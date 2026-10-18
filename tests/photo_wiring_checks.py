"""Run ONLY in a disposable copy with proposed metadata+photo patches applied.

All sessions, sockets, pixels and viewer receipts are fakes. No external model,
public UI, camera, deployed service or physical output is touched.
"""
import asyncio
from contextlib import suppress
from io import BytesIO
import json
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from agent.tenant_device import invoke
from brain.config import Config
from brain.core.device_metadata import update_metadata
from brain.core.photos import CAPTURE_ARGS
from brain.main import create_app
from test_room_conversation import Clock, NativeSession, settings_for


class FakePhone:
    def __init__(self, core):
        self.core = core
        self.frames = []
        self.ack = True
        self.bad_ack = False
        image = BytesIO()
        Image.new('RGB', (24, 18), 'purple').save(image, 'JPEG')
        self.jpeg = image.getvalue()

    async def send_json(self, frame):
        self.frames.append(frame)
        if self.ack:
            args = frame['args']
            await self.core.photos.upload(args['capture_id'], args['upload_token'], self.jpeg, 'image/jpeg')
            self.core.bus.receive(self.device, {'type': 'ok', 'req': frame['req'],
                'result': {'capture_id': 'wrong' if self.bad_ack else args['capture_id'], 'state': 'captured'}})


class PhotoNativeWiringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.native, self.clock = NativeSession(), Clock()
        self.native.auto_finish = False
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.photos = self.core.photos
        self.core.leases.clock = self.clock
        self.photos.clock = self.clock
        self.lease = self.core.leases.create()
        self.phone = FakePhone(self.core)
        self.phone.device = self.core.registry.register({'type': 'hello', 'id': 'photo-phone',
            'label': 'Room photo phone', 'room': 'TEST', 'caps': {'camera.capture': {
            'description': 'One opted-in still', 'args': CAPTURE_ARGS}}}, self.phone)
        self.photos.configure('photo-phone', 'mac-main')
        self.viewer = self.photos.enroll_viewer('mac-main')
        self.photos.device_event(self.phone.device, {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.turn = None

    async def asyncTearDown(self):
        if self.turn and not self.turn.done():
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)
        self.photos.close()
        await self.core.agent.close()

    async def begin(self, text='Take the opted-in group still.'):
        self.native.started.clear()
        self.turn = asyncio.create_task(self.core.agent.turn(self.lease.guest_id, text))
        await asyncio.wait_for(self.native.started.wait(), 1)
        self.grant = next(iter(self.core.agent.device_tools._grants.values()))
        return self.grant

    async def finish(self):
        await self.native.finish(self.native.active_turn_id, 'The photo result is recorded.')
        await self.turn
        self.turn = None

    async def call(self, operation, payload):
        return await asyncio.to_thread(invoke, self.grant.path, operation, payload)

    async def capture(self, request_id='still-1'):
        return await self.call('photo-capture', {'request_id': request_id, 'source_device_id': 'photo-phone'})

    def render(self):
        state = self.photos.viewer_state(self.viewer)
        image = state['photo']
        self.assertTrue(self.photos.image(self.viewer, image['photo_id']))
        self.photos.viewer_receipt(self.viewer, image['photo_id'], image['version'])
        return image

    async def test_private_helper_camera_hook_bus_capture_and_later_render_same_guest(self):
        await self.begin()
        self.assertIs(self.core.agent.device_tools.photos, self.photos)
        inventory = await self.call('inventory', {})
        self.assertTrue(inventory['photos']['ready'])
        self.assertTrue(self.core.registry.metadata.available(self.phone.device, 'camera.capture'))
        self.assertNotIn('camera.capture', [cap['name'] for row in inventory['devices'] for cap in row['caps']])
        response = await self.capture()
        self.assertEqual(response['state'], 'ready', response)
        self.assertEqual(len(self.phone.frames), 1)
        self.assertNotIn('upload_token', json.dumps(response))
        self.assertNotIn('image_url', json.dumps(response))
        self.assertEqual(await self.capture(), response)
        await self.finish()  # Viewer may finish under same continuing guest lease.
        image = self.render()
        await self.begin('What is the photo status?')
        status = await self.call('photo-status', {'request_id': 'status-1', 'capture_request_id': 'still-1'})
        self.assertTrue(status['displayed'])
        self.assertNotIn('image_url', json.dumps(self.core.snapshot()))
        self.assertEqual(self.photos.latest.id, image['photo_id'])
        await self.finish()

    async def test_raw_native_and_host_camera_paths_cannot_bypass_photo_service(self):
        await self.begin()
        raw = await self.call('call', {'request_id': 'raw-1', 'device_id': 'photo-phone',
            'cap': 'camera.capture', 'args': {'capture_id': 'fake', 'upload_url': '/photos/uploads/fake',
                                           'upload_token': 'fake'}})
        self.assertFalse(raw['ok'])
        with self.assertRaises(HTTPException) as caught:
            await self.core.host_do({'device_id': 'photo-phone', 'cap': 'camera.capture', 'args': {}})
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.phone.frames, [])
        self.assertIsNone(self.photos.pending)
        await self.finish()

    async def test_metadata_role_change_while_native_capture_waits_sends_nothing(self):
        await self.begin()
        lock = self.core.bus.locks['photo-phone']
        await lock.acquire()
        task = asyncio.create_task(self.capture())
        try:
            for _ in range(100):
                if self.photos.pending is not None:
                    break
                await asyncio.sleep(.001)
            self.assertIsNotNone(self.photos.pending)
            update_metadata(self.core, 'photo-phone', {'role': 'another-role'})
        finally:
            lock.release()
        result = await asyncio.wait_for(task, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(self.phone.frames, [])
        await self.finish()

    async def test_unknown_capture_cannot_be_reissued_under_new_id_in_same_turn(self):
        self.phone.bad_ack = True
        await self.begin()
        first = await self.capture()
        self.assertEqual(first['code'], 'UNKNOWN')
        second = await self.capture('new-id')
        self.assertEqual(second['code'], 'UNKNOWN')
        self.assertEqual(len(self.phone.frames), 1)
        self.assertIsNone(self.photos.latest)
        await self.finish()

    async def test_core_revoke_retains_rendered_latest_and_new_guest_has_no_old_context(self):
        await self.begin()
        self.assertEqual((await self.capture())['state'], 'ready')
        image = self.render()
        await self.finish()
        self.core.revoke(self.lease.guest_id)
        self.assertEqual(self.photos.viewer_state(self.viewer)['photo']['photo_id'], image['photo_id'])
        self.lease = self.core.leases.create()
        await self.begin('A fresh guest request.')
        self.assertEqual([entry['id'] for entry in self.native.history], ['clean-setup', self.native.active_turn_id])
        self.assertIsNone(self.photos.pending)
        self.assertEqual(self.photos.latest.id, image['photo_id'])
        self.assertNotIn(self.phone.jpeg, [entry.get('text') for entry in self.native.history])
        await self.finish()

    async def test_host_reset_clears_photo_before_waiting_for_context_cleanup(self):
        await self.begin()
        self.assertEqual((await self.capture())['state'], 'ready')
        image = self.render()
        await self.finish()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_cleanup():
            entered.set()
            await release.wait()
            return True
        self.core.agent.reset_context = delayed_cleanup
        reset = asyncio.create_task(self.core.reset())
        await asyncio.wait_for(entered.wait(), 1)
        self.assertIsNone(self.photos.latest)
        self.assertIsNone(self.photos.viewer_state(self.viewer)['photo'])
        release.set()
        await reset
        self.assertGreater(self.photos.version, image['version'])


class PhotoDeviceSocketWiringTests(unittest.TestCase):
    def test_consent_uses_real_authenticated_ws_device_and_opt_out_stays_effect_free(self):
        native = NativeSession()
        app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                         conversation=settings_for(native))
        core = app.state.core
        with TestClient(app, base_url='https://tenant.test') as client:
            with client.websocket_connect('/ws/device?t=device-private') as socket:
                socket.send_json({'type': 'hello', 'id': 'inert-phone', 'label': 'Inert test phone', 'room': 'TEST',
                    'caps': {'camera.capture': {'description': 'Still', 'args': CAPTURE_ARGS}}})
                self.assertEqual(socket.receive_json()['type'], 'welcome')
                socket.send_json({'type': 'photo.consent', 'enabled': True, 'ready': True})
                ack = socket.receive_json()
                self.assertTrue(ack['ok'])
                self.assertTrue(core.photos.consents['inert-phone'].enabled)
                socket.send_json({'type': 'photo.consent', 'enabled': False, 'ready': False})
                self.assertFalse(socket.receive_json()['enabled'])
                self.assertIsNone(core.photos.pending)
                self.assertEqual(native.calls, [])


if __name__ == '__main__':
    unittest.main()
