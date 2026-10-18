"""Photon 2.0 beta adapter checks; fake transport, real shared conversation core.

No real API keys, SMS/iMessage sends, native daemon or physical device effects.
"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx
from brain.channels.photon import PhotonChannel, PhotonClient, PhotonError, phone_number, stamp
from brain.config import Config
from brain.main import create_app
from test_room_conversation import NativeSession, settings_for

PID = 'pho_prj_' + '0' * 25 + '1'
PHONE, LINE = '+14155550101', '+14155550202'
HUMAN, AGENT, SPACE = 'pho_usr_human', 'pho_usr_agent', 'pho_spc_direct'


class FakeClient:
    project_id = PID
    def __init__(self, clock):
        self.clock = clock
        self.current = []
        self.pages = []
        self.queries = []
        self.sent, self.released, self.allocated = [], [], []
        self.send_error = None
        self.assign_error = None
        self.assign_wait = None
        self.send_wait = None
        self.closed = False

    def assignment(self, handle=PHONE, *, assignment_id='assignment-1'):
        return {'assignmentId': assignment_id, 'assignedPhoneNumber': LINE, 'handle': handle,
                'projectId': PID, 'platform': 'imessage', 'createdAt': stamp(self.clock())}
    async def assignments(self): return list(self.current)
    async def assign(self, handle, key):
        self.allocated.append((handle, key))
        if self.assign_wait:
            await self.assign_wait.wait()
        if self.assign_error: raise self.assign_error
        assignment = self.assignment(handle)
        self.current.append(assignment)
        return assignment
    async def release(self, assignment_id):
        self.released.append(assignment_id)
        self.current = [a for a in self.current if a['assignmentId'] != assignment_id]
    async def messages(self, query):
        self.queries.append(dict(query))
        return self.pages.pop(0) if self.pages else {'items': []}
    async def send(self, space_id, sender_id, text, key):
        self.sent.append((space_id, sender_id, text, key))
        if self.send_wait: await self.send_wait.wait()
        if self.send_error: raise self.send_error
        return {'id': 'pho_msg_outgoing'}
    async def close(self): self.closed = True


class PhotonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.native = NativeSession()
        self.app = create_app(Config('device-secret', 'host-secret', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.core.leases.clock = lambda: self.now
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'private.sqlite3'
        self.client = FakeClient(lambda: self.now)
        self.channel = PhotonChannel(self.core, self.client, self.path)
        self.channel._ready = True  # Manual poll/worker control: no scheduling sleeps in these tests.
        self.spoken = []
        async def speech(frames): self.spoken.append(frames)
        self.core.speech = SimpleNamespace(speak_reply=speech)

    async def asyncTearDown(self):
        if not self.channel._stopped:
            await self.channel.close()
        await self.core.agent.close()
        self.temp.cleanup()

    async def enrolled(self, *, guest=None):
        result = await self.channel.enroll(PHONE, guest_id=getattr(guest, 'guest_id', None))
        return result.lease

    def message(self, message_id='pho_msg_input', text='What should we create?', **changes):
        identity = lambda id, handle, kind: {'id': id, 'handle': handle, 'kind': kind,
                                             'projectId': PID, 'platform': 'imessage'}
        value = {'id': message_id, 'projectId': PID, 'platform': 'imessage', 'status': 'received',
                 'createdAt': stamp(self.now),
                 'sentBy': identity(HUMAN, PHONE, 'human'),
                 'receivedBy': identity(AGENT, LINE, 'agent'),
                 'space': {'id': SPACE, 'projectId': PID, 'platform': 'imessage',
                           'kind': 'direct', 'participantIds': [HUMAN, AGENT]},
                 'content': {'type': 'text', 'format': 'plain', 'text': text}}
        value.update(changes)
        return value

    async def enqueue(self, *messages):
        self.client.pages.append({'items': list(messages)})
        await self.channel.poll_once()

    def outcome(self, message_id='pho_msg_input'):
        row = self.channel.store.db.execute('SELECT outcome FROM claims WHERE message_id=?', (message_id,)).fetchone()
        return row[0] if row else None

    async def test_entering_phone_only_creates_pending_lease_and_actual_text_reaches_shared_native_chat(self):
        result = await self.channel.enroll('+1 (415) 555-0101')
        self.assertTrue(result.new_guest)
        self.assertEqual(result.lease.state, 'joining')
        self.assertEqual(self.native.counter, 0)
        self.assertEqual(result.imessage_number, LINE)
        self.assertTrue(result.sms_link.startswith('sms:' + LINE))
        await self.enqueue(self.message())
        self.assertEqual(self.outcome(), 'CLAIMED')
        self.assertEqual(self.native.counter, 0)  # Durable claim precedes native worker.
        await self.channel.process_one()
        self.assertEqual(result.lease.state, 'active')
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.native.history[-1]['text'], 'What should we create?')
        self.assertEqual(self.client.sent[0], (SPACE, AGENT, 'Native reply: What should we create?',
                                               'tenant-reply-pho_msg_input'))
        self.assertEqual(self.outcome(), 'ACCEPTED')
        self.assertEqual(len(self.spoken), 1)

    async def test_same_authenticated_guest_links_without_renewing_or_rotating_web_credential(self):
        guest = self.core.leases.create()
        secret = self.core.issue_credential(guest.guest_id)
        expiry = guest.expires_at
        await self.core.agent.turn(guest.guest_id, 'My project is called Tenant.')
        self.now += 10
        linked = await self.channel.enroll(PHONE, guest_id=guest.guest_id)
        self.assertIs(linked.lease, guest)
        self.assertFalse(linked.new_guest)
        self.assertEqual(guest.expires_at, expiry)
        self.assertTrue(self.core.authentic_token(guest.guest_id, secret))
        await self.enqueue(self.message(text='Do you remember my project?'))
        await self.channel.process_one()
        self.assertEqual([x.get('text') for x in self.native.history],
                         [None, 'My project is called Tenant.', 'Do you remember my project?'])
        self.assertFalse(any(call[0] == 'revert' for call in self.native.calls))
        await self.core.agent.turn(guest.guest_id, 'Back in web chat.')
        self.assertEqual(self.native.counter, 3)

    async def test_reenrollment_is_idempotent_only_for_same_authenticated_live_guest(self):
        guest = await self.enrolled()
        result = await self.channel.enroll(PHONE, guest_id=guest.guest_id)
        self.assertIs(result.lease, guest)
        self.assertFalse(result.new_guest)
        self.assertEqual(len(self.client.allocated), 1)
        other = self.core.leases.create()
        for guest_id in (None, other.guest_id):
            with self.assertRaises(PhotonError) as error:
                await self.channel.enroll(PHONE, guest_id=guest_id)
            self.assertEqual(error.exception.status, 409)
        self.assertEqual(guest.state, 'joining')

    async def test_preexisting_matching_assignment_reused_but_never_released_as_owned(self):
        self.client.current.append(self.client.assignment())
        guest = await self.enrolled()
        self.assertEqual(self.client.allocated, [])
        self.core.revoke(guest.guest_id)
        await self.channel.maintain()
        self.assertEqual(self.client.released, [])
        self.assertEqual(self.channel.store.bindings(), [])
        self.assertEqual(len(self.client.current), 1)

    async def test_unrelated_preexisting_assignment_is_preserved(self):
        self.client.current.append(self.client.assignment('+14155550303', assignment_id='unrelated'))
        guest = await self.enrolled()
        self.core.revoke(guest.guest_id)
        await self.channel.maintain()
        self.assertEqual(self.client.released, ['assignment-1'])
        self.assertEqual(self.client.current[0]['assignmentId'], 'unrelated')

    async def test_outgoing_foreign_unknown_group_stale_and_wrong_line_messages_are_ignored(self):
        await self.enrolled()
        variants = []
        for path, value in [('status', 'dispatched'), ('platform', 'sms'), ('projectId', 'other'),
                             ('sentBy.handle', '+14155550303'), ('sentBy.kind', 'agent'),
                             ('sentBy.kind', 'unknown'), ('sentBy.projectId', 'other'),
                             ('receivedBy.kind', 'human'), ('receivedBy.handle', '+14155550404'),
                             ('receivedBy.projectId', 'other'), ('space.kind', 'group'),
                             ('space.participantIds', [HUMAN, AGENT, 'third']),
                             ('space.participantIds', [HUMAN, None]),
                             ('space.projectId', 'other'), ('content.type', 'reaction'),
                             ('createdAt', stamp(self.now - 1)), ('createdAt', stamp(self.now + 10))]:
            message = self.message(message_id='pho_msg_' + str(len(variants)))
            keys = path.split('.')
            target = message if len(keys) == 1 else message[keys[0]]
            target[keys[-1]] = value
            variants.append(message)
        await self.enqueue(*variants)
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 0)
        self.assertEqual(self.client.sent, [])

    async def test_pinned_direct_space_sender_and_agent_id_cannot_change(self):
        await self.enrolled()
        await self.enqueue(self.message())
        await self.channel.process_one()
        for field in ('space', 'sender', 'agent'):
            message = self.message(message_id='pho_msg_' + field)
            if field == 'space': message['space']['id'] = 'pho_spc_other'
            if field == 'sender':
                message['sentBy']['id'] = 'pho_usr_other'
                message['space']['participantIds'][0] = 'pho_usr_other'
            if field == 'agent':
                message['receivedBy']['id'] = 'pho_usr_other'
                message['space']['participantIds'][1] = 'pho_usr_other'
            await self.enqueue(message)
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 1)

    async def test_duplicate_input_is_never_executed_or_spoken_twice(self):
        await self.enrolled()
        await self.enqueue(self.message(), self.message())
        await self.channel.process_one()
        await self.enqueue(self.message())
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(len(self.spoken), 1)

    async def test_durable_message_claim_survives_restart_even_when_same_id_reappears(self):
        await self.enrolled()
        await self.enqueue(self.message())
        await self.channel.process_one()
        await self.channel.close()
        self.channel = PhotonChannel(self.core, self.client, self.path)
        self.channel._ready = True
        # Simulate a fresh authenticated enrollment after a restart with a new grant.
        await self.enrolled()
        await self.enqueue(self.message())
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.outcome(), 'ACCEPTED')

    async def test_permission_ending_while_queued_denies_without_native_send_or_speech(self):
        for transition in ('revoke', 'expiry', 'reset'):
            with self.subTest(transition=transition):
                guest = await self.enrolled()
                mid = 'pho_msg_' + transition
                await self.enqueue(self.message(message_id=mid))
                if transition == 'revoke': self.core.revoke(guest.guest_id)
                elif transition == 'expiry': self.now = guest.expires_at
                else: self.core.leases.reset()
                await self.channel.process_one()
                await self.channel.maintain()
                self.assertEqual(self.outcome(mid), 'PERMISSION')
                self.assertEqual(self.channel.store.bindings(), [])
                self.assertEqual(self.native.counter, 0)
                self.assertEqual(self.client.sent, [])
                self.assertEqual(self.spoken, [])

    async def test_revocation_during_native_turn_drops_reply_and_speech(self):
        guest = await self.enrolled()
        self.native.auto_finish = False
        await self.enqueue(self.message())
        work = asyncio.create_task(self.channel.process_one())
        await self.native.started.wait()
        self.core.revoke(guest.guest_id)
        await work
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.outcome(), 'PERMISSION')

    async def test_new_guest_admission_resets_same_native_thread_and_denies_old_photon_queue(self):
        old = await self.enrolled()
        await self.enqueue(self.message(text='Private first guest context'))
        await self.channel.process_one()
        await self.enqueue(self.message(message_id='pho_msg_old_queued'))
        new = self.core.leases.create()
        await self.core.agent.turn(new.guest_id, 'Fresh second guest')
        await self.channel.process_one()
        self.assertEqual(old.state, 'released')
        self.assertEqual(self.outcome('pho_msg_old_queued'), 'PERMISSION')
        self.assertEqual([x.get('text') for x in self.native.history], [None, 'Fresh second guest'])
        self.assertEqual(self.native.thread_id, 'fixed-native-room')
        self.assertEqual(len(self.client.sent), 1)

    async def test_unknown_outbound_acceptance_never_retries_or_speaks(self):
        await self.enrolled()
        self.client.send_error = PhotonError('UNKNOWN')
        await self.enqueue(self.message())
        await self.channel.process_one()
        await self.enqueue(self.message())
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.outcome(), 'UNKNOWN')

    async def test_cancellation_after_send_starts_never_replays_or_speaks(self):
        await self.enrolled()
        self.client.send_wait = asyncio.Event()
        await self.enqueue(self.message())
        work = asyncio.create_task(self.channel.process_one())
        for _ in range(100):
            if self.client.sent: break
            await asyncio.sleep(0)
        self.assertEqual(len(self.client.sent), 1)
        work.cancel()
        with self.assertRaises(asyncio.CancelledError): await work
        await self.enqueue(self.message())
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.outcome(), 'UNKNOWN')
        self.assertEqual(self.spoken, [])

    async def test_revocation_after_photon_acceptance_prevents_optional_speech(self):
        guest = await self.enrolled()
        original = self.client.send
        async def send(*args):
            result = await original(*args)
            self.core.revoke(guest.guest_id)
            return result
        self.client.send = send
        await self.enqueue(self.message())
        await self.channel.process_one()
        self.assertEqual(self.outcome(), 'ACCEPTED')
        self.assertEqual(self.spoken, [])

    async def test_pagination_preserves_query_and_follows_empty_page_tokens(self):
        await self.enrolled()
        self.client.pages.extend([{'items': [], 'nextPageToken': 'page.1'},
                                  {'items': [self.message()], 'nextPageToken': 'page.2'},
                                  {'items': []}])
        await self.channel.poll_once()
        self.assertEqual(len(self.client.queries), 3)
        first = self.client.queries[0]
        self.assertEqual(self.client.queries[1], dict(first, pageToken='page.1'))
        self.assertEqual(self.client.queries[2], dict(first, pageToken='page.2'))
        self.assertEqual(self.channel.queue.qsize(), 1)
        self.assertIsNone(self.channel._page_query)

    async def test_page_work_is_bounded_and_continues_exact_query_next_poll(self):
        await self.enrolled()
        self.client.pages.extend([{'items': [], 'nextPageToken': 'page.' + str(i)} for i in range(6)])
        self.client.pages.append({'items': [self.message()]})
        await self.channel.poll_once()
        self.assertEqual(len(self.client.queries), 5)
        first = self.client.queries[0]
        self.now += 2
        await self.channel.poll_once()
        self.assertEqual(len(self.client.queries), 7)
        self.assertEqual(self.client.queries[5], dict(first, pageToken='page.4'))
        self.assertEqual(self.channel.queue.qsize(), 1)

    async def test_queue_is_bounded_and_dropped_work_is_not_replayed(self):
        await self.enrolled()
        await self.enqueue(*[self.message(message_id='pho_msg_' + str(i)) for i in range(12)])
        self.assertEqual(self.channel.queue.qsize(), 8)
        self.assertEqual(self.outcome('pho_msg_11'), 'DROPPED_BUSY')
        for _ in range(8): await self.channel.process_one()
        await self.enqueue(self.message(message_id='pho_msg_11'))
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 8)

    async def test_allocation_in_flight_is_not_removed_by_cleanup_and_lease_expiry_still_wins(self):
        self.client.assign_wait = asyncio.Event()
        enroll = asyncio.create_task(self.channel.enroll(PHONE))
        for _ in range(100):
            if self.client.allocated: break
            await asyncio.sleep(0)
        await self.channel.maintain()
        self.assertEqual(len(self.channel.store.bindings()), 1)
        row = self.channel.store.bindings()[0]
        self.core.revoke(row['guest_id'])
        self.client.assign_wait.set()
        with self.assertRaises(PhotonError): await enroll
        await self.channel.maintain()
        self.assertEqual(self.client.released, ['assignment-1'])
        self.assertEqual(self.channel.store.bindings(), [])

    async def test_unknown_allocation_keeps_durable_intent_without_post_retry(self):
        self.client.assign_error = PhotonError('UNKNOWN')
        with self.assertRaises(PhotonError): await self.channel.enroll(PHONE)
        await self.channel.maintain()
        self.assertEqual(len(self.channel.store.bindings()), 1)
        self.assertEqual(len(self.client.allocated), 1)
        # A later matching external allocation does not establish ownership.
        self.client.current.append(self.client.assignment())
        await self.channel.maintain()
        self.assertEqual(self.client.released, [])
        self.assertEqual(len(self.channel.store.bindings()), 1)
        self.assertEqual(self.native.counter, 0)

    async def test_orphan_owned_assignment_is_released_on_restart_without_recreating_lease(self):
        guest = await self.enrolled()
        # Close only DB to simulate crash: remote assignment remains.
        self.channel.store.close()
        self.channel._stopped = True
        self.channel = PhotonChannel(self.core, self.client, self.path)
        self.core.leases.leases.clear()
        before = len(self.core.leases.leases)
        await self.channel.maintain()
        self.assertEqual(len(self.core.leases.leases), before)
        self.assertEqual(self.client.released, ['assignment-1'])
        self.assertEqual(self.channel.store.bindings(), [])
        self.assertEqual(self.native.counter, 0)

    async def test_one_lifecycle_poller_and_worker_only_and_clean_close(self):
        self.channel._ready = False
        await self.channel.start()
        task, worker = self.channel._task, self.channel._worker
        await self.channel.start()
        self.assertIs(self.channel._task, task)
        self.assertIs(self.channel._worker, worker)
        await self.channel.close()
        self.assertTrue(task.done())
        self.assertTrue(worker.done())
        self.assertTrue(self.client.closed)

    async def test_storage_and_logs_contain_no_chat_body_or_raw_guest_handle(self):
        await self.enrolled()
        await self.enqueue(self.message(text='SYNTHETIC_PRIVATE_CHAT_BODY'))
        await self.channel.process_one()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        raw = self.path.read_bytes()
        audit = json.dumps(self.core.log.audit_rows)
        self.assertNotIn(PHONE.encode(), raw)
        self.assertNotIn(b'SYNTHETIC_PRIVATE_CHAT_BODY', raw)
        for value in (PHONE, LINE, 'SYNTHETIC_PRIVATE_CHAT_BODY'):
            self.assertNotIn(value, audit)

    async def test_storage_claim_failure_prevents_native_execution(self):
        await self.enrolled()
        def fail(*args): raise __import__('sqlite3').OperationalError('synthetic')
        self.channel.store.claim = fail
        with self.assertRaises(__import__('sqlite3').OperationalError):
            await self.enqueue(self.message())
        self.assertEqual(self.native.counter, 0)
        self.assertTrue(self.channel.queue.empty())


    async def test_broken_store_during_startup_and_close_still_closes_http_and_database(self):
        import sqlite3
        closed = []
        original = self.channel.store.close
        def store_close():
            closed.append(True)
            original()
        def fail(): raise sqlite3.OperationalError('synthetic storage failure')
        self.channel.store.close = store_close
        self.channel.store.bindings = fail
        with self.assertRaises(sqlite3.OperationalError): await self.channel.start()
        with self.assertRaises(sqlite3.OperationalError): await self.channel.close()
        self.assertTrue(self.client.closed)
        self.assertEqual(closed, [True])
        await self.channel.close()  # Idempotent after a failed cleanup attempt.

    async def test_prefailed_worker_cannot_prevent_peer_settlement_or_resource_close(self):
        async def fail(): raise RuntimeError('synthetic worker failure')
        async def wait(): await asyncio.Event().wait()
        self.channel._worker = asyncio.create_task(fail())
        self.channel._task = asyncio.create_task(wait())
        await asyncio.sleep(0)
        await self.channel.close()
        self.assertTrue(self.channel._worker.done())
        self.assertTrue(self.channel._task.done())
        self.assertTrue(self.client.closed)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_beta_client_contract_no_parent_no_retries_and_custom_user_agent(self):
        requests = []
        def reply(request):
            requests.append(request)
            if request.method == 'GET' and request.url.path.endswith('/assignments'):
                if request.url.params.get('pageToken') == 'empty.next':
                    return httpx.Response(200, json={'assignments': []})
                return httpx.Response(200, json={'assignments': [], 'nextPageToken': 'empty.next'})
            if request.method == 'POST' and request.url.path.endswith('/messages'):
                return httpx.Response(202, json={'id': 'pho_msg_outgoing'})
            if request.method == 'DELETE': return httpx.Response(200, json={})
            return httpx.Response(201, json={'assignmentId': 'assignment'})
        client = PhotonClient(PID, 'synthetic-api-key', transport=httpx.MockTransport(reply))
        try:
            self.assertEqual(await client.assignments(), [])
            await client.assign(PHONE, 'assignment-key')
            await client.send(SPACE, AGENT, 'Synthetic reply.', 'reply-key')
            await client.release('assignment')
            self.assertEqual(len(requests), 5)
            for request in requests:
                self.assertEqual(request.headers['authorization'], 'Bearer synthetic-api-key')
                self.assertTrue(request.headers['user-agent'].startswith('tenant-dubhacks/'))
                self.assertTrue(request.url.path.startswith('/v1/projects/' + PID + '/'))
            outbound = json.loads(requests[3].content)
            self.assertNotIn('parentMessageId', outbound)
            self.assertEqual(requests[3].headers['idempotency-key'], 'reply-key')
        finally: await client.close()

    async def test_unknown_send_is_single_attempt_with_redacted_error(self):
        calls = []
        def reply(request):
            calls.append(request)
            raise httpx.ReadTimeout('SYNTHETIC_SECRET_URL', request=request)
        client = PhotonClient(PID, 'synthetic-api-key', transport=httpx.MockTransport(reply))
        try:
            with self.assertRaises(PhotonError) as error:
                await client.send(SPACE, AGENT, 'Private reply.', 'reply-key')
            self.assertEqual(error.exception.code, 'UNKNOWN')
            self.assertNotIn('SYNTHETIC_SECRET_URL', str(error.exception))
            self.assertEqual(len(calls), 1)
        finally: await client.close()

    def test_phone_normalization_rejects_non_e164_or_arbitrary_input(self):
        self.assertEqual(phone_number('+1 (415) 555-0101'), PHONE)
        for value in (None, '', '4155550101', '+0123', 'name@example.test', {'phone': PHONE}):
            with self.assertRaises(PhotonError): phone_number(value)


if __name__ == '__main__': unittest.main()


class PhotonRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.native = NativeSession()
        self.channels = []
        def factory(core):
            channel = PhotonChannel(core, FakeClient(core.leases.clock), Path(self.temp.name) / 'private.sqlite3')
            self.channels.append(channel)
            return channel
        self.app = create_app(Config('device', 'host', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native), photon_factory=factory)
        self.client = self.enterContext(TestClient(self.app, base_url='https://tenant.test'))
        self.headers = {'origin': 'https://tenant.test'}
        self.channel = self.channels[0]
        self.core = self.app.state.core

    def join(self, **fields):
        return self.client.post('/join', headers=self.headers, json={'room_code': 'TEST', **fields})

    def test_phone_join_keeps_existing_ui_response_and_waits_for_real_inbound(self):
        response = self.join(phone=PHONE)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(set(result), {'guest_id', 'guest_token', 'chat_url', 'imessage_number', 'sms_link'})
        self.assertEqual(result['imessage_number'], LINE)
        self.assertEqual(self.core.leases.leases[result['guest_id']].state, 'joining')
        self.assertTrue(self.core.authentic_token(result['guest_id'], result['guest_token']))
        self.assertEqual(self.native.counter, 0)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_existing_web_guest_cookie_link_preserves_exact_secret_and_expiry(self):
        guest = self.join().json()
        before = self.core.leases.leases[guest['guest_id']].expires_at
        linked = self.join(phone=PHONE, guest_id=guest['guest_id'])
        self.assertEqual(linked.status_code, 200)
        result = linked.json()
        self.assertEqual(result['guest_id'], guest['guest_id'])
        self.assertEqual(result['guest_token'], guest['guest_token'])
        self.assertEqual(result['chat_url'], guest['chat_url'])
        self.assertEqual(self.core.leases.leases[guest['guest_id']].expires_at, before)
        self.assertEqual(len(self.core.leases.leases), 1)

    def test_existing_link_requires_exact_token_or_cookie_before_any_api_work(self):
        guest = self.join().json()
        self.client.cookies.clear()
        for fields in ({}, {'guest_token': 'wrong'}, {'guest_token': {'invalid': True}}):
            response = self.join(phone=PHONE, guest_id=guest['guest_id'], **fields)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.channel.client.allocated, [])
        response = self.join(phone=PHONE, guest_id=guest['guest_id'], guest_token=guest['guest_token'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['guest_token'], guest['guest_token'])

    def test_repeat_phone_only_join_recovers_same_enrollment_with_own_exact_cookie(self):
        first = self.join(phone=PHONE).json()
        lease = self.core.leases.leases[first['guest_id']]
        original_deadlines = (lease.expires_at, lease.joining_until)
        allocations = len(self.channel.client.allocated)
        repeated = self.join(phone=PHONE)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), first)
        self.assertEqual(len(self.core.leases.leases), 1)
        self.assertEqual((lease.expires_at, lease.joining_until), original_deadlines)
        self.assertEqual(len(self.channel.client.allocated), allocations)
        self.assertEqual(self.native.counter, 0)

    def test_repeat_phone_cookie_recovery_preserves_active_shared_context_without_new_native_turn(self):
        first = self.join(phone=PHONE).json()
        lease = self.core.leases.leases[first['guest_id']]
        self.client.portal.call(self.core.agent.turn, lease.guest_id, 'Existing shared guest context.')
        before = (lease.expires_at, lease.joining_until, self.native.counter, list(self.native.history))
        recovered = self.join(phone=PHONE)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json(), first)
        self.assertEqual((lease.expires_at, lease.joining_until, self.native.counter, self.native.history), before)
        self.assertEqual(lease.state, 'active')
        self.assertEqual(len(self.channel.client.allocated), 1)

    def test_phone_only_recovery_rejects_other_browser_guest_cookie_and_wrong_token(self):
        first = self.join(phone=PHONE).json()
        self.client.cookies.clear()
        # Neither a number alone nor another legitimate guest cookie owns the binding.
        self.assertEqual(self.join(phone=PHONE).status_code, 409)
        other = self.join().json()
        self.assertNotEqual(other['guest_id'], first['guest_id'])
        for fields in ({}, {'guest_token': 'wrong'}, {'guest_token': other['guest_token']}):
            result = self.join(phone=PHONE, **fields)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json()['code'], 'PHONE_IN_USE')
        self.assertEqual(len(self.channel.client.allocated), 1)
        self.assertEqual(self.native.counter, 0)
        # The exact matching original token can recover even without its cookie.
        recovered = self.join(phone=PHONE, guest_token=first['guest_token'])
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json(), first)

    def test_bad_explicit_recovery_token_does_not_fall_back_to_valid_cookie(self):
        first = self.join(phone=PHONE).json()
        rejected = self.join(phone=PHONE, guest_token='wrong')
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()['code'], 'PHONE_IN_USE')
        self.assertEqual(len(self.channel.client.allocated), 1)
        self.assertTrue(self.core.authentic_token(first['guest_id'], first['guest_token']))

    def test_expired_bound_cookie_cannot_recover_or_renew_its_lease(self):
        first = self.join(phone=PHONE).json()
        lease = self.core.leases.leases[first['guest_id']]
        lease.joining_until = 0
        expiry = lease.expires_at
        rejected = self.join(phone=PHONE)
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()['code'], 'GUEST_EXPIRED')
        self.assertEqual(len(self.channel.client.allocated), 1)
        self.assertEqual(len(self.core.leases.leases), 1)
        self.assertEqual(lease.expires_at, expiry)
        self.assertEqual(lease.state, 'expired')
        self.assertEqual(self.native.counter, 0)

    def test_join_error_text_distinguishes_invalid_number_active_setup_and_unconfirmed_service(self):
        invalid = self.join(phone='invalid')
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()['code'], 'INVALID_PHONE')
        self.assertIn('country code', invalid.json()['error'])
        self.channel.client.assign_error = PhotonError('UNKNOWN')
        unknown = self.join(phone=PHONE)
        self.assertEqual(unknown.json()['code'], 'UNKNOWN')
        self.assertIn('could not be confirmed', unknown.json()['error'])
        # An unresolved allocation intent remains distinct from an active setup.
        unresolved = self.join(phone=PHONE)
        self.assertEqual(unresolved.status_code, 409)
        self.assertEqual(unresolved.json()['code'], 'SETUP_UNCONFIRMED')
        self.assertIn('unconfirmed', unresolved.json()['error'])
        self.assertEqual(len(self.channel.client.allocated), 1)

    def test_join_error_audit_records_only_fixed_safe_code_and_status(self):
        self.join(phone='synthetic-invalid-phone-private-value', guest_token='synthetic-private-token')
        audit = self.core.log.audit_rows[-1]
        self.assertEqual(audit['audit'], {'photon_status': 'JOIN_REJECTED',
                                          'code': 'INVALID_PHONE', 'http_status': 400})
        rendered = json.dumps(self.core.log.audit_rows)
        self.assertNotIn('synthetic-invalid-phone-private-value', rendered)
        self.assertNotIn('synthetic-private-token', rendered)
        self.assertNotIn(PHONE, rendered)
        self.assertEqual(self.native.counter, 0)
        self.assertEqual(self.channel.client.allocated, [])

    def test_implicit_cookie_recovery_rechecks_permission_after_waiting_for_enrollment_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        first = self.join(phone=PHONE).json()
        lease = self.core.leases.leases[first['guest_id']]
        deadlines = (lease.expires_at, lease.joining_until)
        reached_enroll = asyncio.Event()
        original = self.channel.enroll
        async def entering(*args, **kwargs):
            # The route has already matched the original cookie to this binding.
            reached_enroll.set()
            return await original(*args, **kwargs)
        self.channel.enroll = entering
        self.client.portal.call(self.channel._enroll_lock.acquire)
        with ThreadPoolExecutor() as pool:
            waiting = pool.submit(self.join, phone=PHONE)
            self.client.portal.call(reached_enroll.wait)
            self.client.portal.call(self.core.revoke, first['guest_id'])
            self.client.portal.call(self.channel._enroll_lock.release)
            result = waiting.result(timeout=2)
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()['code'], 'INVITATION_EXPIRED')
        self.assertEqual(lease.state, 'released')
        self.assertEqual((lease.expires_at, lease.joining_until), deadlines)
        self.assertEqual(len(self.channel.client.allocated), 1)
        self.assertEqual(len(self.core.credentials), 1)
        self.assertTrue(self.core.authentic_token(lease.guest_id, first['guest_token']))
        self.assertEqual(self.native.counter, 0)

    def test_phone_join_never_bypasses_origin_or_current_invitation(self):
        before = len(self.core.leases.leases)
        for headers, code, expected in [({}, 'TEST', 403),
                                        ({'origin': 'https://foreign.test'}, 'TEST', 403),
                                        (self.headers, 'OLD', 404)]:
            response = self.client.post('/join', headers=headers, json={'room_code': code, 'phone': PHONE})
            self.assertEqual(response.status_code, expected)
        self.assertEqual(len(self.core.leases.leases), before)
        self.assertEqual(self.channel.client.allocated, [])

    def test_host_reset_during_assignment_preflight_cannot_mint_postreset_guest(self):
        from concurrent.futures import ThreadPoolExecutor
        ready, release = asyncio.Event(), asyncio.Event()
        original = self.channel.client.assignments
        async def slow():
            ready.set()
            await release.wait()
            return await original()
        self.channel.client.assignments = slow
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(self.join, phone=PHONE)
            self.client.portal.call(ready.wait)
            self.client.portal.call(self.core.leases.reset)
            self.client.portal.call(release.set)
            result = pending.result(timeout=2)
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.core.leases.leases, {})
        self.assertEqual(self.core.credentials, {})
        self.assertEqual(self.channel.client.allocated, [])

    def test_link_revoke_during_preflight_cannot_allocate_or_reissue_credential(self):
        from concurrent.futures import ThreadPoolExecutor
        guest = self.join().json()
        ready, release = asyncio.Event(), asyncio.Event()
        original = self.channel.client.assignments
        async def slow():
            ready.set()
            await release.wait()
            return await original()
        self.channel.client.assignments = slow
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(self.join, phone=PHONE, guest_id=guest['guest_id'])
            self.client.portal.call(ready.wait)
            self.client.portal.call(self.core.revoke, guest['guest_id'])
            self.client.portal.call(release.set)
            result = pending.result(timeout=2)
        self.assertEqual(result.status_code, 404)  # Admission epoch changed.
        self.assertEqual(self.channel.client.allocated, [])
        self.assertEqual(len(self.core.credentials), 1)
        self.assertTrue(self.core.authentic_token(guest['guest_id'], guest['guest_token']))
        self.assertIsNone(self.core.leases.current(guest['guest_id']))

    def test_disabled_channel_is_503_even_if_environment_has_keys(self):
        from fastapi.testclient import TestClient
        app = create_app(Config('device', 'host', 'TEST', 'https://tenant.test'))
        with TestClient(app, base_url='https://tenant.test') as client:
            response = client.post('/join', headers=self.headers, json={'room_code': 'TEST', 'phone': PHONE})
            self.assertEqual(response.status_code, 503)
            self.assertIsNone(app.state.core.photon)
            self.assertEqual(app.state.core.leases.leases, {})

    def test_factory_requires_conversation_mode_and_explicit_opt_in(self):
        import os
        from unittest.mock import patch
        from brain.main import runtime_photon_factory
        with patch.dict(os.environ, {'PHOTON_PROJECT_ID': PID, 'PHOTON_API_KEY': 'synthetic'}, clear=True):
            self.assertIsNone(runtime_photon_factory(settings_for(self.native)))
        with patch.dict(os.environ, {'TENANT_PHOTON_ENABLED': '1'}, clear=True):
            with self.assertRaises(ValueError): runtime_photon_factory(None)
        with self.assertRaises(ValueError):
            create_app(Config('device', 'host'), photon_factory=lambda _core: object())
