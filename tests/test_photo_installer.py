"""Photo installer/readiness composition with inert sockets and in-process ASGI.

No cameras, browsers, native sessions, models, servers or deployed services run.
The normalizer is deliberately fake: image-decoder acceptance has its own suite.
"""
import asyncio
import json
from types import SimpleNamespace
import unittest

from fastapi import FastAPI
import httpx

from brain.core.bus import Bus
from brain.core.device_metadata import MAX_AGE, update_metadata
from brain.core.guest_view import lease_frame
from brain.core.integration import Core
from brain.core.leases import Leases
from brain.core.photo_install import install_photos
from brain.core.photos import CAPTURE_ARGS, PhotoError
from brain.core.registry import Registry
from brain.state import Room


ORIGIN = 'https://tenant.test'
NORMALIZED = b'private-normalized-photo-pixels'


class NativePolicy:
    def __init__(self):
        self._generation = 7
        self.owner = None
        self.allowed = True
        self.authorizations = []
        self.device_tools = SimpleNamespace()
        self.pending, self.locks = {}, {}

    def allows_program(self, lease, generation):
        self.authorizations.append((lease, generation))
        return self.allowed and lease is self.owner and generation == self._generation


class InertCore(Core):
    """Use actual authorization/public projections without starting Core's agents."""
    def __init__(self, registry, bus, leases, agent):
        self.registry, self.bus, self.leases, self.agent = registry, bus, leases, agent
        self.config = SimpleNamespace(public_url=ORIGIN, host_token='host-private', device_token='device-private')
        self.credentials = {}
        self.log = SimpleNamespace(rows=[])


class Phone:
    def __init__(self):
        self.frames = []
        self.started = asyncio.Event()
        self.mode = 'hold'

    async def send_json(self, frame):
        self.frames.append(frame)
        self.started.set()
        if self.mode == 'complete':
            args = frame['args']
            await self.core.photos.upload(args['capture_id'], args['upload_token'], b'raw-input', 'image/jpeg')
            self.core.bus.receive(self.dev, {'type': 'ok', 'req': frame['req'], 'result': {
                'capture_id': args['capture_id'], 'state': 'captured'}})


class PhotoInstallerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now, self.mono = 1000., 500.
        self.app = FastAPI()
        self.registry = Registry(Room('TEST', 'Photo composition fixture'))
        self.registry.metadata.clock = lambda: self.now
        self.registry.metadata.monotonic = lambda: self.mono
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.agent = NativePolicy()
        self.core = InertCore(self.registry, self.bus, self.leases, self.agent)
        self.app.state.core = self.core
        self.lease = self.leases.create(scopes={'camera.capture', 'photo.show'})
        self.leases.current(self.lease.guest_id, activate=True)
        self.agent.owner = self.lease
        self.phone = Phone()
        self.phone.core = self.core
        self.dev = self.register('phone', self.phone)
        self.phone.dev = self.dev
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def register(self, device_id, socket):
        device = self.registry.register({'type': 'hello', 'id': device_id, 'label': 'Room phone', 'room': 'TEST',
            'caps': {'camera.capture': {'args': CAPTURE_ARGS, 'description': 'One explicitly opted-in still'}}}, socket)
        device.last_seen = self.mono
        return device

    def install(self, **options):
        return install_photos(self.app, self.core, normalizer=lambda body, content_type: NORMALIZED, **options)

    def ready(self, **options):
        service = self.install(**options)
        service.configure('phone', 'mac-main')
        service.device_event(self.dev, {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.viewer = service.enroll_viewer('mac-main')
        return service

    def capture_task(self, request_id='shot-1'):
        task = asyncio.create_task(self.core.photos.capture(self.lease, request_id, 'phone',
                                                            generation=self.agent._generation))
        self.tasks.append(task)
        return task

    async def display(self):
        self.phone.mode = 'complete'
        result = await self.core.photos.capture(self.lease, 'shot-1', 'phone', generation=self.agent._generation)
        self.assertEqual(result['state'], 'ready')
        photo = self.core.photos.viewer_state(self.viewer)['photo']
        self.core.photos.viewer_receipt(self.viewer, photo['photo_id'], photo['version'])
        return photo

    def test_metadata_camera_gate_is_default_closed_before_installation(self):
        metadata = self.registry.metadata
        update_metadata(self.core, 'phone', {'role': 'room_camera', 'allowed': True})
        self.assertFalse(metadata.camera_ready(self.dev))
        self.assertFalse(metadata.available(self.dev, 'camera.capture'))
        self.assertEqual(metadata.public_devices()[0]['caps'], [])
        self.assertFalse(self.phone.frames)

    def test_installer_attaches_exact_service_to_readiness_helper_and_routes(self):
        service = self.install()
        self.assertIs(self.core.photos, service)
        self.assertIs(self.registry.metadata.camera_ready.__self__, service)
        self.assertIs(self.agent.device_tools.photos, service)
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))
        self.assertEqual({route.path for route in self.app.routes if 'photos' in route.path}, {
            '/host/photos/config', '/host/photos/viewer', '/photos/captures',
            '/photos/captures/{request_id}', '/photos/viewer', '/photos/viewer.js',
            '/photos/viewer/state', '/photos/images/{photo_id}',
            '/photos/viewer/receipt', '/photos/uploads/{capture_id}'})
        self.assertFalse(self.phone.frames)

    def test_duplicate_install_preserves_service_callbacks_and_route_count(self):
        service = self.ready()
        route_count = len(self.app.routes)
        with self.assertRaisesRegex(ValueError, 'already installed'):
            self.install()
        self.assertIs(self.core.photos, service)
        self.assertIs(self.registry.metadata.camera_ready.__self__, service)
        self.assertIs(self.agent.device_tools.photos, service)
        self.assertEqual(len(self.app.routes), route_count)

    async def test_missing_native_policy_fails_guest_authority_closed(self):
        self.core.agent = SimpleNamespace(device_tools=SimpleNamespace(), pending={}, locks={})
        service = self.ready()
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))
        self.assertFalse(service.inventory(self.lease, generation=7)['ready'])
        with self.assertRaises(PhotoError) as caught:
            await service.capture(self.lease, 'shot-1', 'phone', generation=7)
        self.assertEqual(caught.exception.status, 403)
        self.assertFalse(self.phone.frames)

    def test_explicit_authority_override_is_used_even_without_native_helper(self):
        self.core.agent = SimpleNamespace(pending={}, locks={})
        calls = []

        def authority(lease, generation):
            calls.append((lease, generation))
            return lease is self.lease and generation == 19

        service = self.ready(authority=authority)
        self.assertTrue(service.inventory(self.lease, generation=19)['ready'])
        self.assertFalse(service.inventory(self.lease, generation=18)['ready'])
        self.assertEqual(calls, [(self.lease, 19), (self.lease, 18)])
        self.assertFalse(self.phone.frames)

    def test_native_policy_is_rechecked_for_generation_and_controller_changes(self):
        service = self.ready()
        self.assertTrue(service.inventory(self.lease, generation=7)['ready'])
        self.agent._generation = 8
        self.assertFalse(service.inventory(self.lease, generation=7)['ready'])
        self.assertTrue(service.inventory(self.lease, generation=8)['ready'])
        self.agent.owner = self.leases.create()
        self.assertFalse(service.inventory(self.lease, generation=8)['ready'])
        # Discovery readiness remains independent of any guest's authority.
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))

    def test_roles_and_discovery_do_not_replace_photo_consent_or_selected_viewer(self):
        service = self.install()
        update_metadata(self.core, 'phone', {'role': 'room_camera', 'allowed': True})
        service.configure('phone', 'mac-main')
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))
        service.device_event(self.dev, {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))
        with self.assertRaises(PhotoError) as caught:
            service.enroll_viewer('unknown-viewer')
        self.assertEqual(caught.exception.code, 'TARGET')
        self.assertIsNone(service.viewer)
        self.viewer = service.enroll_viewer('mac-main')
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))
        service.device_event(self.dev, {'type': 'photo.consent', 'enabled': False, 'ready': False})
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))

    def test_host_photo_allowance_and_metadata_host_deny_both_gate_camera(self):
        service = self.ready()
        metadata = self.registry.metadata
        self.assertTrue(metadata.available(self.dev, 'camera.capture'))
        service.configure('phone', 'mac-main', enabled=False)
        self.assertFalse(metadata.available(self.dev, 'camera.capture'))
        service.configure('phone', 'mac-main', enabled=True)
        update_metadata(self.core, 'phone', {'allowed': False})
        self.assertFalse(service.camera_ready(self.dev))
        self.assertFalse(metadata.available(self.dev, 'camera.capture'))
        update_metadata(self.core, 'phone', {'allowed': True})
        self.assertTrue(metadata.available(self.dev, 'camera.capture'))

    def test_viewer_liveness_and_connection_binding_are_required(self):
        service = self.ready()
        self.now += service.viewer_ttl
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))
        service.viewer_state(self.viewer)
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))
        self.mono += MAX_AGE
        self.assertFalse(service.camera_ready(self.dev))
        self.dev.last_seen = self.mono
        self.assertTrue(service.camera_ready(self.dev))
        self.dev.ws = Phone()
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))

    async def test_future_viewer_timestamp_grants_neither_readiness_nor_capture(self):
        service = self.ready()
        self.now -= 1
        self.assertFalse(service.camera_ready(self.dev))
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))
        self.assertFalse(service.inventory(self.lease, generation=7)['ready'])
        with self.assertRaises(PhotoError) as caught:
            await service.capture(self.lease, 'shot-1', 'phone', generation=7)
        self.assertEqual(caught.exception.code, 'VIEWER_OFFLINE')
        self.assertFalse(self.phone.frames)

    async def test_pending_dispatch_does_not_close_its_own_metadata_gate(self):
        service = self.ready()
        task = self.capture_task()
        await asyncio.wait_for(self.phone.started.wait(), 1)
        self.assertIsNotNone(service.pending)
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))
        self.assertFalse(service.inventory(self.lease, generation=7)['ready'])
        frame = self.phone.frames[0]
        self.bus.receive(self.dev, {'type': 'err', 'req': frame['req'], 'code': 'FAILED', 'message': 'fake denial'})
        self.assertEqual((await task)['state'], 'failed')

    async def test_epoch_change_cancels_pending_capture_but_not_device_readiness(self):
        service = self.ready()
        task = self.capture_task()
        await asyncio.wait_for(self.phone.started.wait(), 1)
        self.registry.room.epoch += 1
        service.sweep()
        frame = self.phone.frames[0]
        self.bus.receive(self.dev, {'type': 'ok', 'req': frame['req'], 'result': {
            'capture_id': frame['args']['capture_id'], 'state': 'captured'}})
        self.assertEqual((await task)['state'], 'cancelled')
        self.assertIsNone(service.latest)
        self.assertIsNone(service.pending)
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))

    async def test_metadata_revision_change_fences_installed_pending_capture(self):
        service = self.ready()
        task = self.capture_task()
        await asyncio.wait_for(self.phone.started.wait(), 1)
        update_metadata(self.core, 'phone', {'location': 'whiteboard'})
        service.sweep()
        frame = self.phone.frames[0]
        self.bus.receive(self.dev, {'type': 'ok', 'req': frame['req'], 'result': {
            'capture_id': frame['args']['capture_id'], 'state': 'captured'}})
        self.assertEqual((await task)['state'], 'cancelled')
        self.assertIsNone(service.latest)

    async def test_public_projections_never_receive_image_bytes_urls_or_tickets(self):
        service = self.ready()
        photo = await self.display()
        token = self.phone.frames[0]['args']['upload_token']
        projections = json.dumps({'state': self.core.snapshot(), 'metadata': self.registry.metadata.public_devices(),
                                  'guest': lease_frame(self.core, self.lease.guest_id),
                                  'inventory': service.inventory(self.lease, generation=7),
                                  'status': service.status(self.lease, 'shot-1')})
        for private in (NORMALIZED.decode(), token, self.viewer, photo['image_url'], 'upload_token', 'image_url'):
            self.assertNotIn(private, projections)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN) as client:
            for path in ('/photos/viewer/state', photo['image_url']):
                response = await client.get(path)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(NORMALIZED, response.content)
                self.assertEqual(response.headers['cache-control'], 'no-store')

    async def test_installed_service_retains_display_through_guest_end_then_reset_clears(self):
        service = self.ready()
        photo = await self.display()
        self.leases.revoke(self.lease.guest_id)
        service.invalidate_guest(self.lease.guest_id)
        self.leases.create()
        self.assertEqual(service.viewer_state(self.viewer)['photo']['photo_id'], photo['photo_id'])
        self.assertEqual(service.image(self.viewer, photo['photo_id']), NORMALIZED)
        self.leases.reset()
        service.reset()  # Exact synchronous lifecycle hook required from Root.
        state = service.viewer_state(self.viewer)
        self.assertIsNone(state['photo'])
        self.assertGreater(state['version'], photo['version'])
        with self.assertRaises(PhotoError) as caught:
            service.image(self.viewer, photo['photo_id'])
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(PhotoError) as caught:
            service.viewer_receipt(self.viewer, photo['photo_id'], photo['version'])
        self.assertEqual(caught.exception.status, 409)

    def test_closing_installed_service_closes_camera_readiness_without_unwiring(self):
        service = self.ready()
        self.assertTrue(self.registry.metadata.available(self.dev, 'camera.capture'))
        service.close()
        self.assertFalse(self.registry.metadata.available(self.dev, 'camera.capture'))
        self.assertIs(self.agent.device_tools.photos, service)
        self.assertIs(self.registry.metadata.camera_ready.__self__, service)


if __name__ == '__main__':
    unittest.main()
