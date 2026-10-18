"""Local helper/controller/Bus checks with fake devices; no native models or OS effects."""
import asyncio
from contextlib import suppress
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.tenant_device import invoke, main
from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.native_devices import NativeDevices
from brain.core.registry import Registry
from brain.core.room_conversation import ConversationAgent
from brain.config import Config
from brain.main import create_app
from brain.state import Room
from test_room_conversation import Clock, NativeSession, settings_for


class DeviceSocket:
    def __init__(self, bus, auto=True):
        self.bus, self.auto = bus, auto
        self.frames, self.sent = [], asyncio.Event()
    async def send_json(self, frame):
        self.frames.append(frame)
        self.sent.set()
        if self.auto:
            result = ({'state': 'playing'} if frame['cap'] == 'music.play' else
                      {'state': 'paused'} if frame['cap'] == 'music.pause' else
                      {'spoken': True} if frame['cap'] == 'say' else frame['args'])
            self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': result})


def device(registry, bus, device_id='phone', *, auto=True, caps=None):
    socket = DeviceSocket(bus, auto)
    socket.device = registry.register({'type': 'hello', 'id': device_id, 'label': 'Room ' + device_id,
        'room': registry.room.code, 'caps': caps or {'light': {'args': {'on': {'type': 'boolean'}}, 'description': 'Flashlight'}}}, socket)
    return socket


class NativeDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry(Room('TEST', 'Test'))
        self.bus, self.clock = Bus(self.registry), Clock()
        self.leases = Leases(self.registry.room, clock=self.clock)
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        self.log, self.active = EventLog(), True
        self.tools = NativeDevices(self.registry, self.bus, self.leases, self.log,
                                   lambda _grant: self.active, action_timeout=.03, read_timeout=.02)
        self.phone = device(self.registry, self.bus)
        self.grant = await self.tools.prepare(self.lease.guest_id, 1, self.lease, 'native-thread')
        self.tools.activate(self.grant, 'native-turn')
    async def asyncTearDown(self):
        await self.tools.close()
    def inventory(self): return {'token': self.grant.token, 'operation': 'inventory'}
    def call(self, **changes):
        return {'token': self.grant.token, 'operation': 'call', 'request_id': 'call-1',
                'device_id': 'phone', 'cap': 'light', 'args': {'on': True}, **changes}

    async def test_private_permissions_inactive_grant_and_read_only_actual_inventory(self):
        self.assertEqual(self.grant.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.grant.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.grant.path.parent / 'bus.sock').stat().st_mode & 0o777, 0o600)
        self.grant.turn_id = None
        self.assertEqual((await self.tools.dispatch(self.inventory()))['code'], 'PERMISSION')
        self.tools.activate(self.grant, 'native-turn')
        self.phone.device.online = False
        result = await asyncio.to_thread(invoke, self.grant.path, 'inventory')
        row = result['devices'][0]
        self.assertEqual(row['id'], 'phone')
        self.assertFalse(row['online'])
        self.assertFalse(row['executable'])
        self.assertEqual(row['caps'][0]['args'], {'on': {'type': 'boolean'}})
        self.assertEqual(self.phone.frames, [])

    async def test_real_helper_socket_reaches_bus_and_reports_correlated_ack_once(self):
        payload = {key: value for key, value in self.call().items() if key not in ('token', 'operation')}
        result = await asyncio.to_thread(invoke, self.grant.path, 'call', payload)
        self.assertTrue(result['ok'])
        self.assertEqual(result['result'], {'on': True})
        self.assertEqual(result['message'], 'Room phone turned its flashlight on.')
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(self.log.audit_rows[-1]['audit']['req'], self.phone.frames[0]['req'])
        self.assertEqual(self.log.audit_rows[-1]['audit']['turn_id'], 'native-turn')
        self.assertNotIn(self.grant.token, repr(self.log.audit_rows))
        self.assertNotIn(str(self.grant.path), repr(self.log.rows))

    async def test_duplicate_does_not_replay_but_a_new_requested_action_is_allowed(self):
        self.phone.auto = False
        first = asyncio.create_task(self.tools.dispatch(self.call()))
        await self.phone.sent.wait()
        duplicate = asyncio.create_task(self.tools.dispatch(self.call()))
        self.assertEqual((await self.tools.dispatch(self.call(args={'on': 1})))['code'], 'INVALID')
        self.assertEqual((await self.tools.dispatch(self.call(args={'on': False})))['code'], 'INVALID')
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {'on': True}})
        self.assertEqual(await first, await duplicate)
        self.assertEqual((await self.tools.dispatch(self.call(args={'on': False})))['code'], 'INVALID')
        self.phone.auto = True
        self.assertTrue((await self.tools.dispatch(self.call(request_id='call-2', args={'on': False})))['ok'])
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True, False])

    async def test_independent_device_calls_can_be_inflight_concurrently(self):
        self.phone.auto = False
        second = device(self.registry, self.bus, 'laptop', caps={
            'music.play': {'args': {}, 'description': 'Start music'}})
        first_task = asyncio.create_task(self.tools.dispatch(self.call()))
        second_task = asyncio.create_task(self.tools.dispatch(self.call(request_id='second-call', device_id='laptop',
                                                                       cap='music.play', args={})))
        async with asyncio.timeout(.2):
            await asyncio.gather(self.phone.sent.wait(), second.sent.wait())
        self.assertTrue((await second_task)['ok'])
        self.assertFalse(first_task.done())  # Phone ACK is held while Mac succeeds.
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {'on': True}})
        self.assertTrue((await first_task)['ok'])
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(len(second.frames), 1)

    async def test_unknown_is_cached_and_never_retried_or_substituted(self):
        self.phone.auto = False
        backup = device(self.registry, self.bus, 'backup')
        first = await self.tools.dispatch(self.call())
        self.assertEqual(first['code'], 'UNKNOWN')
        self.assertEqual(await self.tools.dispatch(self.call()), first)
        # A fresh ID cannot resend an unresolved device action, even after a late ACK.
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {'on': True}})
        other = await self.tools.dispatch(self.call(request_id='new'))
        self.assertEqual(other['code'], 'UNKNOWN')
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(backup.frames, [])
        # UNKNOWN does not revoke independent explicit work on another device.
        self.assertTrue((await self.tools.dispatch(self.call(request_id='independent', device_id='backup')))['ok'])
        self.assertEqual(len(backup.frames), 1)

    async def test_all_live_authority_changes_while_bus_queued_send_nothing(self):
        for change in ('expiry', 'revoke', 'scope', 'native_completion', 'new_controller', 'reset'):
            with self.subTest(change=change):
                lease = self.leases.create()
                self.leases.current(lease.guest_id, activate=True)
                grant = await self.tools.prepare(lease.guest_id, 1, lease, 'native-thread')
                self.tools.activate(grant, 'native-turn')
                self.active = True
                lock = self.bus.locks['phone']
                await lock.acquire()
                pending = asyncio.create_task(self.tools.dispatch(self.call(token=grant.token)))
                await asyncio.sleep(0)
                if change == 'expiry': self.clock.now = lease.expires_at
                elif change == 'revoke': self.leases.revoke(lease.guest_id)
                elif change == 'scope': lease.scopes.clear()
                elif change in ('native_completion', 'new_controller'): self.active = False
                else: self.leases.reset()
                lock.release()
                self.assertEqual((await pending)['code'], 'PERMISSION')
                self.assertEqual(self.phone.frames, [])
                self.tools.finish(grant)

    async def test_inflight_ack_after_revocation_remains_truthful_without_restoring_authority(self):
        self.phone.auto = False
        pending = asyncio.create_task(self.tools.dispatch(self.call()))
        await self.phone.sent.wait()
        self.leases.revoke(self.lease.guest_id)
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {'on': True}})
        self.assertTrue((await pending)['ok'])
        self.assertEqual((await self.tools.dispatch(self.call()))['code'], 'PERMISSION')
        self.assertEqual(len(self.phone.frames), 1)

    async def test_invalid_or_offline_requested_device_never_uses_a_backup(self):
        backup = device(self.registry, self.bus, 'backup')
        result = await self.tools.dispatch(self.call(device_id='missing'))
        self.assertEqual(result['code'], 'OFFLINE')
        self.assertEqual(self.phone.frames + backup.frames, [])
        # An explicitly requested new target is allowed; the helper never chooses it.
        self.assertTrue((await self.tools.dispatch(self.call(device_id='backup', request_id='new')))['ok'])
        self.assertEqual(len(backup.frames), 1)

    async def test_copied_stale_context_and_connected_clients_cannot_restore_authority(self):
        saved = copy.deepcopy(json.loads(self.grant.path.read_text()))
        reader, writer = await asyncio.open_unix_connection(saved['socket'])
        self.tools.finish(self.grant)
        self.assertFalse(self.grant.path.exists())
        writer.write(json.dumps({'token': saved['token'], 'operation': 'inventory'}).encode() + b'\n')
        await writer.drain()
        self.assertEqual(json.loads(await reader.readline())['code'], 'PERMISSION')
        writer.close()
        await writer.wait_closed()
        self.assertEqual((await self.tools.dispatch(self.call()))['code'], 'PERMISSION')
        self.assertEqual(self.phone.frames, [])

    async def test_partial_socket_read_and_resource_teardown_are_bounded(self):
        directory = self.grant.path.parent
        reader, writer = await asyncio.open_unix_connection(directory / 'bus.sock')
        writer.write(b'{"token":')
        await writer.drain()
        async with asyncio.timeout(.2):
            self.assertEqual(await reader.read(), b'')
            await self.tools.close()
        self.assertFalse(directory.exists())
        self.assertEqual(self.tools._clients, set())
        writer.close()
        await writer.wait_closed()

    async def test_close_settles_open_client_bus_wait_before_server_wait_closed(self):
        self.tools.action_timeout = 30
        self.phone.auto = False
        directory = self.grant.path.parent
        reader, writer = await asyncio.open_unix_connection(directory / 'bus.sock')
        writer.write(json.dumps(self.call()).encode() + b'\n')
        await writer.drain()
        await self.phone.sent.wait()
        async with asyncio.timeout(.5):
            await self.tools.close()
        self.assertFalse(directory.exists())
        self.assertEqual(self.tools._clients, set())
        self.assertEqual(self.bus.pending, {})
        self.assertTrue(self.bus.uncertain)  # Sent effects are not claimed undone.
        terminal = self.grant.calls['call-1'][1]
        self.assertTrue(terminal.done())
        self.assertEqual(terminal.result()['code'], 'UNKNOWN')  # Receipt survives resource teardown.
        reply = await reader.readline()
        # Shutdown may close before a response; the CLI maps that EOF to UNKNOWN.
        self.assertTrue(not reply or json.loads(reply)['code'] == 'UNKNOWN')
        writer.close()
        await writer.wait_closed()

    async def test_exact_guest_text_and_secrets_stay_out_of_context_command_and_logs(self):
        wrapped = self.tools.context(self.grant)
        self.assertNotIn(self.grant.token, wrapped)
        self.assertNotIn('host-private', wrapped)
        self.assertNotIn('device-private', wrapped)
        self.assertIn('--context', wrapped)
        self.assertEqual(self.tools.redact(self.grant.token + ' ' + str(self.grant.path)),
                         '[private turn grant] [private helper]')

    async def test_cli_treats_speech_and_shell_syntax_as_json_data_and_never_prints_secrets(self):
        phrase = 'hello $(touch should-never-exist); `echo unsafe`'
        socket = device(self.registry, self.bus, 'speaker', caps={
            'say': {'args': {'text': {'type': 'string', 'maxLength': 500}}, 'description': 'Speak'}})
        payload = {'request_id': 'speech-1', 'device_id': 'speaker', 'cap': 'say', 'args': {'text': phrase}}
        result = await asyncio.to_thread(invoke, self.grant.path, 'call', payload)
        self.assertTrue(result['ok'])
        self.assertEqual(socket.frames[0]['args']['text'], phrase)
        with patch('sys.stdin', io.StringIO('{}')), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['--context', str(self.grant.path), 'call']), 1)
            self.assertNotIn(self.grant.token, output.getvalue())


class NativeDeviceConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry(Room('TEST', 'Test'))
        self.bus, self.leases, self.native = Bus(self.registry), Leases(self.registry.room), NativeSession()
        self.agent = ConversationAgent(self.leases, EventLog(), settings_for(self.native),
                                       registry=self.registry, bus=self.bus,
                                       private_values=('host-private', 'device-private'))
        self.phone = device(self.registry, self.bus)
        self.lease = self.leases.create()
        self.native.auto_finish = False
    async def asyncTearDown(self):
        await self.agent.close()
    async def start(self, text='Turn on Room phone.'):
        task = asyncio.create_task(self.agent.turn(self.lease.guest_id, text))
        await self.native.started.wait()
        grant = next(iter(self.agent.device_tools._grants.values()))
        return task, grant

    async def test_native_turn_helper_result_is_delivered_then_grant_is_removed(self):
        original = '  Turn on Room phone.\nPreserve my exact words.  '
        task, grant = await self.start(original)
        self.assertEqual(self.native.history[-1]['text'], original)
        self.assertIn('--context', self.native.application_contexts[-1])
        self.assertNotIn(grant.token, self.native.application_contexts[-1])
        result = await asyncio.to_thread(invoke, grant.path, 'call',
            {'request_id': 'native-call', 'device_id': 'phone', 'cap': 'light', 'args': {'on': True}})
        self.assertTrue(result['ok'])
        await self.native.finish('native-1', result['message'])
        self.assertEqual((await task)[-1]['text'], 'Room phone turned its flashlight on.')
        self.assertFalse(grant.path.exists())
        self.assertTrue(grant.closed)
        self.assertEqual(len(self.phone.frames), 1)

    async def test_one_native_request_can_control_phone_and_laptop_audio(self):
        speaker = device(self.registry, self.bus, 'laptop', caps={
            'music.play': {'args': {}, 'description': 'Start music'}})
        task, grant = await self.start('Start laptop music and turn on Room phone.')
        common = {'token': grant.token, 'operation': 'call'}
        results = await asyncio.gather(
            self.agent.device_tools.dispatch({**common, 'request_id': 'phone-on', 'device_id': 'phone',
                                               'cap': 'light', 'args': {'on': True}}),
            self.agent.device_tools.dispatch({**common, 'request_id': 'music-start', 'device_id': 'laptop',
                                               'cap': 'music.play', 'args': {}}))
        self.assertTrue(all(result['ok'] for result in results))
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(len(speaker.frames), 1)
        await self.native.finish('native-1', 'Music started and the phone light is on.')
        self.assertEqual((await task)[-1]['text'], 'Music started and the phone light is on.')

    async def test_helper_cannot_act_before_successful_start_ack_or_after_native_completion(self):
        original_start = self.native.start_turn
        pre_start = []
        async def start_with_racing_helper(text, **kwargs):
            turn = await original_start(text, **kwargs)
            grant = next(iter(self.agent.device_tools._grants.values()))
            pre_start.append(await self.agent.device_tools.dispatch({'token': grant.token, 'operation': 'call',
                'request_id': 'early', 'device_id': 'phone', 'cap': 'light', 'args': {'on': True}}))
            return turn
        self.native.start_turn = start_with_racing_helper
        task, grant = await self.start()
        self.assertEqual(pre_start[0]['code'], 'PERMISSION')
        await self.native.finish('native-1', 'No device was used.')
        # The receiver observes completion before final response delivery.
        response = await self.agent.device_tools.dispatch({'token': grant.token, 'operation': 'inventory'})
        self.assertEqual(response['code'], 'PERMISSION')
        await task
        self.assertEqual(self.phone.frames, [])

    async def test_handoff_unlinks_old_capability_before_waiting_for_controller_lock(self):
        task, grant = await self.start()
        second = self.leases.create()
        other = asyncio.create_task(self.agent.turn(second.guest_id, 'New guest asks a question.'))
        await asyncio.sleep(0)
        self.assertFalse(grant.path.exists())
        self.assertEqual((await self.agent.device_tools.dispatch({'token': grant.token, 'operation': 'inventory'}))['code'], 'PERMISSION')
        await task
        for _ in range(100):
            if self.native.counter == 2: break
            await asyncio.sleep(.001)
        await self.native.finish('native-2', 'A new guest conversation.')
        await other
        self.assertEqual(self.phone.frames, [])

    async def test_actual_new_controller_admission_denies_an_old_bus_queued_helper(self):
        task, grant = await self.start()
        lock = self.bus.locks['phone']
        await lock.acquire()
        queued = asyncio.create_task(self.agent.device_tools.dispatch({'token': grant.token, 'operation': 'call',
            'request_id': 'old-queued', 'device_id': 'phone', 'cap': 'light', 'args': {'on': True}}))
        await asyncio.sleep(0)
        self.assertTrue(grant.calls)
        second = self.leases.create()
        other = asyncio.create_task(self.agent.turn(second.guest_id, 'A new guest.'))
        await asyncio.sleep(0)
        lock.release()
        self.assertEqual((await queued)['code'], 'PERMISSION')
        await task
        for _ in range(100):
            if self.native.counter == 2: break
            await asyncio.sleep(.001)
        await self.native.finish('native-2', 'New guest response.')
        await other
        self.assertEqual(self.phone.frames, [])

    async def test_native_close_error_still_removes_helper_resources(self):
        self.native.auto_finish = True
        await self.agent.turn(self.lease.guest_id, 'A question.')
        directory = Path(self.agent.device_tools._directory.name)
        async def failed_close():
            raise RuntimeError('connection close failed')
        original = self.native.close
        self.native.close = failed_close
        with self.assertRaises(RuntimeError):
            await self.agent.close()
        self.assertFalse(directory.exists())
        self.native.close = original

    async def test_failed_start_unlinks_grant_and_never_falls_back(self):
        self.native.fail_start = True
        result = await self.agent.turn(self.lease.guest_id, 'Turn on Room phone.')
        self.assertIn('nothing was retried', result[-1]['text'])
        self.assertEqual(self.agent.device_tools._grants, {})
        self.assertEqual(list(Path(self.agent.device_tools._directory.name).glob('*.json')), [])
        self.assertEqual(self.phone.frames, [])


class NativeSecretRedactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_photon_literal_is_redacted_from_native_final_only(self):
        synthetic_secret = 'injected-photon-private-test-value'
        native = NativeSession()
        native.auto_finish = False
        with patch.dict('os.environ', {'PHOTON_API_KEY': synthetic_secret}):
            app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                             conversation=settings_for(native))
        core = app.state.core
        self.addAsyncCleanup(core.agent.close)
        lease = core.leases.create()
        task = asyncio.create_task(core.agent.turn(lease.guest_id, 'A harmless question.'))
        await native.started.wait()
        await native.finish('native-1', 'An accidentally echoed value: ' + synthetic_secret)
        frames = await task
        self.assertNotIn(synthetic_secret, str(frames))
        self.assertIn('[private value]', frames[-1]['text'])
        self.assertNotIn(synthetic_secret, repr(core.log.audit_rows))
        self.assertEqual(native.history[-1]['text'], 'A harmless question.')
        self.assertNotIn(synthetic_secret, native.application_contexts[-1])


if __name__ == '__main__': unittest.main()
