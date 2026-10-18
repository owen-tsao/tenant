"""Reply-voice helper/CLI integration; synthetic policy and sockets, no sound."""
import asyncio
import copy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.tenant_device import invoke, main
from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.native_devices import NativeDevices
from brain.core.registry import Registry
from brain.state import Room


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        return self.now


class DeviceSocket:
    def __init__(self, bus):
        self.bus, self.frames = bus, []

    async def send_json(self, frame):
        self.frames.append(frame)
        result = {'spoken': True} if frame['cap'] == 'say' else frame['args']
        self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': result})


class Policy:
    """Synchronous interface double; real speaker/lease selection has own tests."""
    def __init__(self):
        self.enabled, self.selected = False, None
        self.speaker_ref = 'actual-connection-1'
        self.calls, self.offered = [], set()
        self.before_set = None

    def inventory(self, _grant):
        return {'enabled': self.enabled, 'selected_device_id': self.selected,
                'speakers': [{'device_id': 'speaker', 'label': 'Room speaker',
                              'speaker_ref': self.speaker_ref}]}

    def context(self, grant):
        key = grant.guest_id, self.speaker_ref
        offer = key not in self.offered
        self.offered.add(key)
        return {'enabled': self.enabled, 'selected_device_id': self.selected,
                'offer_speaker_choice': offer}

    def set_voice(self, grant, payload, *, authorized):
        if self.before_set is not None:
            self.before_set()
        if not authorized():
            return {'ok': False, 'code': 'PERMISSION', 'message': 'Voice permission changed.'}
        self.calls.append(copy.deepcopy(payload))
        if payload['enabled'] and (payload['device_id'] != 'speaker'
                                   or payload['speaker_ref'] != self.speaker_ref):
            return {'ok': False, 'code': 'STALE', 'message': 'Choose the current speaker connection.'}
        self.enabled = payload['enabled']
        self.selected = payload.get('device_id') if self.enabled else None
        return {'ok': True, 'result': self.inventory(grant), 'message': 'Reply voice preference updated.'}


class ReplyVoiceHelperTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry(Room('TEST', 'Synthetic room'))
        self.bus, self.clock = Bus(self.registry), Clock()
        self.leases = Leases(self.registry.room, clock=self.clock)
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        self.active = True
        self.tools = NativeDevices(self.registry, self.bus, self.leases, EventLog(),
                                   lambda _grant: self.active, action_timeout=.1)
        self.grant = await self.tools.prepare(self.lease.guest_id, 1, self.lease, 'native-thread')
        self.tools.activate(self.grant, 'native-turn')
        self.phone = self.device('phone', {'light': {'description': 'Light',
                                  'args': {'on': {'type': 'boolean'}}}})
        self.policy = Policy()
        self.tools.reply_voice = self.policy
        self.speaker = self.device('speaker', {
            'say': {'description': 'Speech', 'args': {'text': {'type': 'string', 'maxLength': 160}}}})

    async def asyncTearDown(self):
        await self.tools.close()

    def device(self, device_id, caps):
        socket = DeviceSocket(self.bus)
        socket.device = self.registry.register({'type': 'hello', 'id': device_id, 'label': device_id,
                                               'room': 'TEST', 'caps': caps}, socket)
        return socket

    def voice(self, **changes):
        return {'token': self.grant.token, 'operation': 'reply-voice', 'request_id': 'voice-on',
                'enabled': True, 'device_id': 'speaker', 'speaker_ref': self.policy.speaker_ref, **changes}

    def assert_no_bus(self):
        self.assertEqual(self.phone.frames + self.speaker.frames, [])

    async def test_inventory_and_offer_context_are_text_default_without_bus_or_activation(self):
        for _ in range(2):
            inventory = await self.tools.dispatch({'token': self.grant.token, 'operation': 'inventory'})
            self.assertFalse(inventory['reply_voice']['enabled'])
        self.assertEqual(self.policy.offered, set(), 'Inventory consumed the once-only context offer.')
        first = self.tools.context(self.grant)
        second = self.tools.context(self.grant)
        self.assertIn('"offer_speaker_choice":true', first)
        self.assertIn('"offer_speaker_choice":false', second)
        self.policy.speaker_ref = 'actual-connection-2'
        self.assertIn('"offer_speaker_choice":true', self.tools.context(self.grant))
        self.assertIn('Text is default', first)
        self.assertIn('One-off say never enables it', first)
        self.assertNotIn('voiced automatically', first)
        self.assertEqual(self.policy.calls, [])
        self.assertFalse(self.policy.enabled)
        self.assertFalse(self.grant.explicit_speech_attempted)
        self.assert_no_bus()

    async def test_full_program_and_voice_guide_remains_inside_native_context_budget(self):
        self.tools.programs = SimpleNamespace()
        self.policy.enabled, self.policy.selected = True, 's' * 80
        context = self.tools.context(self.grant)
        self.assertLessEqual(len(context), 4000)
        self.assertIn('program-start', context)
        self.assertIn('reply-voice', context)
        self.assertNotIn(self.grant.token, context)
        snapshot = json.JSONDecoder().raw_decode(context.split('Reply voice context: ', 1)[1])[0]
        self.assertEqual(set(snapshot), {'enabled', 'selected_device_id', 'offer_speaker_choice'})

    async def test_enable_disable_share_the_existing_ledger_and_do_not_dispatch(self):
        first = await self.tools.dispatch(self.voice())
        self.assertTrue(first['ok'], first)
        self.assertTrue(first['result']['enabled'])
        first['result']['enabled'] = False
        duplicate = await self.tools.dispatch(self.voice())
        self.assertTrue(duplicate['result']['enabled'], 'Caller mutation altered the cached receipt.')
        self.assertEqual(len(self.policy.calls), 1)
        changed = await self.tools.dispatch(self.voice(enabled=False))
        self.assertEqual(changed['code'], 'INVALID')
        changed_ref = await self.tools.dispatch(self.voice(speaker_ref='changed-connection'))
        self.assertEqual(changed_ref['code'], 'INVALID')
        changed_mode = await self.tools.dispatch({'token': self.grant.token, 'operation': 'reply-voice',
                                                 'request_id': 'voice-on', 'enabled': False})
        self.assertEqual(changed_mode['code'], 'INVALID')
        self.assertEqual(len(self.policy.calls), 1)
        disabled = await self.tools.dispatch({'token': self.grant.token, 'operation': 'reply-voice',
                                             'request_id': 'voice-off', 'enabled': False})
        self.assertTrue(disabled['ok'])
        self.assertFalse(disabled['result']['enabled'])
        self.assertEqual(self.policy.calls[-1], {'request_id': 'voice-off', 'enabled': False})
        self.assertEqual(self.grant.unknown_devices, set())
        self.assert_no_bus()

    async def test_exact_boolean_enable_and_disable_schemas_reject_invalid_before_policy(self):
        invalid = [
            {'request_id': 'bad', 'enabled': value} for value in (0, 1, None, 'true', [], {})
        ] + [
            {'request_id': 'bad', 'enabled': True},
            {'request_id': 'bad', 'enabled': True, 'device_id': 'speaker'},
            {'request_id': 'bad', 'enabled': 1, 'device_id': 'speaker', 'speaker_ref': 'ref'},
            {'request_id': 'bad', 'enabled': False, 'device_id': 'speaker'},
            {'request_id': 'bad', 'enabled': False, 'speaker_ref': 'extra'},
            {'request_id': 'bad', 'enabled': True, 'device_id': 1, 'speaker_ref': 'ref'},
            {'request_id': 'bad', 'enabled': True, 'device_id': 'speaker', 'speaker_ref': None},
            {'request_id': None, 'enabled': False},
            {'request_id': 'bad id', 'enabled': False},
            {'request_id': 'x' * 81, 'enabled': False},
            {'enabled': False},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = await self.tools.dispatch({'token': self.grant.token,
                                                      'operation': 'reply-voice', **payload})
                self.assertEqual(response['code'], 'INVALID')
        self.assertEqual(self.policy.calls, [])
        self.assertEqual(self.grant.calls, {})
        self.assert_no_bus()

    async def test_stale_context_and_permission_changes_while_ledger_queued_cannot_set_voice(self):
        for transition in ('expire', 'revoke', 'finish', 'controller', 'disconnect', 'reset'):
            with self.subTest(transition=transition):
                lease = self.leases.create()
                self.leases.current(lease.guest_id, activate=True)
                grant = await self.tools.prepare(lease.guest_id, 1, lease, 'native-thread')
                self.tools.activate(grant, 'native-turn')
                connected = True
                self.active = True
                await grant.lock.acquire()
                task = asyncio.create_task(self.tools.dispatch(self.voice(token=grant.token),
                                                               connected=lambda: connected))
                await asyncio.sleep(0)
                if transition == 'expire':
                    self.clock.now = lease.expires_at
                elif transition == 'revoke':
                    self.leases.revoke(lease.guest_id)
                elif transition == 'finish':
                    self.tools.finish(grant)
                elif transition == 'controller':
                    self.active = False
                elif transition == 'disconnect':
                    connected = False
                else:
                    self.leases.reset()
                grant.lock.release()
                self.assertEqual((await task)['code'], 'PERMISSION')
                self.tools.finish(grant)
        self.active = True
        self.assertEqual(self.policy.calls, [])
        self.assert_no_bus()

    async def test_policy_receives_live_authorization_callback_and_exact_stale_speaker_ref(self):
        stale = await self.tools.dispatch(self.voice(speaker_ref='old-speaker-connection'))
        self.assertFalse(stale['ok'])
        self.assertEqual(stale['code'], 'STALE')
        self.assertEqual(self.policy.calls[-1]['speaker_ref'], 'old-speaker-connection')
        self.assertFalse(self.policy.enabled)
        self.policy.before_set = lambda: self.tools.finish(self.grant)
        denied = await self.tools.dispatch(self.voice(request_id='voice-after-finish'))
        self.assertEqual(denied['code'], 'PERMISSION')
        self.assertEqual(len(self.policy.calls), 1)
        self.assert_no_bus()

    async def test_one_off_say_does_not_enable_future_reply_voice(self):
        response = await self.tools.dispatch({'token': self.grant.token, 'operation': 'call',
            'request_id': 'one-off-say', 'device_id': 'speaker', 'cap': 'say', 'args': {'text': 'Hello.'}})
        self.assertTrue(response['ok'], response)
        self.assertTrue(self.grant.explicit_speech_attempted)
        self.assertEqual(len(self.speaker.frames), 1)
        self.assertEqual(self.policy.calls, [])
        self.assertFalse(self.policy.enabled)

    async def test_real_private_cli_socket_updates_preference_once_without_bus(self):
        payload = {key: value for key, value in self.voice().items() if key not in ('token', 'operation')}
        first = await asyncio.to_thread(invoke, self.grant.path, 'reply-voice', payload)
        duplicate = await asyncio.to_thread(invoke, self.grant.path, 'reply-voice', payload)
        self.assertEqual(first, duplicate)
        self.assertTrue(first['ok'])
        self.assertEqual(len(self.policy.calls), 1)
        self.assert_no_bus()

    async def test_policy_exception_is_cached_without_marking_a_physical_device_uncertain(self):
        with patch.object(self.policy, 'set_voice', side_effect=RuntimeError('Synthetic policy error')) as mutation:
            first = await self.tools.dispatch(self.voice())
            duplicate = await self.tools.dispatch(self.voice())
        self.assertEqual(first['code'], 'UNKNOWN')
        self.assertEqual(first, duplicate)
        mutation.assert_called_once()
        self.assertEqual(self.grant.unknown_devices, set())
        self.assert_no_bus()

    async def test_unwired_policy_rejects_preference_operation_without_changing_existing_inventory(self):
        self.tools.reply_voice = None
        response = await self.tools.dispatch(self.voice())
        self.assertEqual(response['code'], 'INVALID')
        inventory = await self.tools.dispatch({'token': self.grant.token, 'operation': 'inventory'})
        self.assertNotIn('reply_voice', inventory)
        self.assert_no_bus()


class ReplyVoiceCliTests(unittest.TestCase):
    def run_cli(self, payload):
        with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO) as output:
            status = main(['--context', '/private/synthetic-context', 'reply-voice'])
        return status, json.loads(output.getvalue())

    def test_cli_accepts_exact_typed_enable_and_disable_payloads(self):
        for payload in ({'request_id': 'voice-off', 'enabled': False},
                        {'request_id': 'voice-on', 'enabled': True, 'device_id': 'speaker', 'speaker_ref': 'connection'}):
            with self.subTest(payload=payload), patch('agent.tenant_device.invoke', return_value={'ok': True}) as call:
                status, response = self.run_cli(payload)
                self.assertEqual(status, 0)
                self.assertTrue(response['ok'])
                self.assertEqual(call.call_args.args[1:], ('reply-voice', payload))

    def test_cli_rejects_numeric_bool_extra_fields_and_missing_speaker_reference(self):
        for payload in ({'request_id': 'off', 'enabled': value} for value in (0, 1, None, 'false')):
            with self.subTest(payload=payload), patch('agent.tenant_device.invoke') as call:
                self.assertEqual(self.run_cli(payload)[0], 1)
                call.assert_not_called()
        for payload in ({'request_id': 'on', 'enabled': True, 'device_id': 'speaker'},
                        {'request_id': 'on', 'enabled': 1, 'device_id': 'speaker', 'speaker_ref': 'ref'},
                        {'request_id': 'off', 'enabled': False, 'device_id': 'speaker'},
                        {'request_id': 1, 'enabled': False},
                        {'request_id': 'on', 'enabled': True, 'device_id': 'speaker', 'speaker_ref': 1}):
            with self.subTest(payload=payload), patch('agent.tenant_device.invoke') as call:
                self.assertEqual(self.run_cli(payload)[0], 1)
                call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
