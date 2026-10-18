"""Run in an isolated copy with proposed-photo-readiness-wiring.patch applied.

Only an in-memory registry and temporary private helper socket are used.
"""
import asyncio
import unittest

from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.native_devices import NativeDevices
from brain.core.photos import CAPTURE_ARGS, PhotoService
from brain.core.registry import Registry
from brain.state import Room


class InertSocket:
    def __init__(self):
        self.frames = []

    async def send_json(self, frame):
        self.frames.append(frame)


class PhotoReadinessWiringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry(Room('TEST', 'Readiness test'))
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room)
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        self.photos = PhotoService(self.registry, self.bus, self.leases, authority=lambda *_: True)
        self.registry.metadata.camera_ready = self.photos.camera_ready
        self.tools = NativeDevices(self.registry, self.bus, self.leases, EventLog(), lambda _: True)
        self.tools.photos = self.photos
        self.grant = await self.tools.prepare(self.lease.guest_id, 1, self.lease, 'inert-thread')
        self.tools.activate(self.grant, 'inert-turn')
        self.socket = InertSocket()

    async def asyncTearDown(self):
        await self.tools.close()
        self.photos.close()

    async def inventory(self):
        return await self.tools.dispatch({'operation': 'inventory', 'token': self.grant.token})

    async def test_disabled_backend_exposes_safe_missing_reason_not_a_phantom_capability(self):
        reply = await self.inventory()
        self.assertTrue(reply['ok'])
        self.assertFalse(reply['photos']['ready'])
        self.assertEqual(reply['photos']['reason'], 'DISABLED')
        self.assertIsNone(reply['photos']['source_device_id'])
        self.assertEqual(reply['devices'], [])
        self.assertFalse(self.photos.enabled)
        self.assertIsNone(self.photos.viewer)
        self.assertIsNone(self.photos.pending)

    async def test_guest_scope_denial_is_visible_without_host_configuration_leak(self):
        self.lease.scopes = {'computer'}
        reply = await self.inventory()
        self.assertEqual(reply['photos']['reason'], 'SCOPE_REQUIRED')
        self.assertIsNone(reply['photos']['source_label'])
        self.assertNotIn('viewer_id', reply['photos'])
        self.assertFalse(reply['photos']['ready'])

    async def test_ready_dedicated_photo_path_does_not_enable_raw_capture(self):
        phone = self.registry.register({'type': 'hello', 'id': 'phone', 'label': 'Room phone', 'room': 'TEST',
            'caps': {'camera.capture': {'description': 'Still', 'args': CAPTURE_ARGS}}}, self.socket)
        self.photos.configure('phone', 'mac-main')
        self.photos.device_event(phone, {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.photos.enroll_viewer('mac-main')
        self.assertTrue((await self.inventory())['photos']['ready'])
        result = await self.tools.dispatch({'token': self.grant.token, 'operation': 'call',
            'request_id': 'raw-camera', 'device_id': 'phone', 'cap': 'camera.capture',
            'args': {'capture_id': 'untrusted', 'upload_url': '/photos/uploads/untrusted', 'upload_token': 'untrusted'}})
        self.assertFalse(result['ok'])
        self.assertEqual(self.socket.frames, [])
        self.assertIsNone(self.photos.pending)


if __name__ == '__main__':
    unittest.main()
