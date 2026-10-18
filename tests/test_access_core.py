import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from brain.config import Config
from brain.state import Room
from brain.core.registry import Registry
from brain.core.bus import Bus
from brain.core.integration import install_core


ORIGIN = 'https://testserver'
HEADERS = {'Origin': ORIGIN}
HOST_HEADERS = {'Authorization': 'Bearer host-private'}


def hello(device_id='phone', *, cap='light', room='TEST', label=None):
    args = {'on': {'type': 'boolean'}} if cap == 'light' else {'text': {'type': 'string'}}
    return {'type': 'hello', 'id': device_id, 'label': label or device_id, 'room': room,
            'caps': {cap: {'description': cap, 'args': args}}}


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


class Planner:
    def __init__(self, plan=None):
        self.output = plan or {'kind': 'action', 'device_id': 'phone', 'cap': 'light', 'args': {'on': True}}
        self.calls = []
        self.called = asyncio.Event()
    async def plan(self, text, inventory, history):
        self.calls.append((text, inventory, history))
        self.called.set()
        return self.output


class Socket:
    def __init__(self, bus, *, auto=True):
        self.bus, self.auto = bus, auto
        self.frames = []
        self.sent = asyncio.Event()
        self.dev = None
    async def send_json(self, frame):
        self.frames.append(frame)
        self.sent.set()
        if self.auto:
            self.bus.receive(self.dev, {'type': 'ok', 'req': frame['req'], 'result': frame['args']})


def make_app(*, planner=None, clock=None, cleanup_hook=None, log_path=None, registry=None):
    app = FastAPI()
    app.state.config = Config('device-private', 'host-private', 'TEST', ORIGIN)
    app.state.registry = registry or Registry(Room('TEST', 'Room TEST'))
    app.state.bus = Bus(app.state.registry)
    core = install_core(app, planner or Planner(), clock=clock or Clock(),
                        cleanup_hook=cleanup_hook, log_path=log_path)
    @app.post('/host/do')
    async def host_do(request: Request):
        core.require_host(request)
        return await core.host_do(await request.json())
    return app, core


def register(core, device_id='phone', *, auto=True, cap='light', label=None):
    socket = Socket(core.bus, auto=auto)
    socket.dev = core.registry.register(hello(device_id, cap=cap, label=label), socket)
    return socket


class AccessCoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.planner = Planner()
        self.app, self.core = make_app(planner=self.planner, clock=self.clock)
        self.phone = register(self.core)
        self.lease = self.core.leases.create()

    async def turn(self, text='turn on phone'):
        return await self.core.agent.turn(self.lease.guest_id, text)

    async def test_join_activation_and_real_bus_ack(self):
        self.assertEqual(self.lease.state, 'joining')
        frames = await self.turn()
        self.assertEqual(self.lease.state, 'active')
        self.assertEqual([f['type'] for f in frames], ['action', 'assistant'])
        self.assertEqual(self.phone.frames[0]['args'], {'on': True})
        self.assertEqual(len(self.planner.calls), 1)

    async def test_activation_does_not_extend_issued_ttl(self):
        issued_expiry = self.lease.expires_at
        self.clock.now += 50
        await self.turn()
        self.assertEqual(self.lease.expires_at, issued_expiry)
        self.clock.now = issued_expiry - .0001
        self.assertIs(self.core.leases.current(self.lease.guest_id), self.lease)
        self.clock.now = issued_expiry
        before = len(self.planner.calls)
        self.assertIn('no longer', (await self.turn())[-1]['text'])
        self.assertEqual(len(self.planner.calls), before)
        self.assertEqual(self.lease.state, 'expired')
        self.assertEqual(len(self.phone.frames), 1)

    async def test_joining_expiry_is_exact_at_120_seconds(self):
        self.clock.now += 120
        frames = await self.turn()
        self.assertIn('no longer', frames[-1]['text'])
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_revoke_and_absent_lease_no_planner_calls(self):
        self.core.revoke(self.lease.guest_id)
        self.assertIn('no longer', (await self.turn())[-1]['text'])
        self.assertIn('no longer', (await self.core.agent.turn('missing', 'light'))[-1]['text'])
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_permission_rechecked_after_queue_wait(self):
        for change in ('revoke', 'expiry', 'scopes'):
            with self.subTest(change=change):
                self.setUp()
                lock = self.core.bus.locks['phone']
                await lock.acquire()
                task = asyncio.create_task(self.turn())
                await self.planner.called.wait()
                await asyncio.sleep(0)
                if change == 'revoke': self.core.revoke(self.lease.guest_id)
                elif change == 'expiry': self.clock.now = self.lease.expires_at
                else: self.lease.scopes.clear()
                lock.release()
                result = await task
                self.assertEqual(self.phone.frames, [])
                self.assertFalse(any(frame['type'] == 'action' for frame in result))

    async def test_inflight_ack_is_truthful_after_revoke(self):
        self.phone.auto = False
        task = asyncio.create_task(self.turn())
        await self.phone.sent.wait()
        self.core.revoke(self.lease.guest_id)
        self.core.bus.receive(self.phone.dev, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {'on': True}})
        result = await task
        self.assertEqual(result[-1]['text'], 'phone turned its flashlight on.')
        self.assertEqual(len(self.phone.frames), 1)
        before = len(self.planner.calls)
        self.assertIn('no longer', (await self.turn())[-1]['text'])
        self.assertEqual(len(self.planner.calls), before)

    async def test_offline_requires_explicit_alternative_choice(self):
        self.core.bus.disconnect(self.phone.dev)
        other = register(self.core, 'backup', label='Backup phone')
        result = await self.turn()
        self.assertIn('Which', result[-1]['text'])
        self.assertEqual(other.frames, [])
        self.assertEqual(len(self.planner.calls), 1)
        result = await self.turn('use Backup phone')
        self.assertEqual(result[-1]['text'], 'Backup phone turned its flashlight on.')
        self.assertEqual(len(other.frames), 1)
        self.assertEqual(len(self.planner.calls), 1)

    async def test_ambiguous_alternatives_never_choose_for_guest(self):
        self.core.bus.disconnect(self.phone.dev)
        b, c = register(self.core, 'b'), register(self.core, 'c')
        await self.turn()
        result = await self.turn('yes')
        self.assertIn('choose', result[-1]['text'])
        self.assertEqual(b.frames + c.frames, [])
        await self.turn('b')
        self.assertEqual(len(b.frames), 1)
        self.assertEqual(c.frames, [])

    async def test_expired_alternative_confirmation_does_nothing(self):
        self.core.bus.disconnect(self.phone.dev)
        backup = register(self.core, 'backup')
        await self.turn()
        self.clock.now = self.lease.expires_at
        result = await self.turn('yes')
        self.assertIn('no longer', result[-1]['text'])
        self.assertEqual(backup.frames, [])
        self.assertEqual(len(self.planner.calls), 1)

    async def test_alternative_changed_permission_denied(self):
        self.core.bus.disconnect(self.phone.dev)
        backup = register(self.core, 'backup')
        await self.turn()
        self.lease.scopes.clear()
        result = await self.turn('yes')
        self.assertIn('no longer permitted', result[-1]['text'])
        self.assertEqual(backup.frames, [])

    async def test_offline_alternative_requires_new_choice(self):
        self.core.bus.disconnect(self.phone.dev)
        backup = register(self.core, 'backup')
        await self.turn()
        self.core.bus.disconnect(backup.dev)
        third = register(self.core, 'third')
        result = await self.turn('yes')
        self.assertIn('Which', result[-1]['text'])
        self.assertEqual(third.frames, [])
        await self.turn('yes')
        self.assertEqual(len(third.frames), 1)

    async def test_missing_alternative_does_not_dispatch(self):
        self.core.bus.disconnect(self.phone.dev)
        backup = register(self.core, 'backup')
        await self.turn()
        self.core.registry.devices.pop('backup')
        result = await self.turn('yes')
        self.assertEqual(backup.frames, [])
        self.assertIn('No command', result[-1]['text'])

    async def test_unknown_outcome_has_no_retry_or_fallback(self):
        self.phone.auto = False
        backup = register(self.core, 'backup')
        self.core.agent.action_timeout = .01
        result = await self.turn()
        self.assertIn('unknown', result[-1]['text'])
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(backup.frames, [])
        self.assertEqual(self.core.agent.pending, {})

    async def test_inventory_keeps_offline_labels_but_no_executable_tools(self):
        self.core.bus.disconnect(self.phone.dev)
        self.planner.output = {'kind': 'message', 'text': 'Choose an available device.'}
        await self.turn('what is available')
        inventory = self.planner.calls[0][1]
        self.assertFalse(inventory[0]['online'])
        self.assertEqual(inventory[0]['label'], 'phone')
        self.assertIsNone(inventory[0]['caps'][0]['tool'])

    async def test_named_offline_device_cannot_be_silently_substituted_by_planner(self):
        self.core.bus.disconnect(self.phone.dev)
        backup = register(self.core, 'backup')
        self.planner.output = {'kind': 'action', 'device_id': 'backup', 'cap': 'light', 'args': {'on': True}}
        result = await self.turn('turn on phone')
        self.assertIn('Which', result[-1]['text'])
        self.assertEqual(backup.frames, [])
        await self.turn('yes')
        self.assertEqual(len(backup.frames), 1)

    async def test_named_online_device_mismatch_requires_clarification(self):
        backup = register(self.core, 'backup')
        self.planner.output = {'kind': 'action', 'device_id': 'backup', 'cap': 'light', 'args': {'on': True}}
        result = await self.turn('turn on phone')
        self.assertIn('Please confirm', result[-1]['text'])
        self.assertEqual(self.phone.frames + backup.frames, [])

    async def test_two_named_devices_cannot_trigger_coordinated_action(self):
        backup = register(self.core, 'backup')
        result = await self.turn('turn on phone and backup')
        self.assertIn('one device', result[-1]['text'])
        self.assertEqual(self.phone.frames + backup.frames, [])

    async def test_duplicate_alternative_labels_require_unique_choice(self):
        self.core.bus.disconnect(self.phone.dev)
        b = register(self.core, 'b', label='Backup phone')
        c = register(self.core, 'c', label='Backup phone')
        result = await self.turn()
        self.assertIn('different names', result[-1]['text'])
        self.assertNotIn(self.lease.guest_id, self.core.agent.pending)
        self.assertEqual(b.frames + c.frames, [])
        # Knowing an internal identifier must not bypass ambiguous visible names.
        await self.turn('b')
        self.assertEqual(b.frames + c.frames, [])
        b.dev.label = 'Jay phone'
        c.dev.label = 'Owen phone'
        await self.turn()
        await self.turn('Jay phone')
        self.assertEqual(len(b.frames), 1)
        self.assertEqual(c.frames, [])

    async def test_duplicate_named_labels_fail_closed(self):
        b = register(self.core, 'b', label='Backup phone')
        c = register(self.core, 'c', label='Backup phone')
        self.planner.output = {'kind': 'action', 'device_id': 'c', 'cap': 'light', 'args': {'on': True}}
        result = await self.turn('turn on Backup phone')
        self.assertIn('different names', result[-1]['text'])
        self.assertEqual(b.frames + c.frames, [])

    async def test_unhashable_device_identifier_is_refused(self):
        self.planner.output = {'kind': 'action', 'device_id': [], 'cap': 'light', 'args': {'on': True}}
        result = await self.turn('turn on phone')
        self.assertIn('malformed', result[-1]['text'])
        self.assertEqual(self.phone.frames, [])

    async def test_exact_leave_works_without_planner(self):
        self.core.agent.planner = None
        result = await self.turn('leave')
        self.assertEqual(self.lease.state, 'released')
        self.assertIn('ended', result[-1]['text'])
        self.assertEqual(self.planner.calls, [])

    async def test_device_permission_failure_never_claims_nothing_sent(self):
        self.phone.auto = False
        task = asyncio.create_task(self.turn())
        await self.phone.sent.wait()
        self.core.bus.receive(self.phone.dev, {'type': 'err', 'req': self.phone.frames[0]['req'],
                                             'code': 'PERMISSION', 'message': 'camera permission denied'})
        result = await task
        self.assertEqual(len(self.phone.frames), 1)
        self.assertNotIn('No command was sent', result[-1]['text'])
        self.assertIn('not confirmed', result[-1]['text'])

    async def test_suggestion_cannot_falsely_mark_connected_device_unavailable(self):
        self.planner.output = dict(self.planner.output, kind='suggest')
        result = await self.turn()
        self.assertIn('connected', result[-1]['text'])
        self.assertNotIn('unavailable', result[-1]['text'])
        self.assertEqual(self.phone.frames, [])

    async def test_message_cannot_claim_an_unperformed_action(self):
        self.planner.output = {'kind': 'message', 'text': 'I turned every light on.'}
        result = await self.turn('hello')
        self.assertNotIn('turned every', result[-1]['text'])
        self.assertIn('No device action', result[-1]['text'])
        self.assertEqual(self.phone.frames, [])

    async def test_invalid_untrusted_plans_cannot_dispatch(self):
        plans = [None, [], {'kind': 'action', 'device_id': 'missing', 'cap': 'light', 'args': {'on': True}},
                 {'kind': 'action', 'device_id': 'phone', 'cap': 'light', 'args': {'on': 1}},
                 {'kind': 'action', 'device_id': 'phone', 'cap': 'light', 'args': {'on': True}, 'extra': True},
                 {'kind': 'action', 'device_id': 'phone', 'cap': 'camera.capture', 'args': {}},
                 {'kind': 'actions', 'actions': []}, {'kind': 'message', 'text': 12}]
        for plan in plans:
            with self.subTest(plan=plan):
                self.planner.output = plan
                result = await self.turn()
                self.assertFalse(any(f['type'] == 'action' for f in result))
        self.assertEqual(self.phone.frames, [])

    async def test_same_guest_turns_are_serialized(self):
        self.phone.auto = False
        first = asyncio.create_task(self.turn())
        await self.phone.sent.wait()
        second = asyncio.create_task(self.turn())
        await asyncio.sleep(.005)
        self.assertEqual(len(self.planner.calls), 1)
        self.core.bus.receive(self.phone.dev, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {}})
        await first
        await asyncio.sleep(.005)
        self.assertEqual(len(self.planner.calls), 2)
        self.core.bus.receive(self.phone.dev, {'type': 'ok', 'req': self.phone.frames[1]['req'], 'result': {}})
        await second

    async def test_reset_preserves_enrollment_and_blocks_queued_action(self):
        lock = self.core.bus.locks['phone']
        await lock.acquire()
        queued = asyncio.create_task(self.turn())
        await self.planner.called.wait()
        await asyncio.sleep(0)
        first = await self.core.reset()
        code = self.core.registry.room.code
        self.assertNotEqual(code, 'TEST')
        self.assertEqual(first['cleanup'], 'not_configured')
        self.assertIs(self.core.registry.devices['phone'], self.phone.dev)
        self.assertIn(self.phone.dev, self.core.registry.online_in(self.core.registry.room))
        second_lease = self.core.leases.create()
        second = await self.core.reset()
        self.assertNotEqual(second['room_code'], code)
        self.assertEqual(second_lease.state, 'released')
        lock.release()
        result = await queued
        self.assertIn('no longer', result[-1]['text'])
        self.assertEqual(self.phone.frames, [])
        self.core.bus.disconnect(self.phone.dev)
        new_socket = Socket(self.core.bus)
        reconnected = self.core.registry.register(hello(room='TEST'), new_socket)
        self.assertEqual(reconnected.room_id, self.core.registry.room.id)
        with self.assertRaises(ValueError):
            self.core.registry.register(hello('unknown', room='TEST'), Socket(self.core.bus))

    async def test_reconnect_canonical_alias_survives_a_later_reset(self):
        await self.core.reset()
        canonical = self.core.registry.room.code
        self.core.bus.disconnect(self.phone.dev)
        reconnect = self.core.registry.register(hello(room='TEST'), Socket(self.core.bus))
        self.assertEqual(reconnect.room_code, canonical)
        await self.core.reset()
        self.core.bus.disconnect(reconnect)
        latest = self.core.registry.register(hello(room=canonical), Socket(self.core.bus))
        self.assertEqual(latest.room_id, self.core.registry.room.id)
        self.assertEqual(latest.room_code, self.core.registry.room.code)

    async def test_reset_cleanup_reports_only_explicit_confirmation(self):
        seen = []
        async def cleanup(core):
            seen.append(self.lease.state)
            return False
        self.core.cleanup_hook = cleanup
        result = await self.core.reset()
        self.assertEqual(seen, ['released'])
        self.assertEqual(result['cleanup'], 'unconfirmed')

    async def test_expired_sessions_and_credentials_retained_only_through_cookie_lifetime(self):
        secret = self.core.issue_credential(self.lease.guest_id)
        self.core.revoke(self.lease.guest_id)
        cookies = {self.core.cookie_name(self.lease.guest_id): secret}
        self.assertTrue(self.core.authentic_guest(self.lease.guest_id, cookies))
        self.clock.now = self.lease.expires_at + 120
        self.core.sweep()
        self.assertNotIn(self.lease.guest_id, self.core.leases.sessions)
        self.assertNotIn(self.lease.guest_id, self.core.credentials)
        self.assertFalse(self.core.authentic_guest(self.lease.guest_id, cookies))

    async def test_leave_preserves_effects(self):
        await self.turn()
        self.planner.output = {'kind': 'leave'}
        frames = await self.turn('leave')
        self.assertEqual(self.lease.state, 'released')
        self.assertEqual(len(self.phone.frames), 1)
        self.assertIn('stay as set', frames[-1]['text'])

    async def test_no_cross_room_authority(self):
        self.phone.dev.room_id = 'another-room'
        result = await self.turn()
        self.assertIn('not permitted', result[-1]['text'])
        self.assertEqual(self.phone.frames, [])


class AccessEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.planner = Planner({'kind': 'message', 'text': 'What would you like?'})
        self.app, self.core = make_app(planner=self.planner, clock=self.clock)
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN))
        self.tokens = {}

    def join(self, client=None):
        response = (client or self.client).post('/join', json={'room_code': 'TEST'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.tokens[response.json()['guest_id']] = response.json()['guest_token']
        return response

    def guest_url(self, guest_id):
        return 'wss://testserver/ws/guest?guest_id=' + guest_id + '&token=' + self.tokens[guest_id]

    def assert_lease_frame(self, frame, state=None):
        self.assertEqual(frame.get('type'), 'lease')
        self.assertIn(frame.get('state'), ('joining', 'active', 'released'))
        expected = {'type', 'state', 'expires_in', 'access_expires_in', 'controls'}
        if frame['state'] == 'released':
            expected.add('reason')
        self.assertEqual(set(frame), expected)
        if state:
            self.assertEqual(frame['state'], state)

    def receive_conversation(self, ws):
        # Metadata may update while a turn runs. Never discard action/assistant
        # frames or any other unexpected conversation-frame type.
        while True:
            frame = ws.receive_json()
            if frame.get('type') != 'lease':
                return frame
            self.assert_lease_frame(frame)

    def test_join_private_cookie_separate_from_public_id(self):
        response = self.join()
        body = response.json()
        self.assertEqual(set(body), {'guest_id', 'guest_token', 'chat_url'})
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertIn('Secure', cookie)
        secret = response.cookies.get(self.core.cookie_name(body['guest_id']))
        self.assertNotEqual(secret, body['guest_id'])
        self.assertNotIn(secret, json.dumps(self.core.snapshot()))
        self.assertNotIn('device-private', json.dumps(self.core.snapshot()))
        self.assertNotIn('host-private', json.dumps(self.core.snapshot()))

    def test_guest_public_id_alone_missing_cookie_and_wrong_origin_denied(self):
        guest_id = self.join().json()['guest_id']
        with TestClient(self.app, base_url=ORIGIN) as other:
            for headers in (HEADERS, {}, {'Origin': 'https://evil.example'}):
                with self.assertRaises(WebSocketDisconnect):
                    with other.websocket_connect('wss://testserver/ws/guest?guest_id=' + guest_id, headers=headers): pass
        for headers in ({}, {'Origin': 'https://evil.example'}, {'Origin': 'null'}):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect('wss://testserver/ws/guest?guest_id=' + guest_id, headers=headers): pass
        self.assertEqual(self.planner.calls, [])

    def test_explicit_websocket_token_required_even_with_valid_cookie(self):
        response = self.join()
        guest_id = response.json()['guest_id']
        for suffix in ('', '&token=wrong'):
            with self.assertRaises(WebSocketDisconnect) as caught:
                with self.client.websocket_connect('wss://testserver/ws/guest?guest_id=' + guest_id + suffix, headers=HEADERS):
                    pass
            self.assertEqual(caught.exception.code, 4401)
        with TestClient(self.app, base_url=ORIGIN) as no_cookies:
            with no_cookies.websocket_connect(self.guest_url(guest_id), headers=HEADERS) as ws:
                self.assert_lease_frame(ws.receive_json(), 'joining')
                ws.send_json({'type': 'user', 'text': 'what can you do'})
                self.assertEqual(self.receive_conversation(ws)['type'], 'assistant')
        self.assertEqual(len(self.planner.calls), 1)

    def test_other_guests_private_token_cannot_impersonate(self):
        first = self.join().json()
        second = self.join().json()
        target = 'wss://testserver/ws/guest?guest_id=' + first['guest_id'] + '&token=' + second['guest_token']
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect(target, headers=HEADERS):
                pass
        self.assertEqual(caught.exception.code, 4401)
        self.assertEqual(self.planner.calls, [])

    def test_other_guest_cookie_cannot_impersonate(self):
        first_id = self.join().json()['guest_id']
        with TestClient(self.app, base_url=ORIGIN) as other:
            second_id = self.join(other).json()['guest_id']
            self.assertNotEqual(first_id, second_id)
            with self.assertRaises(WebSocketDisconnect):
                with other.websocket_connect('wss://testserver/ws/guest?guest_id=' + first_id, headers=HEADERS): pass
            response = other.post('/leave', json={'guest_id': first_id}, headers=HEADERS)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.core.leases.leases[first_id].state, 'joining')

    def test_webchat_activation_then_expiry_denies_without_planner(self):
        guest_id = self.join().json()['guest_id']
        with self.client.websocket_connect(self.guest_url(guest_id), headers=HEADERS) as ws:
            self.assert_lease_frame(ws.receive_json(), 'joining')
            ws.send_json({'type': 'user', 'text': 'hello'})
            self.assertEqual(self.receive_conversation(ws)['type'], 'assistant')
            self.assertEqual(self.core.leases.leases[guest_id].state, 'active')
            self.clock.now += 600
            ws.send_json({'type': 'user', 'text': 'turn on phone'})
            self.assertIn('no longer', self.receive_conversation(ws)['text'])
            self.assertEqual(len(self.planner.calls), 1)

    def test_leave_needs_cookie_and_origin(self):
        guest_id = self.join().json()['guest_id']
        self.assertEqual(self.client.post('/leave', json={'guest_id': guest_id}).status_code, 403)
        self.assertEqual(self.client.post('/leave', json={'guest_id': guest_id}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/leave', json={'guest_id': guest_id}, headers=HEADERS).status_code, 200)
        with self.client.websocket_connect(self.guest_url(guest_id), headers=HEADERS) as ws:
            self.assert_lease_frame(ws.receive_json(), 'released')
            ws.send_json({'type': 'user', 'text': 'light'})
            self.assertIn('no longer', self.receive_conversation(ws)['text'])
        self.assertEqual(self.planner.calls, [])

    def test_origin_and_invitation_validation(self):
        for headers in ({}, {'Origin': 'https://evil.example'}, {'Origin': ORIGIN + '/fake'}):
            self.assertEqual(self.client.post('/join', json={'room_code': 'TEST'}, headers=headers).status_code, 403)
        self.assertEqual(self.client.post('/join', json={'room_code': 'wrong'}, headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.post('/join', json=[], headers=HEADERS).status_code, 400)
        self.assertEqual(self.client.post('/join', json={'room_code': 'TEST', 'phone': '+15550000000'}, headers=HEADERS).status_code, 503)

    def test_two_resets_invalidate_old_invites_and_old_guest(self):
        guest_id = self.join().json()['guest_id']
        first = self.client.post('/host/reset', headers=HOST_HEADERS).json()
        self.assertNotEqual(first['room_code'], 'TEST')
        second = self.client.post('/host/reset', headers=HOST_HEADERS).json()
        self.assertNotEqual(second['room_code'], first['room_code'])
        for code in ('TEST', first['room_code']):
            self.assertEqual(self.client.post('/join', json={'room_code': code}, headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.post('/join', json={'room_code': second['room_code']}, headers=HEADERS).status_code, 200)
        with self.client.websocket_connect(self.guest_url(guest_id), headers=HEADERS) as ws:
            self.assert_lease_frame(ws.receive_json(), 'released')
            ws.send_json({'type': 'user', 'text': 'hello'})
            self.assertIn('no longer', self.receive_conversation(ws)['text'])
        self.assertEqual(self.planner.calls, [])

    def test_host_actions_require_token_and_public_display_schema(self):
        guest_id = self.join().json()['guest_id']
        for route in ('/host/reset', '/host/revoke', '/host/do'):
            self.assertEqual(self.client.post(route, json={'guest_id': guest_id}).status_code, 403)
        snapshot = self.core.snapshot()
        self.assertEqual(set(snapshot), {'type', 'room', 'devices', 'guests', 'log'})
        self.assertEqual(set(snapshot['room']), {'code', 'label', 'join_url'})
        self.assertEqual(set(snapshot['guests'][0]), {'guest_id', 'display_name', 'channel', 'expires_in', 'scopes',
                                                    'lease_total', 'transcript'})
        with self.client.websocket_connect('wss://testserver/ws/display', headers=HEADERS) as ws:
            self.assertEqual(ws.receive_json()['type'], 'state')
            ws.send_json({'type': 'host.revoke', 'guest_id': guest_id, 'token': 'wrong'})
            # HTTP round trip synchronizes the TestClient without a sleep.
            self.client.get('/missing')
            self.assertEqual(self.core.leases.leases[guest_id].state, 'joining')
            ws.send_json({'type': 'host.revoke', 'guest_id': guest_id, 'token': 'host-private'})
            frame = ws.receive_json()
            self.assertEqual(frame['guests'], [])
        self.assertEqual(self.core.leases.leases[guest_id].state, 'released')

    def test_revoke_endpoint_then_deterministic_denial(self):
        guest_id = self.join().json()['guest_id']
        response = self.client.post('/host/revoke', json={'guest_id': guest_id}, headers=HOST_HEADERS)
        self.assertTrue(response.json()['revoked'])
        with self.client.websocket_connect(self.guest_url(guest_id), headers=HEADERS) as ws:
            self.assert_lease_frame(ws.receive_json(), 'released')
            ws.send_json({'type': 'user', 'text': 'light'})
            self.assertIn('no longer', self.receive_conversation(ws)['text'])
        self.assertEqual(self.planner.calls, [])

    def test_log_persistence_redacts_secrets_and_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            app, core = make_app(planner=self.planner, log_path=Path(directory) / 'events.jsonl')
            with TestClient(app, base_url=ORIGIN) as client:
                response = client.post('/join', json={'room_code': 'TEST'}, headers=HEADERS)
                guest_id = response.json()['guest_id']
                secret = response.cookies.get(core.cookie_name(guest_id))
                with client.websocket_connect('wss://testserver/ws/guest?guest_id=' + guest_id + '&token=' + response.json()['guest_token'], headers=HEADERS) as ws:
                    self.assert_lease_frame(ws.receive_json(), 'joining')
                    ws.send_json({'type': 'user', 'text': 'my private sentence'})
                    self.assertEqual(self.receive_conversation(ws)['type'], 'assistant')
            text = (Path(directory) / 'events.jsonl').read_text()
            for value in (secret, 'my private sentence', 'host-private', 'device-private'):
                self.assertNotIn(value, text)
            self.assertEqual(json.loads(text.splitlines()[0])['kind'], 'guest.join')


if __name__ == '__main__':
    unittest.main()
