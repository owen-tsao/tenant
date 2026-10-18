"""Run explicitly after Root's proposed wiring patch, with fake device I/O only.

python -m unittest discover -s tests -p 'device_metadata_wiring_checks.py'
The default suite remains usable while central wiring is intentionally unapplied.
"""
import asyncio
import json
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from brain.config import Config
from brain.core.device_metadata import update_metadata
from brain.core.guest_view import lease_frame
from brain.main import create_app
from test_room_conversation import NativeSession, settings_for


class Socket:
    def __init__(self, bus):
        self.bus, self.device, self.frames = bus, None, []

    async def send_json(self, frame):
        self.frames.append(frame)
        self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': dict(frame['args'])})


class WiringChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.native = NativeSession()
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://testserver'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.lease = self.core.leases.create()
        self.socket = Socket(self.core.bus)
        self.dev = self.socket.device = self.core.registry.register({
            'type': 'hello', 'room': 'TEST', 'id': 'mac', 'label': 'Configured Mac', 'caps': {
                'light': {'args': {'on': {'type': 'boolean'}}, 'description': 'Light'},
                'say': {'args': {'text': {'type': 'string'}}, 'description': 'Speak'},
                'camera.capture': {'args': {}, 'description': 'Declared but gated'},
                'beat.start': {'args': {}, 'description': 'Existing beat adapter'}}}, self.socket)

    async def asyncTearDown(self):
        await self.core.agent.close()

    async def test_public_inventory_and_guest_controls_are_truthful_without_authority_renewal(self):
        original = self.lease.expires_at
        update_metadata(self.core, self.dev.id, {'role': 'room_audio', 'location': 'Table',
                                               'output_description': 'Host says the Mac uses a speaker'})
        row = self.core.snapshot()['devices'][0]
        self.assertEqual(row['role'], 'room_audio')
        self.assertEqual(row['provenance']['location']['source'], 'host_specified')
        self.assertEqual(row['provenance']['capabilities']['source'], 'adapter_reported')
        self.assertNotIn('camera.capture', row['caps'])
        encoded = json.dumps(self.core.snapshot())
        for private in ('device-private', 'host-private', 'Declared but gated', '"args"', '"ws"'):
            self.assertNotIn(private, encoded)
        self.assertEqual(len(self.core.snapshot()['devices']), 1)  # Mac output is an attribute.
        self.assertIn('say', lease_frame(self.core, self.lease.guest_id)['controls'][0]['caps'])
        update_metadata(self.core, self.dev.id, {'allowed': False})
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'], [])
        self.assertEqual(self.core.snapshot()['devices'][0]['caps'], [])
        self.assertEqual((self.lease.state, self.lease.expires_at), ('joining', original))

    async def test_host_denial_while_queued_blocks_dispatch_even_after_reenable(self):
        lock = self.core.bus.locks[self.dev.id]
        await lock.acquire()
        task = asyncio.create_task(self.core.bus.call(self.dev.id, 'light', {'on': True},
                                                      authorize=lambda *_: True))
        await asyncio.sleep(0)
        update_metadata(self.core, self.dev.id, {'allowed': False})
        update_metadata(self.core, self.dev.id, {'allowed': True})
        lock.release()
        result = await task
        self.assertEqual(result.code, 'PERMISSION')
        self.assertEqual(self.socket.frames, [])
        fresh = await self.core.bus.call(self.dev.id, 'light', {'on': False}, authorize=lambda *_: True)
        self.assertTrue(fresh.ok)  # A fresh explicit request remains distinct from replay.
        self.assertEqual(len(self.socket.frames), 1)

    async def test_bus_covers_host_calls_stale_binding_feature_gate_and_missing_guest_authority(self):
        gated = await self.core.bus.call(self.dev.id, 'camera.capture', {}, authorize=lambda *_: True)
        self.assertEqual(gated.code, 'PERMISSION')
        missing = await self.core.bus.call(self.dev.id, 'light', {'on': True})
        self.assertEqual(missing.code, 'PERMISSION')
        self.dev.last_seen -= 11
        stale = await self.core.bus.call(self.dev.id, 'light', {'on': True}, authorize=lambda *_: True)
        self.assertEqual(stale.code, 'PERMISSION')
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'], [])
        self.assertFalse(self.core.snapshot()['devices'][0]['online'])
        self.assertEqual(self.core.snapshot()['devices'][0]['connection_state'], 'unknown')
        self.assertEqual(self.socket.frames, [])

    async def test_native_inventory_voice_choices_and_program_inventory_filter_host_denial(self):
        self.native.auto_finish = False
        running = asyncio.create_task(self.core.agent.turn(self.lease.guest_id, 'Read only device inquiry'))
        try:
            await self.native.started.wait()
            tools = self.core.agent.device_tools
            grant = next(iter(tools._grants.values()))
            before = await tools.dispatch({'token': grant.token, 'operation': 'inventory'})
            self.assertTrue(before['devices'][0]['executable'])
            self.assertNotIn('camera.capture', [c['name'] for c in before['devices'][0]['caps']])
            update_metadata(self.core, self.dev.id, {'allowed': False})
            after = await tools.dispatch({'token': grant.token, 'operation': 'inventory'})
            self.assertFalse(after['devices'][0]['executable'])
            self.assertEqual(after['devices'][0]['caps'], [])
            self.assertEqual(after['reply_voice']['speakers'], [])
            self.assertEqual(after['programs']['audio_devices'], [])
            self.assertEqual(self.socket.frames, [])
            await self.native.finish('native-1', 'No device action requested')
            await running
        finally:
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

    async def test_changed_socket_cannot_inherit_queued_work(self):
        lock = self.core.bus.locks[self.dev.id]
        await lock.acquire()
        task = asyncio.create_task(self.core.bus.call(self.dev.id, 'light', {'on': True}, authorize=lambda *_: True))
        await asyncio.sleep(0)
        self.core.bus.disconnect(self.dev)
        new_socket = Socket(self.core.bus)
        new_socket.device = self.core.registry.register({'type': 'hello', 'id': self.dev.id,
            'label': 'Reconnect', 'room': 'TEST', 'caps': {'light': {'args': {'on': {'type': 'boolean'}},
                                                                     'description': 'Light'}}}, new_socket)
        lock.release()
        self.assertEqual((await task).code, 'OFFLINE')
        self.assertEqual(new_socket.frames, [])

    async def test_raw_host_capture_stays_blocked_when_photo_readiness_is_true(self):
        self.core.registry.metadata.camera_ready = lambda _dev: True
        with self.assertRaises(HTTPException) as error:
            await self.core.host_do({'device_id': self.dev.id, 'cap': 'camera.capture', 'args': {}})
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.socket.frames, [])


