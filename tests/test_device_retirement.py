"""Host retirement is metadata recovery, never an acknowledged physical reset."""
import asyncio
from collections import defaultdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from brain.config import Config
from brain.core.persistence import RoomStateStore
from brain.core.room_programs import Program, RoomPrograms
from brain.main import create_app
from test_access_core import hello


HOST = {'Authorization': 'Bearer host-private'}
BODY = {'device_ids': ['phone-a', 'phone-b'], 'reason': 'Obsolete replaced enrollments',
        'physical_off_confirmed': True}


class Socket:
    def __init__(self, bus):
        self.bus, self.frames, self.device = bus, [], None

    async def send_json(self, frame):
        self.frames.append(frame)
        data = {'state': 'paused'} if frame['cap'] == 'music.pause' else frame['args']
        self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': data})


class DeviceRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'room.json'
        self.log = Path(self.temp.name) / 'events.jsonl'
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://testserver'),
                              state_path=self.path, log_path=self.log)
        self.core = self.app.state.core
        self.registry = self.core.registry
        self.registry.enrollments.update({'phone-a': {'OLD1'}, 'phone-b': {'OLD2'}})
        self.assertTrue(self.registry.persist())
        self.phone = self.register('jay-visible-phone-oct17')
        self.audio = self.register('laptop', music=True)
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def register(self, device_id, *, music=False):
        socket = Socket(self.core.bus)
        frame = hello(device_id, room=self.registry.room.code)
        if music:
            frame['caps'] = {'music.pause': {'description': 'Pause prepared music', 'args': {}}}
        socket.device = self.registry.register(frame, socket)
        return socket

    def retire(self, body=None, **kwargs):
        return self.client.post('/host/devices/retire', headers=HOST, json=BODY if body is None else body, **kwargs)

    def assert_old_preserved(self):
        self.assertIn('phone-a', self.registry.enrollments)
        self.assertIn('phone-b', self.registry.enrollments)

    def test_authentication_and_strict_schema_do_not_mutate_or_dispatch(self):
        for headers in ({}, {'Authorization': 'Bearer wrong'}):
            self.assertEqual(self.client.post('/host/devices/retire', headers=headers, json=BODY).status_code, 403)
        invalid = [[], {}, {**BODY, 'reason': ''}, {**BODY, 'reason': 'x' * 201},
                   {**BODY, 'physical_off_confirmed': False}, {**BODY, 'physical_off_confirmed': 1},
                   {**BODY, 'device_ids': []}, {**BODY, 'device_ids': ['phone-a', 'phone-a']},
                   {**BODY, 'device_ids': ['phone-a', {}]}, {**BODY, 'extra': True}]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.retire(body).status_code, 400)
                self.assert_old_preserved()
        self.assertEqual(self.client.post('/host/devices/retire', headers=HOST, content='{').status_code, 400)
        self.assertEqual(self.phone.frames + self.audio.frames, [])

    def test_unknown_or_online_mixed_batch_is_all_or_nothing(self):
        self.assertEqual(self.retire({**BODY, 'device_ids': ['phone-a', 'unknown']}).status_code, 404)
        self.assertEqual(self.retire({**BODY, 'device_ids': ['phone-a', 'laptop']}).status_code, 409)
        self.assertEqual(self.retire({**BODY, 'device_ids': ['phone-a', 'jay-visible-phone-oct17']}).status_code, 409)
        self.assert_old_preserved()
        self.assertTrue(self.phone.device.online)
        self.assertTrue(self.audio.device.online)

    def test_authenticated_reconnection_registers_before_retirement_and_blocks_it(self):
        with self.client.websocket_connect('/ws/device?t=device-private') as bridge:
            bridge.send_json(hello('phone-a', room='OLD1'))
            self.assertEqual(bridge.receive_json()['type'], 'welcome')
            self.assertTrue(self.registry.devices['phone-a'].online)
            self.assertEqual(self.retire().status_code, 409)
            self.assert_old_preserved()

    def test_busy_queued_unknown_and_logical_operation_reject_retirement(self):
        device = SimpleNamespace(id='phone-a')
        for kind in ('pending', 'unknown', 'queue', 'logical', 'offline_busy'):
            with self.subTest(kind=kind):
                release = None
                if kind == 'pending': self.core.bus.pending['old'] = (device, None)
                elif kind == 'unknown': self.core.bus.uncertain['old'] = device
                elif kind in ('queue', 'logical'):
                    if kind == 'queue': locks = self.core.bus.locks
                    else:
                        self.core.agent.device_tools = SimpleNamespace(device_locks=defaultdict(asyncio.Lock))
                        locks = self.core.agent.device_tools.device_locks
                    lock = locks['phone-a']
                    self.client.portal.call(lock.acquire)
                    release = lock.release
                else:
                    self.registry.devices['phone-a'] = SimpleNamespace(id='phone-a', online=False, busy=True)
                try:
                    self.assertEqual(self.retire().status_code, 409)
                    self.assert_old_preserved()
                finally:
                    self.core.bus.pending.clear()
                    self.core.bus.uncertain.clear()
                    self.registry.devices.pop('phone-a', None)
                    if release is not None: self.client.portal.call(release)
        self.assertEqual(self.phone.frames + self.audio.frames, [])

    def test_active_unconfirmed_and_unsettled_program_claims_reject_retirement(self):
        engine = RoomPrograms(self.registry, self.core.bus, self.core.leases, self.core.log, lambda owner: False)
        self.core.agent.programs = engine
        program = Program('old-program', None, self.audio.device, self.audio, 60,
                          state='running', active=True, lights={'phone-a': (SimpleNamespace(id='phone-a'), None)})
        engine.programs[program.id] = program
        self.assertEqual(self.retire().status_code, 409)
        program.active, program.state = False, 'unknown'
        program.cleanup = {'audio': 'confirmed', 'phone-a': 'unknown'}
        self.assertEqual(self.retire().status_code, 409)
        program.state, program.cleanup['phone-a'] = 'stopped', 'confirmed'
        async def pending_cleanup():
            future = asyncio.get_running_loop().create_future()
            program.output_cleanup['old'] = future
        self.client.portal.call(pending_cleanup)
        self.assertEqual(self.retire().status_code, 409)
        self.client.portal.call(program.output_cleanup['old'].set_result, None)
        self.assertEqual(self.retire().status_code, 200)
        self.assertEqual(self.phone.frames + self.audio.frames, [])

    def test_only_old_pair_removed_with_host_observation_audit_and_no_effect_or_cleanup_claim(self):
        obsolete = self.register('phone-a')
        self.registry.offline(obsolete.device)
        self.core.agent.private_values = ('photon-private',)
        response = self.retire({**BODY, 'reason': 'Replaced; host-private device-private photon-private'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'retired': ['phone-a', 'phone-b']})
        self.assertEqual(set(self.registry.enrollments), {'laptop', 'jay-visible-phone-oct17'})
        self.assertNotIn('phone-a', self.registry.devices)
        self.assertNotIn('phone-a', self.registry.room.device_ids)
        self.assertIs(self.registry.devices['laptop'], self.audio.device)
        self.assertIs(self.registry.devices['jay-visible-phone-oct17'], self.phone.device)
        self.assertTrue(self.audio.device.online and self.phone.device.online)
        rows = [row for row in self.core.log.audit_rows if row['kind'] == 'host.retire']
        self.assertEqual([row['audit']['outcome'] for row in rows], ['requested', 'persisted'])
        self.assertEqual(rows[0]['audit']['operation_id'], rows[1]['audit']['operation_id'])
        for row in rows:
            self.assertEqual(row['audit']['device_ids'], ['phone-a', 'phone-b'])
            self.assertIs(row['audit']['physical_off_confirmed'], True)
            self.assertEqual(row['audit']['evidence'], 'host_observation_not_device_ack')
            self.assertNotIn('phone-a', row['text'])
        text = self.log.read_text()
        for secret in ('host-private', 'device-private', 'photon-private'):
            self.assertNotIn(secret, text)
        self.assertEqual(self.phone.frames + self.audio.frames + obsolete.frames, [])
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_persistence_failure_keeps_memory_and_prior_file_but_fails_guest_access_closed(self):
        lease = self.core.leases.create()
        previous = self.path.read_bytes()
        with patch('brain.core.persistence.os.replace', side_effect=OSError('disk unavailable')):
            response = self.retire()
        self.assertEqual(response.status_code, 503)
        self.assert_old_preserved()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertFalse(self.registry.persistence_healthy)
        self.assertIsNone(self.core.leases.current(lease.guest_id))
        self.assertEqual(self.client.post('/join', headers={'Origin': 'https://testserver'},
                                         json={'room_code': self.registry.room.code}).status_code, 503)
        self.assertEqual(self.core.log.audit_rows[-1]['audit']['outcome'], 'persistence_unconfirmed')
        self.assertEqual(self.phone.frames + self.audio.frames, [])

    def test_audit_failure_before_persistence_stays_closed_until_trusted_reload(self):
        with patch.object(self.core.log, 'append', side_effect=OSError('audit unavailable')):
            response = self.retire()
        self.assertEqual(response.status_code, 503)
        self.assert_old_preserved()
        self.assertFalse(self.registry.persistence_healthy)
        before = self.path.read_bytes()
        self.assertFalse(self.registry.persist())
        self.assertEqual(self.path.read_bytes(), before)
        restored = RoomStateStore(self.path).load_registry('TEST')
        self.assertTrue(restored.persistence_healthy)
        self.assertIn('phone-a', restored.enrollments)

    def test_completion_audit_failure_reports_persisted_retirement_and_fails_closed(self):
        append = self.core.log.append
        def fail_completion(*args, **kwargs):
            if kwargs.get('outcome') == 'persisted': raise OSError('audit unavailable')
            return append(*args, **kwargs)
        with patch.object(self.core.log, 'append', side_effect=fail_completion):
            response = self.retire()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail']['retired'], ['phone-a', 'phone-b'])
        self.assertNotIn('phone-a', json.loads(self.path.read_text())['enrollments'])
        self.assertFalse(self.registry.persistence_healthy)

    def test_restart_refuses_old_alias_but_allows_fresh_current_invitation_enrollment(self):
        self.assertEqual(self.retire().status_code, 200)
        restored = RoomStateStore(self.path).load_registry('TEST')
        for device_id, alias in (('phone-a', 'OLD1'), ('phone-b', 'OLD2')):
            with self.assertRaises(ValueError):
                restored.register(hello(device_id, room=alias), object())
        self.assertEqual(set(restored.enrollments), {'laptop', 'jay-visible-phone-oct17'})
        fresh = restored.register(hello('phone-a', room=restored.room.code), object())
        self.assertEqual(fresh.id, 'phone-a')  # Retirement is not a permanent ID ban.

    def test_next_reset_needs_current_target_acks_and_remains_unconfirmed_on_offline_target(self):
        initial = self.client.post('/host/reset', headers=HOST).json()
        self.assertEqual(initial['cleanup'], 'unconfirmed')
        before = len(self.phone.frames), len(self.audio.frames)
        self.assertEqual(self.retire().json(), {'ok': True, 'retired': ['phone-a', 'phone-b']})
        self.assertEqual((len(self.phone.frames), len(self.audio.frames)), before)
        reset = self.client.post('/host/reset', headers=HOST).json()
        self.assertEqual(reset['cleanup'], 'confirmed')
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
        self.assertEqual(self.audio.frames[-1]['cap'], 'music.pause')
        self.registry.offline(self.phone.device)
        self.assertEqual(self.client.post('/host/reset', headers=HOST).json()['cleanup'], 'unconfirmed')
