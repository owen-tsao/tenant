"""Offline exact-turn steering: fake daemon and fake native controller only."""
import asyncio
import copy
import json
from types import SimpleNamespace
import unittest

from agent.room_session import RoomSession, RoomSessionError
from brain.core.conversation_speech import ReplyFrames
from brain.core.room_conversation import ConversationAgent
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.state import Room
from tests.test_room_session import Socket, THREAD as PROTOCOL_THREAD
from tests.test_room_conversation import NativeSession, Clock, settings_for


class SteeringSocket(Socket):
    def __init__(self):
        super().__init__()
        self.steer_sent = asyncio.Event()
        self.hold_steer = False
        self.steer_ack = 'turn1'
        self.steer_error = None
        self.before_queue_reply = None
        self.before_steer_ack = None

    async def send(self, raw):
        frame = json.loads(raw)
        if frame.get('method') == 'turn/steer':
            self.sent.append(frame)
            self.steer_sent.set()
            if self.before_steer_ack:
                await self.before_steer_ack()
            if not self.hold_steer:
                await self.ack(frame)
            return
        if frame.get('method') == 'thread/queue/list' and self.before_queue_reply:
            self.before_queue_reply()
        await super().send(raw)

    async def ack(self, frame):
        if self.steer_error is not None:
            await self.emit({'id': frame['id'], 'error': {'code': self.steer_error, 'message': 'private rejection'}})
        else:
            await self.emit({'id': frame['id'], 'result': {'turnId': self.steer_ack}})

    def steers(self):
        return [frame for frame in self.sent if frame.get('method') == 'turn/steer']


class SteeringProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket = SteeringSocket()
        async def connector(*args, **kwargs):
            return self.socket
        self.client = RoomSession(PROTOCOL_THREAD, connector=connector, request_timeout=.04)
        self.addAsyncCleanup(self.client.close)
        await self.client.connect()
        await self.client.start_turn('Original ongoing task')

    async def steer(self, text='Add the lights', expected='turn1', authorize=None):
        return await self.client.steer_turn(text, expected_turn_id=expected, authorize=authorize)

    async def test_exact_steer_contract_does_not_start_or_interrupt_or_consume_events(self):
        before = self.client._events.qsize()
        exact = '  Add the lights.\nKeep the music.  '
        self.assertEqual(await self.steer(exact), 'turn1')
        frame = self.socket.steers()[0]
        self.assertEqual(frame['params'], {'threadId': PROTOCOL_THREAD,
            'input': [{'type': 'text', 'text': exact}], 'expectedTurnId': 'turn1'})
        self.assertEqual(self.client._events.qsize(), before)
        self.assertEqual(self.client.active_turn_id, 'turn1')
        self.assertEqual(sum(f.get('method') == 'turn/start' for f in self.socket.sent), 1)
        self.assertFalse(any(f.get('method') == 'turn/interrupt' for f in self.socket.sent))

    async def test_stale_expected_turn_and_invalid_text_never_send_steer(self):
        for text, expected in [('valid', 'stale-turn'), ('', 'turn1'), (' ' * 2, 'turn1'),
                               ('x' * 8001, 'turn1'), (None, 'turn1'), ('valid', None)]:
            with self.subTest(expected=expected, text_type=type(text).__name__):
                with self.assertRaises((RoomSessionError, ValueError)):
                    await self.steer(text, expected)
        self.assertFalse(self.socket.steers())
        self.assertEqual(self.client.active_turn_id, 'turn1')

    async def test_authorization_denied_before_queue_check(self):
        before = len(self.socket.sent)
        with self.assertRaises(RoomSessionError):
            await self.steer(authorize=lambda: False)
        self.assertEqual(len(self.socket.sent), before)

    async def test_authorization_revoked_while_serialization_lock_waits(self):
        allowed = True
        await self.client._start_lock.acquire()
        pending = asyncio.create_task(self.steer(authorize=lambda: allowed))
        await asyncio.sleep(0)
        allowed = False
        self.client._start_lock.release()
        with self.assertRaises(RoomSessionError):
            await pending
        self.assertFalse(self.socket.steers())
        self.assertEqual(self.client.active_turn_id, 'turn1')

    async def test_revoked_after_rpc_ack_never_claims_followup_accepted(self):
        allowed = True
        async def revoke():
            nonlocal allowed
            allowed = False
        self.socket.before_steer_ack = revoke
        with self.assertRaises(RoomSessionError):
            await self.steer(authorize=lambda: allowed)
        self.assertEqual(len(self.socket.steers()), 1)
        self.assertFalse(any(f.get('method') == 'turn/interrupt' for f in self.socket.sent))
        self.assertEqual(self.client.active_turn_id, 'turn1')

    async def test_mismatched_ack_latches_uncertainty_without_interrupting_original(self):
        self.socket.steer_ack = 'different-turn'
        with self.assertRaises(RoomSessionError) as caught:
            await self.steer()
        self.assertTrue(caught.exception.outcome_unknown)
        with self.assertRaises(RoomSessionError):
            await self.steer('Another followup')
        self.assertEqual(len(self.socket.steers()), 1)
        self.assertEqual(self.client.active_turn_id, 'turn1')
        self.assertFalse(any(f.get('method') == 'turn/interrupt' for f in self.socket.sent))

    async def test_timeout_never_replays_or_consumes_original_completion(self):
        self.socket.hold_steer = True
        with self.assertRaises(RoomSessionError) as caught:
            await self.steer()
        self.assertTrue(caught.exception.outcome_unknown)
        with self.assertRaises(RoomSessionError):
            await self.steer('Never replay')
        self.assertEqual(len(self.socket.steers()), 1)
        await self.socket.emit({'method': 'turn/completed', 'params': {'threadId': PROTOCOL_THREAD,
            'turn': {'id': 'turn1', 'status': 'completed'}}})
        events = [await asyncio.wait_for(self.client.next_event(), .1) for _ in range(2)]
        self.assertEqual([event['method'] for event in events], ['turn/started', 'turn/completed'])
        self.assertIsNone(self.client.active_turn_id)
        self.assertFalse(any(f.get('method') == 'turn/interrupt' for f in self.socket.sent))

    async def test_known_rejection_preserves_active_turn_and_does_not_fallback(self):
        self.socket.steer_error = 409
        with self.assertRaises(RoomSessionError):
            await self.steer()
        self.assertEqual(len(self.socket.steers()), 1)
        self.assertEqual(sum(f.get('method') == 'turn/start' for f in self.socket.sent), 1)
        self.assertEqual(self.client.active_turn_id, 'turn1')
        self.assertFalse(any(f.get('method') == 'turn/interrupt' for f in self.socket.sent))

    async def test_concurrent_steers_serialize_same_exact_active_turn(self):
        self.socket.hold_steer = True
        first = asyncio.create_task(self.steer('First followup'))
        await self.socket.steer_sent.wait()
        second = asyncio.create_task(self.steer('Second followup'))
        await asyncio.sleep(0)
        self.assertEqual(len(self.socket.steers()), 1)
        self.socket.hold_steer = False
        await self.socket.ack(self.socket.steers()[0])
        self.assertEqual(await first, 'turn1')
        self.assertEqual(await second, 'turn1')
        self.assertEqual([frame['params']['input'][0]['text'] for frame in self.socket.steers()],
                         ['First followup', 'Second followup'])

    async def test_matching_completion_before_steer_ack_does_not_consume_or_reject_ack(self):
        async def complete():
            await self.socket.emit({'method': 'turn/completed', 'params': {'threadId': PROTOCOL_THREAD,
                'turn': {'id': 'turn1', 'status': 'completed'}}})
        self.socket.before_steer_ack = complete
        self.assertEqual(await self.steer(authorize=lambda: True), 'turn1')
        self.assertIsNone(self.client.active_turn_id)
        self.assertEqual(self.client._events.qsize(), 2)


