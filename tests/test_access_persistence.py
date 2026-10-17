import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from brain.core.persistence import RoomStateStore, RoomStateError
from test_access_core import make_app, hello, register, Socket, Planner, Clock


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'var' / 'room.json'
        self.store = RoomStateStore(self.path)
        self.registry = self.store.load_registry('TEST')
        self.app, self.core = make_app(registry=self.registry)
        self.phone = register(self.core)

    async def test_restart_after_reset_preserves_room_epoch_and_enrollment_only(self):
        lease = self.core.leases.create()
        token = self.core.issue_credential(lease.guest_id)
        before_id, before_epoch = self.registry.room.id, self.registry.room.epoch
        await self.core.reset()
        current_code, current_epoch = self.registry.room.code, self.registry.room.epoch
        self.assertGreater(current_epoch, before_epoch)
        restored = RoomStateStore(self.path).load_registry('TEST')
        self.assertEqual(restored.room.id, before_id)
        self.assertEqual(restored.room.code, current_code)
        self.assertEqual(restored.room.epoch, current_epoch)
        self.assertEqual(restored.devices, {})
        app, core = make_app(registry=restored)
        self.assertEqual(core.leases.leases, {})
        self.assertEqual(core.credentials, {})
        self.assertFalse(core.authentic_guest(lease.guest_id, {core.cookie_name(lease.guest_id): token}))
        # An enrolled device may still hold its pre-reset alias when it was offline.
        device = restored.register(hello(room='TEST'), Socket(core.bus))
        self.assertEqual(device.room_code, current_code)
        self.assertEqual(device.room_id, before_id)
        with self.assertRaises(ValueError):
            restored.register(hello('stranger', room='TEST'), Socket(core.bus))
        content = self.path.read_text()
        for forbidden in (lease.guest_id, token, 'messages', 'capabilities', 'ws', 'credentials'):
            self.assertNotIn(forbidden, content)
        self.assertEqual(set(json.loads(content)), {'version', 'room', 'enrollments'})
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    async def test_repeated_restart_and_reset_keeps_monotonic_epoch_and_canonical_alias(self):
        await self.core.reset()
        code_a, epoch_a = self.registry.room.code, self.registry.room.epoch
        restored = self.store.load_registry('TEST')
        app, core = make_app(registry=restored)
        device = restored.register(hello(room='TEST'), Socket(core.bus))
        self.assertEqual(device.room_code, code_a)
        core.leases.create()
        await core.reset()
        self.assertGreater(restored.room.epoch, epoch_a)
        again = self.store.load_registry('TEST')
        app2, core2 = make_app(registry=again)
        rehello = again.register(hello(room=code_a), Socket(core2.bus))
        self.assertEqual(rehello.room_id, self.registry.room.id)
        self.assertGreaterEqual(again.room.epoch, restored.room.epoch)

    async def test_reset_persists_authority_before_cleanup_await(self):
        lease = self.core.leases.create()
        seen = []
        async def cleanup(core):
            data = json.loads(self.path.read_text())
            seen.append((lease.state, data['room']['code'], data['room']['epoch']))
            await asyncio.sleep(0)
            return True
        self.core.cleanup_hook = cleanup
        result = await self.core.reset()
        self.assertEqual(result['cleanup'], 'confirmed')
        self.assertEqual(seen, [('released', self.registry.room.code, self.registry.room.epoch)])

    async def test_revoke_and_exact_expiry_persist_epoch(self):
        clock = Clock()
        app, core = make_app(registry=self.registry, clock=clock)
        lease = core.leases.create()
        core.leases.revoke(lease.guest_id)
        self.assertEqual(json.loads(self.path.read_text())['room']['epoch'], self.registry.room.epoch)
        other = core.leases.create()
        previous = self.registry.room.epoch
        clock.now = other.expires_at
        self.assertIsNone(core.leases.current(other.guest_id))
        self.assertGreater(self.registry.room.epoch, previous)
        self.assertEqual(self.store.load_registry('TEST').room.epoch, self.registry.room.epoch)

    async def test_failed_atomic_write_keeps_previous_file_and_blocks_guest_control(self):
        lease = self.core.leases.create()
        previous = self.path.read_bytes()
        with patch('brain.core.persistence.os.replace', side_effect=OSError('disk unavailable')):
            result = await self.core.reset()
        self.assertFalse(result['ok'])
        self.assertEqual(lease.state, 'released')
        self.assertFalse(self.registry.persistence_healthy)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.glob('.room.json-*')), [])
        self.assertIsNone(self.core.leases.current(lease.guest_id))
        frames = await self.core.agent.turn(lease.guest_id, 'turn on phone')
        self.assertIn('no longer', frames[-1]['text'])
        self.assertEqual(self.phone.frames, [])

    async def test_registration_save_failure_does_not_create_phantom_device(self):
        with patch('brain.core.persistence.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(ValueError):
                self.registry.register(hello('new-device'), Socket(self.core.bus))
        self.assertNotIn('new-device', self.registry.devices)
        self.assertNotIn('new-device', self.registry.enrollments)
        self.assertFalse(self.registry.persistence_healthy)

    async def test_invalid_existing_state_never_resets_or_overwrites_it(self):
        valid = json.loads(self.path.read_text())
        invalid = ['not json', json.dumps({}), json.dumps(dict(valid, version=True)),
                   json.dumps(dict(valid, credentials={'secret': 'bad'})),
                   json.dumps(dict(valid, room=dict(valid['room'], epoch=-1))),
                   json.dumps(dict(valid, room=dict(valid['room'], epoch=True))),
                   json.dumps(dict(valid, room=dict(valid['room'], id='unknown'))),
                   json.dumps(dict(valid, enrollments={'attacker': ['wrong code']}))]
        for content in invalid:
            with self.subTest(content=content):
                self.path.write_text(content)
                with self.assertRaises(RoomStateError):
                    self.store.load_registry('TEST')
                self.assertEqual(self.path.read_text(), content)

    async def test_unwritable_initial_store_refuses_startup(self):
        missing = Path(self.temp.name) / 'new.json'
        with patch('brain.core.persistence.os.replace', side_effect=OSError('unwritable')):
            with self.assertRaises(RoomStateError):
                RoomStateStore(missing).load_registry('TEST')
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
