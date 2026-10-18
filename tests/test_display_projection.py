"""Public display contract, using real channel/controller code and fake I/O only."""
import asyncio
import json
import unittest

from fastapi import WebSocketDisconnect
from brain.channels.webchat import guest_socket
from brain.core.guest_view import GuestPublisher
from brain.config import Config
from brain.main import create_app
from test_guest_view import ChannelSocket
from test_room_conversation import Clock, NativeSession, settings_for
import test_photon as photon_fixture
from brain.channels.photon import PhotonError


class DisplayProjectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.native, self.clock = NativeSession(), Clock()
        self.app = create_app(Config('device-secret', 'host-secret', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.core.leases.clock = self.clock
        self.lease = self.core.leases.create()
        self.socket = ChannelSocket(self.app, self.lease.guest_id, '', origin='https://tenant.test')
        self.publisher = GuestPublisher(self.core, self.lease.guest_id, self.socket)

    async def asyncTearDown(self):
        await self.core.agent.close()

    def transcript(self, lease=None):
        guest_id = (lease or self.lease).guest_id
        return next(row['transcript'] for row in self.core.snapshot()['guests'] if row['guest_id'] == guest_id)

    async def exchange(self, text):
        frames = await self.core.agent.turn(self.lease.guest_id, text)
        await self.publisher.send_batch(frames)
        return frames

    async def test_web_socket_publication_end_to_end_and_no_history_or_receipt_leak(self):
        initial = self.core.snapshot()['guests'][0]
        self.assertEqual((initial['expires_in'], initial['lease_total']), (120, 120))
        self.socket.query_params['token'] = self.core.issue_credential(self.lease.guest_id)
        self.core.leases.sessions[self.lease.guest_id].messages.append({'content': 'PRIVATE MODEL HISTORY'})
        self.native.history[0]['private'] = 'PRIVATE NATIVE ANCHOR'
        handler = asyncio.create_task(guest_socket(self.socket))
        try:
            self.assertEqual((await self.socket.outgoing.get())['type'], 'lease')
            await self.socket.incoming.put({'type': 'user', 'text': 'A room question'})
            reply = await asyncio.wait_for(self.socket.outgoing.get(), 1)
            self.assertEqual(reply, {'type': 'assistant', 'text': 'Native reply: A room question'})
            await asyncio.sleep(0)  # send_json deliberately yields before its successful return.
            transcript = self.transcript()
            self.assertEqual(initial['transcript'], [])
            self.assertEqual(self.core.snapshot()['guests'][0]['lease_total'], 600)
            self.assertEqual(transcript, [
                {'role': 'guest', 'text': 'A room question', 't': 1000},
                {'role': 'room', 'text': reply['text'], 't': 1000}])
            encoded = json.dumps(self.core.snapshot())
            for private in ('PRIVATE MODEL HISTORY', 'PRIVATE NATIVE ANCHOR', 'completed_reply',
                            'device-secret', 'host-secret', 'generation', 'fixed-native-room'):
                self.assertNotIn(private, encoded)
        finally:
            await self.socket.incoming.put(WebSocketDisconnect(1000))
            await handler

    async def test_validated_input_only_and_failed_web_publish_does_not_add_room_reply(self):
        for invalid in ('', ' ' * 4, None, 9, 'x' * 8001):
            await self.exchange(invalid)
        self.assertEqual(self.transcript(), [])
        self.lease.scopes = {'light'}
        await self.exchange('Not authorized for native control')
        self.assertEqual(self.transcript(), [])
        self.lease.scopes = {'*'}
        frames = await self.core.agent.turn(self.lease.guest_id, 'Accepted input')
        self.assertEqual([row['role'] for row in self.transcript()], ['guest'])
        self.socket.fail_send = True
        with self.assertRaises(WebSocketDisconnect):
            await self.publisher.send_batch(frames)
        self.assertEqual([row['role'] for row in self.transcript()], ['guest'])

    async def test_final_redacted_wire_text_only_and_duplicate_publication_once(self):
        self.native.auto_finish = False
        task = asyncio.create_task(self.core.agent.turn(self.lease.guest_id, 'host-secret question'))
        await self.native.started.wait()
        for item in ({'type': 'agentMessage', 'phase': 'commentary', 'text': 'PRIVATE COMMENTARY'},
                     {'type': 'commandExecution', 'text': 'PRIVATE TOOL OUTPUT'}):
            await self.native.events.put({'method': 'item/completed', 'params': {
                'threadId': self.native.thread_id, 'turnId': 'native-1', 'item': item}})
        await self.native.finish('native-1', 'Answer containing host-secret and device-secret')
        frames = await task
        await self.publisher.send_batch(frames)
        await self.publisher.send_batch(frames)  # Same turn on another delivery path is still one row.
        self.assertEqual([row['text'] for row in self.transcript()], [
            '[private value] question', 'Answer containing [private value] and [private value]'])
        self.assertEqual(self.transcript()[-1]['text'], self.socket.frames[-1]['text'])
        self.core.published_reply(self.lease.guest_id, frames, 'changed wire text')
        await self.publisher.send_batch([{'type': 'assistant', 'text': 'Unreceipted status'},
                                         {'type': 'action', 'text': 'Private action receipt'}])
        self.assertEqual(len(self.transcript()), 2)

    async def test_last_ten_order_detached_snapshots_and_issued_totals(self):
        self.core.leases.active_ttl, self.core.leases.joining_ttl = 75, 12
        self.lease = self.core.leases.create()
        self.publisher = GuestPublisher(self.core, self.lease.guest_id, self.socket)
        first = next(g for g in self.core.snapshot()['guests'] if g['guest_id'] == self.lease.guest_id)
        self.assertEqual((first['expires_in'], first['lease_total'], first['transcript']), (12, 12, []))
        expiry = self.lease.expires_at
        for index in range(7):
            self.clock.now += 1
            await self.exchange(str(index))
        rows = self.transcript()
        self.assertEqual([row['text'] for row in rows], [text for i in range(2, 7)
                         for text in (str(i), 'Native reply: ' + str(i))])
        self.assertEqual([row['t'] for row in rows], sorted(row['t'] for row in rows))
        rows[0]['text'] = 'MUTATED'
        rows.append({'role': 'guest', 'text': 'INJECTED'})
        self.assertNotIn('MUTATED', json.dumps(self.transcript()))
        self.assertNotIn('INJECTED', json.dumps(self.transcript()))
        active = self.core.snapshot()['guests'][0]
        self.assertEqual((active['lease_total'], active['expires_in']), (75, 68))
        self.assertEqual(self.lease.expires_at, expiry)
        self.core.leases.active_ttl = 900  # Changing defaults cannot rewrite existing grant totals.
        self.assertEqual(self.core.snapshot()['guests'][0]['lease_total'], 75)

    async def test_joining_total_is_capped_by_shorter_original_access_grant(self):
        self.core.leases.active_ttl, self.core.leases.joining_ttl = 9, 120
        short = self.core.leases.create()
        row = next(g for g in self.core.snapshot()['guests'] if g['guest_id'] == short.guest_id)
        self.assertEqual((row['lease_total'], row['expires_in']), (9, 9))

    async def test_controller_priority_fresh_guest_empty_and_late_handoff_reply_excluded(self):
        unused = self.core.leases.create()
        frames = await self.exchange('First context')
        another_join = self.core.leases.create()
        self.assertEqual(self.core.snapshot()['guests'][0]['guest_id'], self.lease.guest_id)
        self.assertEqual(self.transcript(another_join), [])
        replacement = await self.core.agent.turn(unused.guest_id, 'Replacement context')
        await GuestPublisher(self.core, unused.guest_id, self.socket).send_batch(replacement)
        await self.publisher.send_batch(frames)
        snapshot = self.core.snapshot()
        self.assertEqual(snapshot['guests'][0]['guest_id'], unused.guest_id)
        self.assertNotIn('First context', json.dumps(snapshot))
        self.assertEqual(self.core.leases.sessions[self.lease.guest_id].transcript, [])
        self.assertEqual([r['text'] for r in self.transcript(unused)],
                         ['Replacement context', 'Native reply: Replacement context'])

    async def test_revoke_expiry_reset_foreign_room_and_health_hide_projection(self):
        frames = await self.exchange('Before revoke')
        self.core.revoke(self.lease.guest_id)
        await self.publisher.send_batch(frames)
        self.assertEqual(self.core.snapshot()['guests'], [])
        self.lease = self.core.leases.create()
        await self.core.agent.turn(self.lease.guest_id, 'Before expiry')
        self.clock.now = self.lease.expires_at
        self.assertEqual(self.core.snapshot()['guests'], [])
        self.assertEqual(self.core.leases.sessions[self.lease.guest_id].transcript, [])
        fresh = self.core.leases.create()
        fresh.room_id = 'foreign'
        self.assertEqual(self.core.snapshot()['guests'], [])
        self.lease = self.core.leases.create()
        await self.core.agent.turn(self.lease.guest_id, 'Before reset')
        await self.core.reset()
        self.assertEqual(self.core.snapshot()['guests'], [])
        fresh = self.core.leases.create()
        self.core.registry.persistence_healthy = False
        self.assertEqual(self.core.snapshot()['guests'], [])

    async def test_revoke_during_successful_web_send_does_not_restore_projection(self):
        frames = await self.core.agent.turn(self.lease.guest_id, 'A late send')
        original = self.socket.send_json
        async def revoked_send(frame):
            await original(frame)
            self.core.revoke(self.lease.guest_id)
        self.socket.send_json = revoked_send
        await self.publisher.send_batch(frames)
        self.assertEqual(self.core.snapshot()['guests'], [])
        self.assertEqual(self.core.leases.sessions[self.lease.guest_id].transcript, [])


class PhotonProjectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = photon_fixture.PhotonTests.setUp
    asyncTearDown = photon_fixture.PhotonTests.asyncTearDown
    enrolled = photon_fixture.PhotonTests.enrolled
    message = photon_fixture.PhotonTests.message
    enqueue = photon_fixture.PhotonTests.enqueue
    outcome = photon_fixture.PhotonTests.outcome

    def transcript(self):
        return self.core.snapshot()['guests'][0]['transcript']

    async def test_successful_publication_once_for_duplicate_inbound_and_linked_web(self):
        guest = await self.enrolled()
        expiry = guest.expires_at
        message = self.message(text='Shared context')
        await self.enqueue(message, message)
        await self.channel.process_one()
        await self.enqueue(message)
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 1)
        self.assertEqual([r['text'] for r in self.transcript()], ['Shared context', 'Native reply: Shared context'])
        frames = await self.core.agent.turn(guest.guest_id, 'Web follow-up')
        socket = ChannelSocket(self.app, guest.guest_id, '')
        await GuestPublisher(self.core, guest.guest_id, socket).send_batch(frames)
        self.assertEqual([r['role'] for r in self.transcript()], ['guest', 'room', 'guest', 'room'])
        self.assertEqual(guest.expires_at, expiry)

    async def test_uncertain_photon_send_records_input_only_and_never_retries(self):
        await self.enrolled()
        self.client.send_error = PhotonError('TIMEOUT')
        message = self.message()
        await self.enqueue(message)
        await self.channel.process_one()
        self.assertEqual(self.outcome(), 'UNKNOWN')
        self.assertEqual([r['role'] for r in self.transcript()], ['guest'])
        await self.enqueue(message)
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual((self.native.counter, len(self.client.sent)), (1, 1))

    async def test_late_photon_acceptance_after_revoke_cannot_repopulate(self):
        guest = await self.enrolled()
        self.client.send_wait = asyncio.Event()
        await self.enqueue(self.message())
        task = asyncio.create_task(self.channel.process_one())
        for _ in range(100):
            if self.client.sent:
                break
            await asyncio.sleep(.001)
        self.assertEqual(len(self.client.sent), 1)
        self.core.revoke(guest.guest_id)
        self.client.send_wait.set()
        await task
        self.assertEqual(self.outcome(), 'ACCEPTED')
        self.assertEqual(self.core.snapshot()['guests'], [])
        self.assertEqual(self.core.leases.sessions[guest.guest_id].transcript, [])