class SteeringNative(NativeSession):
    def __init__(self):
        super().__init__()
        self.auto_finish = False
        self.steers = []
        self.steer_entered = asyncio.Event()
        self.steer_release = asyncio.Event()
        self.steer_release.set()
        self.steer_error = None
        self.steer_ack = None
        self.before_ack = None

    async def steer_turn(self, text, *, expected_turn_id, authorize=None):
        if authorize is not None and not authorize():
            raise RoomSessionError('access ended')
        if self.active_turn_id != expected_turn_id:
            raise RoomSessionError('different active turn')
        self.steers.append((text, expected_turn_id))
        self.steer_entered.set()
        await self.steer_release.wait()
        if self.before_ack:
            self.before_ack()
        if self.steer_error:
            raise self.steer_error
        if authorize is not None and not authorize():
            raise RoomSessionError('access ended after acknowledgement', outcome_unknown=True)
        return self.steer_ack or expected_turn_id


class DeviceGrants:
    def __init__(self):
        self.calls = []
    def revoke_all(self): self.calls.append('revoke_all')
    async def prepare(self, guest, generation, lease, thread):
        self.calls.append('prepare')
        return SimpleNamespace(guest_id=guest, generation=generation, lease=lease, turn_id=None,
                               explicit_speech_attempted=False)
    def context(self, grant): return 'Current private helper context.'
    def redact(self, text): return text
    def activate(self, grant, turn_id):
        grant.turn_id = turn_id
        self.calls.append('activate')
    def finish(self, grant): self.calls.append('finish')
    async def close(self): self.calls.append('close')


class SteeringControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.leases = Leases(Room('TEST', 'Test'), clock=self.clock)
        self.native = SteeringNative()
        self.agent = ConversationAgent(self.leases, EventLog(), settings_for(self.native))
        self.guest = self.leases.create()
        self.tasks = []

    async def asyncTearDown(self):
        self.native.steer_release.set()
        for task in self.tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.agent.close()

    async def original(self):
        task = asyncio.create_task(self.agent.turn(self.guest.guest_id, 'Play music'))
        self.tasks.append(task)
        await asyncio.wait_for(self.native.started.wait(), .2)
        return task

    async def followup(self, text='Add the lights', guest=None):
        return await asyncio.wait_for(self.agent.turn((guest or self.guest).guest_id, text), .2)

    async def finish(self, original):
        await self.native.finish('native-1', 'One original final reply')
        return await asyncio.wait_for(original, .2)

    async def test_followup_reaches_same_native_turn_without_waiting_for_controller_lock(self):
        original = await self.original()
        result = await self.followup()
        self.assertEqual(result, [{'type': 'action', 'text': 'Added to current request'}])
        self.assertNotIsInstance(result, ReplyFrames)
        self.assertFalse(original.done())
        self.assertEqual(self.native.steers, [('Add the lights', 'native-1')])
        self.assertEqual(self.native.counter, 1)
        self.assertFalse(any(call[0] == 'interrupt' for call in self.native.calls))
        final = await self.finish(original)
        self.assertIsInstance(final, ReplyFrames)
        self.assertEqual(final, [{'type': 'assistant', 'text': 'One original final reply'}])

    async def test_helper_grant_is_retained_until_original_final_without_repreparation(self):
        grants = self.agent.device_tools = DeviceGrants()
        original = await self.original()
        await self.followup()
        self.assertEqual(grants.calls.count('prepare'), 1)
        self.assertEqual(grants.calls.count('activate'), 1)
        self.assertNotIn('finish', grants.calls)
        await self.finish(original)
        self.assertEqual(grants.calls.count('finish'), 1)

    async def test_unknown_followup_latches_without_failing_or_interrupting_original(self):
        original = await self.original()
        self.native.steer_error = RoomSessionError('private failed acknowledgement', outcome_unknown=True)
        result = await self.followup()
        self.assertEqual(result, [{'type': 'action', 'text':
            'Tenant could not confirm that follow-up was added. It was not retried.'}])
        later = await self.followup('Do not retry')
        self.assertEqual(later, [{'type': 'action', 'text':
            'A previous follow-up could not be confirmed. Wait for the current request to finish.'}])
        self.assertEqual(len(self.native.steers), 1)
        self.assertFalse(self.agent._failed)
        self.assertEqual(self.native.counter, 1)
        self.assertFalse(any(call[0] == 'interrupt' for call in self.native.calls))
        self.assertEqual((await self.finish(original))[-1]['text'], 'One original final reply')

    async def test_known_rejected_followup_is_action_only_and_never_new_submission(self):
        original = await self.original()
        self.native.steer_error = RoomSessionError('native rejected followup')
        result = await self.followup()
        self.assertEqual(result, [{'type': 'action', 'text':
            'That follow-up was not accepted. Nothing was retried.'}])
        self.assertEqual(self.native.counter, 1)
        self.assertFalse(self.agent._failed)
        self.assertFalse(any(call[0] == 'interrupt' for call in self.native.calls))
        await self.finish(original)

    async def test_mismatched_fake_session_ack_does_not_create_completed_reply(self):
        original = await self.original()
        self.native.steer_ack = 'another-turn'
        result = await self.followup()
        self.assertEqual(result[0]['type'], 'action')
        self.assertNotEqual(result[0]['text'], 'Added to current request')
        await self.followup('Do not replay')
        self.assertEqual(len(self.native.steers), 1)
        self.assertEqual(self.native.counter, 1)
        await self.finish(original)

    async def test_revoked_guest_followup_never_steers_existing_turn(self):
        original = await self.original()
        self.leases.revoke(self.guest.guest_id)
        result = await self.followup()
        self.assertIn('no longer', result[-1]['text'])
        self.assertFalse(self.native.steers)
        await asyncio.wait_for(original, .3)

    async def test_expired_guest_followup_never_steers_existing_turn(self):
        original = await self.original()
        self.clock.now = self.guest.expires_at
        result = await self.followup()
        self.assertIn('no longer', result[-1]['text'])
        self.assertFalse(self.native.steers)
        await asyncio.wait_for(original, .3)

    async def test_authority_lost_while_steer_ack_pending_never_claims_acceptance(self):
        original = await self.original()
        self.native.before_ack = lambda: self.leases.revoke(self.guest.guest_id)
        result = await self.followup()
        self.assertNotEqual(result, [{'type': 'action', 'text': 'Added to current request'}])
        self.assertEqual(len(self.native.steers), 1)
        self.assertEqual(self.native.counter, 1)
        await asyncio.wait_for(original, .3)

    async def test_replaced_lease_object_cannot_authorize_pending_followup(self):
        original = await self.original()
        replacement = copy.copy(self.guest)
        self.native.before_ack = lambda: self.leases.leases.__setitem__(self.guest.guest_id, replacement)
        result = await self.followup()
        self.assertNotEqual(result, [{'type': 'action', 'text': 'Added to current request'}])
        self.assertEqual(len(self.native.steers), 1)
        self.assertEqual(self.native.counter, 1)
        await self.finish(original)

    async def test_changed_generation_cannot_authorize_pending_followup(self):
        original = await self.original()
        self.native.before_ack = lambda: setattr(self.agent, '_generation', self.agent._generation + 1)
        result = await self.followup()
        self.assertNotEqual(result, [{'type': 'action', 'text': 'Added to current request'}])
        self.assertEqual(len(self.native.steers), 1)
        self.assertEqual(self.native.counter, 1)
        await asyncio.wait_for(original, .3)

    async def test_completed_turn_before_steering_choice_uses_next_normal_turn(self):
        original = await self.original()
        self.native.auto_finish = True
        await self.native.finish('native-1', 'One original final reply')
        result = await self.followup('A new completed-turn request')
        self.assertEqual((await original)[-1]['text'], 'One original final reply')
        self.assertEqual(result[-1]['text'], 'Native reply: A new completed-turn request')
        self.assertEqual(self.native.counter, 2)
        self.assertFalse(self.native.steers)

    async def test_new_guest_starts_after_handoff_and_never_steers_previous_guest(self):
        original = await self.original()
        new_guest = self.leases.create()
        second = asyncio.create_task(self.agent.turn(new_guest.guest_id, 'A different guest request'))
        self.tasks.append(second)
        await asyncio.wait_for(original, .3)
        for _ in range(100):
            if self.native.counter == 2:
                break
            await asyncio.sleep(.001)
        self.assertEqual(self.native.counter, 2)
        self.assertFalse(self.native.steers)
        await self.native.finish('native-2', 'New guest final')
        self.assertEqual((await asyncio.wait_for(second, .2))[-1]['text'], 'New guest final')


if __name__ == '__main__':
    unittest.main()