class HostRouteChecks(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://testserver'))
        self.core = self.app.state.core
        self.socket = Socket(self.core.bus)
        self.socket.device = self.core.registry.register({'type': 'hello', 'id': 'phone', 'label': 'Phone',
            'room': 'TEST', 'caps': {'light': {'args': {'on': {'type': 'boolean'}}, 'description': 'Light'}}}, self.socket)
        self.client = self.enterContext(TestClient(self.app))

    def test_actual_host_route_authorization_and_detached_public_display_contract(self):
        path = '/host/devices/phone/metadata'
        for headers in ({}, {'Authorization': 'Bearer wrong'}, {'X-Host-Token': 'host-private'}):
            self.assertEqual(self.client.patch(path, headers=headers, json={'role': 'capture_source'}).status_code, 403)
        response = self.client.patch(path, headers={'Authorization': 'Bearer host-private'},
                                     json={'role': 'capture_source', 'location': 'Whiteboard'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['device']['role'], 'capture_source')
        with self.client.websocket_connect('/ws/display', headers={'Origin': 'https://testserver'}) as ws:
            frame = ws.receive_json()
            self.assertEqual(frame['devices'][0]['location'], 'Whiteboard')
            self.assertEqual(frame['devices'][0]['provenance']['role']['source'], 'host_specified')
        self.assertEqual(self.client.patch('/host/devices/unknown/metadata',
            headers={'Authorization': 'Bearer host-private'}, json={'role': 'projector'}).status_code, 404)

    def test_host_denial_is_enforced_by_existing_host_do(self):
        headers = {'Authorization': 'Bearer host-private'}
        self.assertEqual(self.client.patch('/host/devices/phone/metadata', headers=headers,
                         json={'allowed': False}).status_code, 200)
        response = self.client.post('/host/do', headers=headers,
                                   json={'device_id': 'phone', 'cap': 'light', 'args': {'on': True}})
        self.assertEqual(response.json()['code'], 'PERMISSION')
        self.assertEqual(self.socket.frames, [])
