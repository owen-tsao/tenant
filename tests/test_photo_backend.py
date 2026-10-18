"""Actual HTTP+service+Bus path with a fake phone and no physical/network I/O."""
import asyncio
from io import BytesIO
from types import SimpleNamespace
import unittest

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from brain.config import Config
from brain.core.bus import Bus
from brain.core.integration import install_core
from brain.core.leases import Leases
from brain.core.photo_install import install_photos
from brain.core.photos import CAPTURE_ARGS
from brain.core.registry import Registry
from brain.state import Room

ORIGIN = 'https://testserver'
HOST = {'Origin': ORIGIN, 'Authorization': 'Bearer host-private'}


class Clock:
    now = 1000.
    def __call__(self):
        return self.now


class Phone:
    def __init__(self, app, core, jpeg):
        self.app, self.core, self.jpeg = app, core, jpeg
        self.frames = []
        self.fail_ack = False

    async def send_json(self, frame):
        self.frames.append(frame)
        args = frame['args']
        # Exercise the actual streamed upload route while the actual Bus waits.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN) as client:
            result = await client.post(args['upload_url'], content=self.jpeg,
                headers={'Origin': ORIGIN, 'Content-Type': 'image/jpeg',
                         'Authorization': 'Bearer ' + args['upload_token']})
        self.upload_status = result.status_code
        self.core.bus.receive(self.dev, {'type': 'ok', 'req': frame['req'], 'result':
            {'capture_id': 'wrong' if self.fail_ack else args['capture_id'], 'state': 'captured'}})


class PhotoBackendTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.app = FastAPI()
        self.app.state.config = Config('device-private', 'host-private', 'TEST', ORIGIN)
        self.app.state.registry = Registry(Room('TEST', 'Room TEST'))
        self.app.state.bus = Bus(self.app.state.registry)
        self.core = install_core(self.app, object(), clock=self.clock)
        authority = lambda lease, generation: self.core.leases.current(lease.guest_id) is lease
        # Central composition installs this owner itself; the unmodified shared
        # Core does not. Both fixtures use the same explicit fake guest policy.
        if getattr(self.core, 'photos', None) is None:
            self.service = install_photos(self.app, self.core, authority=authority)
        else:
            self.service = self.core.photos
            self.service.authority = authority
        blob = BytesIO()
        Image.new('RGB', (40, 30), 'orange').save(blob, 'JPEG', comment=b'private image metadata')
        self.jpeg = blob.getvalue()
        self.phone = Phone(self.app, self.core, self.jpeg)
        self.phone.dev = self.core.registry.register({'type': 'hello', 'id': 'phone', 'label': 'Room phone',
            'room': 'TEST', 'caps': {'camera.capture': {'args': CAPTURE_ARGS, 'description': 'Still photo'}}}, self.phone)
        self.service.device_event(self.phone.dev, {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.client.__enter__()
        self.assertEqual(self.client.post('/host/photos/config', headers=HOST,
            json={'source_device_id': 'phone', 'viewer_id': 'mac-main', 'enabled': True}).status_code, 200)
        self.assertEqual(self.client.post('/host/photos/viewer', headers=HOST,
            json={'viewer_id': 'mac-main'}).status_code, 200)
        self.lease = self.core.leases.create()
        self.core.leases.current(self.lease.guest_id, activate=True)
        self.client.cookies.set(self.core.cookie_name(self.lease.guest_id), self.core.issue_credential(self.lease.guest_id))

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def capture(self, request_id='shot-1'):
        return self.client.post('/photos/captures', headers={'Origin': ORIGIN}, json={
            'guest_id': self.lease.guest_id, 'request_id': request_id, 'source_device_id': 'phone'})

    def display(self):
        state = self.client.get('/photos/viewer/state').json()
        photo = state['photo']
        image = self.client.get(photo['image_url'])
        self.assertEqual(image.status_code, 200)
        self.assertNotIn(b'private image metadata', image.content)
        receipt = self.client.post('/photos/viewer/receipt', headers={'Origin': ORIGIN},
            json={'photo_id': photo['photo_id'], 'version': photo['version']})
        self.assertEqual(receipt.status_code, 200)
        return photo

    def test_complete_route_bus_image_viewer_path_and_ordinary_leave_retention(self):
        result = self.capture()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.phone.upload_status, 200)
        self.assertEqual(result.json()['state'], 'ready')
        self.assertFalse(result.json()['displayed'])
        serialized = result.text
        self.assertNotIn('upload_token', serialized)
        self.assertNotIn('image_url', serialized)
        photo = self.display()
        status = self.client.get('/photos/captures/shot-1', params={'guest_id': self.lease.guest_id})
        self.assertTrue(status.json()['displayed'])
        leave = self.client.post('/leave', headers={'Origin': ORIGIN}, json={'guest_id': self.lease.guest_id})
        self.assertEqual(leave.status_code, 200)
        # Root's explicit revoke hook changes only pending work.
        self.service.invalidate_guest(self.lease.guest_id)
        self.assertEqual(self.client.get('/photos/viewer/state').json()['photo']['photo_id'], photo['photo_id'])
        self.core.leases.create()
        self.assertEqual(self.client.get(photo['image_url']).status_code, 200)
        snapshot = self.core.snapshot()
        self.assertNotIn('image_url', str(snapshot))
        self.assertNotIn('upload_token', str(snapshot))
        self.assertTrue(all(not session.messages for session in self.core.leases.sessions.values()))
        self.assertEqual(len(self.phone.frames), 1)

    def test_failed_ack_never_publishes_new_image_and_old_display_survives(self):
        self.assertEqual(self.capture().json()['state'], 'ready')
        old = self.display()
        self.phone.fail_ack = True
        failed = self.capture('shot-2').json()
        self.assertEqual(failed['state'], 'unknown')
        state = self.client.get('/photos/viewer/state').json()
        self.assertEqual(state['photo']['photo_id'], old['photo_id'])
        self.assertEqual(self.capture('shot-2').json()['state'], 'unknown')
        self.assertEqual(len(self.phone.frames), 2)

    def test_host_reset_hook_clears_bytes_and_blocks_old_render_receipt(self):
        self.assertEqual(self.capture().json()['state'], 'ready')
        old = self.display()
        # This deliberately tests the exact synchronous hook ordering Root applies.
        self.core.leases.reset()
        self.service.reset()
        state = self.client.get('/photos/viewer/state').json()
        self.assertIsNone(state['photo'])
        self.assertGreater(state['version'], old['version'])
        self.assertEqual(self.client.get(old['image_url']).status_code, 404)
        self.assertEqual(self.client.post('/photos/viewer/receipt', headers={'Origin': ORIGIN},
            json={'photo_id': old['photo_id'], 'version': old['version']}).status_code, 409)
        self.assertIsNone(self.service.latest)
        self.assertTrue(all(rec.image is None for rec in self.service.records.values()))

    def test_default_installer_fails_closed_without_native_controller_policy(self):
        app = FastAPI()
        class Core:
            agent = object()
            registry, bus, leases = self.core.registry, self.core.bus, self.core.leases
        core = Core()
        service = install_photos(app, core)
        self.assertFalse(service.authority(self.lease, 0))
        with self.assertRaises(ValueError):
            install_photos(app, core)

    def test_installer_attaches_actual_readiness_owner_and_native_policy(self):
        app = FastAPI()
        registry = Registry(Room('TEST', 'Installer test'))
        leases = Leases(registry.room, clock=self.clock)
        devices = SimpleNamespace()
        policy = lambda lease, generation: lease is self.lease and generation == 12
        core = SimpleNamespace(registry=registry, bus=Bus(registry), leases=leases,
            agent=SimpleNamespace(allows_program=policy, device_tools=devices))
        self.assertFalse(registry.metadata.camera_ready(self.phone.dev))
        service = install_photos(app, core)
        self.assertIs(core.photos, service)
        self.assertIs(devices.photos, service)
        self.assertIs(registry.metadata.camera_ready.__self__, service)
        self.assertIs(service.authority, policy)
        self.assertTrue(service.authority(self.lease, 12))
        self.assertFalse(service.authority(self.lease, 13))
        self.assertFalse(registry.metadata.camera_ready(self.phone.dev))
        self.assertEqual(self.phone.frames, [])

    def test_installed_hook_reflects_opt_in_viewer_and_host_allowance(self):
        metadata = self.core.registry.metadata
        self.assertIs(metadata.camera_ready.__self__, self.service)
        self.assertTrue(metadata.available(self.phone.dev, 'camera.capture'))
        self.service.device_event(self.phone.dev, {'type': 'photo.consent', 'enabled': False, 'ready': False})
        self.assertFalse(metadata.available(self.phone.dev, 'camera.capture'))
        denied = self.capture('consent-denied')
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.phone.frames, [])
        self.service.device_event(self.phone.dev, {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.clock.now += self.service.viewer_ttl
        self.assertFalse(metadata.available(self.phone.dev, 'camera.capture'))
        self.assertEqual(self.capture('viewer-expired').status_code, 409)
        self.assertEqual(self.phone.frames, [])
        self.assertEqual(self.client.get('/photos/viewer/state').status_code, 200)
        self.assertTrue(metadata.available(self.phone.dev, 'camera.capture'))
        self.service.configure('phone', 'mac-main', enabled=False)
        self.assertFalse(metadata.available(self.phone.dev, 'camera.capture'))
        self.assertEqual(self.capture('host-disabled').status_code, 403)
        self.assertEqual(self.phone.frames, [])


if __name__ == '__main__':
    unittest.main()
