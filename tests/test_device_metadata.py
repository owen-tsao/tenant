"""Device metadata evidence/persistence tests; fake sockets, no live devices or OS effects."""
import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.api.device_metadata import router
from brain.core.device_metadata import MAX_AGE, update_metadata
from brain.core.persistence import RoomStateError, RoomStateStore
from brain.core.retirement import retire_devices
from brain.ws.devices import device_socket
from test_access_core import Clock, Socket, hello, make_app


HOST = {'Authorization': 'Bearer host-private'}


class DeviceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'room.json'
        self.store = RoomStateStore(self.path)
        self.registry = self.store.load_registry('TEST')
        self.app, self.core = make_app(registry=self.registry)
        if not any(getattr(route, 'path', None) == '/host/devices/{device_id}/metadata'
                   for route in self.app.routes):
            self.app.include_router(router)
        @self.app.websocket('/ws/device')
        async def devices(ws: WebSocket):
            await device_socket(ws, self.core.config, self.registry, self.core.bus)
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.wall, self.mono = Clock(), Clock()
        self.registry.metadata.clock = self.wall
        self.registry.metadata.monotonic = self.mono
        self.socket = self.enroll()

    def enroll(self, device_id='mac', *, label='Mac adapter', caps=None, room=None):
        frame = hello(device_id, cap='say', room=room or self.registry.room.code, label=label)
        if caps is not None:
            frame['caps'] = caps
        socket = Socket(self.core.bus)
        socket.dev = self.registry.register(frame, socket)
        socket.dev.last_seen = self.mono.now
        return socket

    def update(self, body, *, device_id='mac', headers=HOST):
        return self.client.patch('/host/devices/' + device_id + '/metadata', headers=headers, json=body)

    def row(self, device_id='mac'):
        return next(row for row in self.registry.metadata.public_devices() if row['id'] == device_id)

    def test_host_metadata_requires_host_authorization_and_known_enrollment(self):
        before = self.path.read_bytes()
        for headers in ({}, {'Authorization': 'Bearer wrong'},
                        {'Authorization': 'Bearer device-private'},
                        {'Origin': 'https://testserver', 'X-Host-Token': 'host-private'}):
            self.assertEqual(self.update({'label': 'Denied'}, headers=headers).status_code, 403)
        self.assertEqual(self.update({'label': 'Unknown'}, device_id='not-enrolled').status_code, 404)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.socket.frames, [])

    def test_unauthenticated_device_socket_cannot_create_metadata_identity(self):
        for token in ('', 'wrong'):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect('/ws/device?t=' + token) as socket:
                    socket.send_json(hello('intruder', cap='say'))
        self.assertNotIn('intruder', self.registry.enrollments)
        self.assertNotIn('intruder', self.registry.metadata.records)
        with self.client.websocket_connect('/ws/device?t=device-private') as socket:
            socket.send_json(hello('authenticated', cap='say'))
            self.assertEqual(socket.receive_json()['type'], 'welcome')
            self.assertEqual(self.row('authenticated')['provenance']['identity']['source'],
                             'authenticated_enrollment')

    def test_host_facts_survive_reconnect_changed_hello_reset_and_restart(self):
        facts = {'label': '  Host Mac  ', 'role': 'audio_host', 'location': 'Desk',
                 'output_description': 'Current Mac output', 'allowed': False}
        self.assertEqual(self.update(facts).status_code, 200)
        old_room, old_code = self.registry.room.id, self.registry.room.code
        self.registry.offline(self.socket.dev)
        asyncio.run(self.core.reset())
        replacement = self.enroll(label='Changed adapter', room=old_code)
        self.assertIsNot(replacement.dev, self.socket.dev)
        self.assertEqual(replacement.dev.room_id, old_room)
        self.assertEqual(replacement.dev.label, 'Host Mac')
        self.assertEqual(self.registry.metadata.records['mac']['adapter_label']['value'], 'Changed adapter')
        restored = self.store.load_registry('IGNORED')
        self.assertEqual(restored.room.id, old_room)
        self.assertEqual(restored.devices, {})
        row = restored.metadata.public_devices()[0]
        for field, value in facts.items():
            self.assertEqual(row[field], value.strip() if isinstance(value, str) else value)
            self.assertEqual(row['provenance'][field], {'source': 'host_specified', 'at': self.wall.now})
        self.assertEqual(row['connection_state'], 'unknown')
        self.assertEqual(row['caps'], [])
        self.assertEqual(row['capability_status'], [])
        self.assertIsNone(restored.metadata.binding('mac'))
        self.assertEqual(restored.metadata.role_devices('audio_host'), ())
        _, restored_core = make_app(registry=restored)
        resumed = restored.register(hello('mac', cap='light', room=old_code, label='Restarted adapter'),
                                    Socket(restored_core.bus))
        self.assertEqual(resumed.room_id, old_room)
        self.assertEqual(resumed.label, 'Host Mac')
        self.assertEqual(set(resumed.caps), {'light'})
        self.assertEqual(restored.metadata.value('mac', 'role'), 'audio_host')
        self.assertFalse(restored.metadata.available(resumed, 'light'))

    def test_adapter_caps_never_invent_peripheral_identity_or_role(self):
        self.registry.offline(self.socket.dev)
        caps = {name: {'args': {}, 'description': 'Adapter tool'}
                for name in ('say', 'music.play', 'projector.power', 'speaker.output', 'camera.capture')}
        self.enroll(caps=caps)
        rows = self.registry.metadata.public_devices()
        self.assertEqual([row['id'] for row in rows], ['mac'])
        self.assertEqual(set(self.registry.enrollments), {'mac'})
        self.assertIsNone(rows[0]['role'])
        self.assertIsNone(rows[0]['location'])
        self.assertIsNone(rows[0]['output_description'])
        self.assertEqual(rows[0]['provenance']['role'], {'source': 'unknown'})
        self.assertEqual(self.registry.metadata.role_devices('speaker'), ())
        self.assertEqual(self.registry.metadata.role_devices('projector'), ())

    def test_duplicate_host_labels_remain_distinct_enrolled_ids(self):
        self.enroll('phone')
        for device_id in ('mac', 'phone'):
            self.assertEqual(self.update({'label': 'Same', 'role': 'light'}, device_id=device_id).status_code, 200)
        rows = self.registry.metadata.public_devices()
        self.assertEqual({row['id'] for row in rows}, {'mac', 'phone'})
        self.assertEqual([row['label'] for row in rows], ['Same', 'Same'])
        self.assertEqual({item['device_id'] for item in self.registry.metadata.role_devices('light')}, {'mac', 'phone'})

    def test_role_lookup_is_detached_revisioned_and_binding_is_exact_current_object(self):
        self.update({'role': 'audio_host'})
        matches = self.registry.metadata.role_devices('audio_host')
        self.assertIsInstance(matches, tuple)
        self.assertEqual(matches, ({'device_id': 'mac', 'metadata_revision': 1},))
        self.assertIs(self.registry.metadata.binding('mac'), self.socket.dev)
        matches[0]['device_id'] = 'forged'
        self.assertEqual(self.registry.metadata.role_devices('audio_host')[0]['device_id'], 'mac')
        old = self.socket.dev
        self.registry.offline(old)
        new = self.enroll()
        self.assertIs(self.registry.metadata.binding('mac'), new.dev)
        self.assertFalse(self.registry.metadata.available(old, 'say'))
        self.assertTrue(self.registry.metadata.available(new.dev, 'say'))
        self.update({'location': 'Shelf'})
        self.assertEqual(self.registry.metadata.role_devices('audio_host')[0]['metadata_revision'], 2)

    def test_heartbeat_boundary_and_future_timestamp_are_not_live(self):
        dev = self.socket.dev
        self.mono.now = dev.last_seen + MAX_AGE - .001
        self.assertIs(self.registry.metadata.binding('mac'), dev)
        self.mono.now = dev.last_seen + MAX_AGE
        self.assertIsNone(self.registry.metadata.binding('mac'))
        self.assertFalse(self.row()['online'])
        self.assertEqual(self.row()['caps'], [])
        self.assertIn('heartbeat', self.row()['capability_status'][0]['reason'])
        self.mono.now = dev.last_seen - .001
        self.assertIsNone(self.registry.metadata.binding('mac'))
        dev.last_seen = self.mono.now
        self.assertTrue(self.registry.metadata.available(dev, 'say'))

    def test_foreign_room_offline_unenrolled_and_unhealthy_bindings_fail_closed(self):
        dev = self.socket.dev
        self.update({'role': 'audio_host'})
        dev.room_id = 'foreign'
        self.assertEqual(self.registry.metadata.public_devices(), [])
        self.assertIsNone(self.registry.metadata.binding('mac'))
        dev.room_id = self.registry.room.id
        dev.online = False
        self.assertEqual(self.row()['connection_state'], 'offline')
        self.assertFalse(self.registry.metadata.available(dev, 'say'))
        dev.online = True
        self.registry.persistence_healthy = False
        self.assertIsNone(self.registry.metadata.binding('mac'))
        self.assertEqual(self.registry.metadata.role_devices('audio_host'), ())
        self.assertIn('storage', self.row()['capability_status'][0]['reason'])
        self.assertEqual(self.update({'location': 'No bypass'}).status_code, 503)
        self.registry.persistence_healthy = True
        self.registry.enrollments.pop('mac')
        self.assertFalse(self.registry.metadata.available(dev, 'say'))
        self.assertEqual(self.registry.metadata.public_devices(), [])

    def test_host_disabled_blocks_capability_and_role_resolution_without_disconnect(self):
        self.update({'role': 'audio_host', 'allowed': False})
        self.assertIs(self.registry.metadata.binding('mac'), self.socket.dev)
        row = self.row()
        self.assertTrue(row['online'])
        self.assertEqual(row['caps'], [])
        self.assertEqual(self.registry.metadata.role_devices('audio_host'), ())
        self.assertIn('disabled', row['capability_status'][0]['reason'])
        self.update({'allowed': True})
        self.assertEqual(self.row()['caps'], ['say'])
        self.assertEqual(len(self.registry.metadata.role_devices('audio_host')), 1)
        self.assertEqual(self.socket.frames, [])

    def test_camera_role_does_not_supply_camera_consent_or_advertise_availability(self):
        self.registry.offline(self.socket.dev)
        socket = self.enroll(caps={'camera.capture': {'args': {}, 'description': 'Capture'}})
        self.update({'role': 'camera', 'allowed': True})
        self.assertEqual(len(self.registry.metadata.role_devices('camera')), 1)
        self.assertFalse(self.registry.metadata.available(socket.dev, 'camera.capture'))
        status = self.row()['capability_status'][0]
        self.assertEqual(status['status'], 'blocked')
        self.assertIn('consent', status['reason'])
        self.assertEqual(self.row()['caps'], [])
        self.assertFalse(self.registry.metadata.available(socket.dev, 'say'))
        self.assertEqual(socket.frames, [])

    def test_host_role_and_allowed_metadata_never_grant_guest_scope(self):
        lease = self.core.leases.create(scopes={'light'})
        self.core.leases.current(lease.guest_id, activate=True)
        expires, scopes, epoch = lease.expires_at, set(lease.scopes), self.registry.room.epoch
        self.update({'role': 'speaker', 'allowed': True})
        self.assertTrue(self.registry.metadata.available(self.socket.dev, 'say'))
        self.assertFalse(self.core.leases.allows(lease, self.socket.dev, 'say'))
        self.assertEqual((lease.expires_at, lease.scopes, self.registry.room.epoch), (expires, scopes, epoch))
        result = asyncio.run(self.core.agent.execute_plan(lease, {
            'kind': 'action', 'device_id': 'mac', 'cap': 'say', 'args': {'text': 'Denied'}}))
        self.assertIn('not permitted', result[-1]['text'])
        self.assertEqual(self.socket.frames, [])
        self.assertEqual(self.core.credentials, {})

    def test_strict_host_update_values_and_private_literals_never_mutate(self):
        self.core.agent.private_values = ('provider-private',)
        before = self.path.read_bytes()
        records = copy.deepcopy(self.registry.metadata.records)
        invalid = [{}, [], None, {'unknown': 'field'}, {'allowed': 1}, {'allowed': None},
                   {'label': None}, {'label': ''}, {'label': '   '}, {'role': True},
                   {'location': 3}, {'role': 'x' * 129}, {'label': 'a\nb'}, {'role': 'a\tb'},
                   {'output_description': 'null\x00value'}, {'label': 'a\x7fb'},
                   {'label': 'host-private'}, {'role': 'device-private'},
                   {'output_description': 'prefix provider-private suffix'}]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.update(body).status_code, 400)
        response = self.client.patch('/host/devices/mac/metadata', headers=HOST, content='{')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.registry.metadata.records, records)

    def test_nullable_host_assertions_and_timestamp_provenance_are_explicit(self):
        self.update({'role': 'speaker', 'location': 'Desk', 'output_description': 'Mac audio'})
        self.wall.now += 7
        result = self.update({'role': None, 'location': None, 'output_description': None})
        self.assertEqual(result.status_code, 200)
        row = result.json()['device']
        self.assertEqual(row['metadata_revision'], 2)
        for field in ('role', 'location', 'output_description'):
            self.assertIsNone(row[field])
            self.assertEqual(row['provenance'][field], {'source': 'host_specified', 'at': self.wall.now})
        self.assertEqual(row['provenance']['label']['source'], 'adapter_reported')
        self.assertEqual(row['provenance']['allowed']['source'], 'existing_enrollment_policy')

    def test_public_projection_export_and_http_result_are_detached_and_bounded_to_safe_fields(self):
        self.update({'role': 'audio_host', 'output_description': 'Mac current output'})
        self.socket.dev.caps['say'].description = 'provider-resource credential-private'
        self.socket.dev.caps['say'].args['text']['private_schema'] = 'raw-schema-private'
        rows = self.registry.metadata.public_devices()
        payload = json.dumps(rows)
        for forbidden in ('host-private', 'device-private', 'provider-resource', 'raw-schema-private',
                          'credential-private', 'schema', '"description"', '"ws"', 'room_code'):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(set(rows[0]), {'id', 'label', 'caps', 'online', 'busy', 'connection_state',
            'role', 'location', 'output_description', 'allowed', 'metadata_revision', 'provenance', 'capability_status'})
        rows[0]['caps'].clear()
        rows[0]['provenance']['role']['source'] = 'forged'
        rows[0]['capability_status'][0]['status'] = 'forged'
        exported = self.registry.metadata.export()
        exported['mac']['host']['role']['value'] = 'forged'
        self.assertEqual(self.row()['caps'], ['say'])
        self.assertEqual(self.row()['provenance']['role']['source'], 'host_specified')
        self.assertEqual(self.registry.metadata.value('mac', 'role'), 'audio_host')
        self.assertEqual(self.row()['capability_status'][0]['status'], 'available')
        response = update_metadata(self.core, 'mac', {'location': 'Desk'})
        response['device']['provenance']['location']['source'] = 'forged'
        response['device']['caps'].clear()
        self.assertEqual(self.row()['caps'], ['say'])
        self.assertEqual(self.row()['provenance']['location']['source'], 'host_specified')

    def test_pre_replace_failure_rolls_back_host_record_label_and_durable_bytes(self):
        self.update({'label': 'Saved', 'role': 'audio_host'})
        before_bytes, before_record = self.path.read_bytes(), copy.deepcopy(self.registry.metadata.records)
        with patch('brain.core.persistence.os.replace', side_effect=OSError('write failed')):
            result = self.update({'label': 'Unsaved', 'allowed': False})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.registry.metadata.records, before_record)
        self.assertEqual(self.socket.dev.label, 'Saved')
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertFalse(self.registry.persistence_healthy)
        self.assertEqual(self.row()['caps'], [])
        self.assertEqual(list(self.path.parent.glob('.room.json-*')), [])

    def test_post_replace_metadata_failure_does_not_claim_durable_rollback_or_allow_control(self):
        self.update({'label': 'Old'})
        old_record = copy.deepcopy(self.registry.metadata.records)
        real_fsync, calls = os.fsync, []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('directory sync unconfirmed')
            return real_fsync(fd)
        with patch('brain.core.persistence.os.fsync', side_effect=fail_directory):
            result = self.update({'label': 'Possibly durable'})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.registry.metadata.records, old_record)
        self.assertEqual(self.socket.dev.label, 'Old')
        self.assertEqual(json.loads(self.path.read_text())['device_metadata']['mac']['host']['label']['value'],
                         'Possibly durable')
        self.assertFalse(self.registry.persistence_healthy)
        self.assertIsNone(self.registry.metadata.binding('mac'))
        self.assertEqual(self.update({'allowed': True}).status_code, 503)

    def test_registration_failure_rolls_back_aliases_metadata_observation_and_connection(self):
        self.update({'label': 'Saved host'})
        self.registry.offline(self.socket.dev)
        asyncio.run(self.core.reset())
        before = (copy.deepcopy(self.registry.enrollments), copy.deepcopy(self.registry.metadata.records),
                  copy.deepcopy(self.registry.metadata.observed_at), self.path.read_bytes())
        self.wall.now += 8
        with patch('brain.core.persistence.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(ValueError):
                self.enroll(label='Unconfirmed adapter')
        self.assertEqual(self.registry.enrollments, before[0])
        self.assertEqual(self.registry.metadata.records, before[1])
        self.assertEqual(self.registry.metadata.observed_at, before[2])
        self.assertEqual(self.path.read_bytes(), before[3])
        self.assertIs(self.registry.devices['mac'], self.socket.dev)
        self.assertFalse(self.registry.persistence_healthy)

    def test_new_enrollment_post_replace_failure_has_no_live_or_inmemory_phantom(self):
        real_fsync, count = os.fsync, [0]
        def fail_directory(fd):
            count[0] += 1
            if count[0] == 2:
                raise OSError('ambiguous replace')
            return real_fsync(fd)
        with patch('brain.core.persistence.os.fsync', side_effect=fail_directory):
            with self.assertRaises(ValueError):
                self.enroll('new-device')
        for mapping in (self.registry.enrollments, self.registry.devices,
                        self.registry.metadata.records, self.registry.metadata.observed_at):
            self.assertNotIn('new-device', mapping)
        self.assertIn('new-device', json.loads(self.path.read_text())['enrollments'])
        self.assertFalse(self.registry.persistence_healthy)
        self.assertEqual(self.row()['caps'], [])

    def test_v1_migration_preserves_identity_and_never_restores_live_capabilities(self):
        data = json.loads(self.path.read_text())
        data['version'] = 1
        data.pop('device_metadata')
        self.path.write_text(json.dumps(data))
        restored = self.store.load_registry('IGNORED')
        self.assertEqual(restored.room.id, self.registry.room.id)
        self.assertEqual(restored.enrollments, self.registry.enrollments)
        self.assertEqual(restored.devices, {})
        self.assertEqual(restored.metadata.records, {})
        row = restored.metadata.public_devices()[0]
        self.assertEqual(row['label'], 'Enrolled device')
        self.assertIsNone(row['role'])
        self.assertEqual(row['caps'], [])
        self.assertEqual(json.loads(self.path.read_text())['version'], 2)
        app, core = make_app(registry=restored)
        update_metadata(core, 'mac', {'role': 'audio_host'})
        again = self.store.load_registry('IGNORED')
        self.assertEqual(again.metadata.value('mac', 'role'), 'audio_host')
        self.assertEqual(again.metadata.public_devices()[0]['caps'], [])

    def test_v2_metadata_corruption_refuses_load_without_overwriting_evidence(self):
        valid = json.loads(self.path.read_text())
        mutations = [
            lambda d: d['device_metadata'].update({'unknown': copy.deepcopy(d['device_metadata']['mac'])}),
            lambda d: d['device_metadata']['mac'].update({'extra': 'field'}),
            lambda d: d['device_metadata']['mac'].update({'revision': True}),
            lambda d: d['device_metadata']['mac'].update({'revision': -1}),
            lambda d: d['device_metadata']['mac'].update({'revision': 2**63}),
            lambda d: d['device_metadata']['mac'].update({'adapter_label': {'value': 'Mac', 'at': float('nan')}}),
            lambda d: d['device_metadata']['mac'].update({'adapter_label': {'value': '', 'at': 1}}),
            lambda d: d['device_metadata']['mac']['host'].update({'ws': {'value': 'private', 'at': 1}}),
            lambda d: d['device_metadata']['mac']['host'].update({'allowed': {'value': 1, 'at': 1}}),
            lambda d: d['device_metadata']['mac']['host'].update({'role': {'value': 'camera', 'at': -1}}),
            lambda d: d['device_metadata']['mac']['host'].update({'location': {'value': 'two\nlines', 'at': 1}}),
            lambda d: d['device_metadata']['mac']['host'].update({'label': {'value': None, 'at': 1}}),
            lambda d: d['device_metadata']['mac']['host'].update({'role': {'value': 'camera', 'at': 1, 'extra': 2}}),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(case=number):
                data = copy.deepcopy(valid)
                mutate(data)
                content = json.dumps(data)
                self.path.write_text(content)
                with self.assertRaises(RoomStateError):
                    self.store.load_registry('TEST')
                self.assertEqual(self.path.read_text(), content)

    def test_retired_metadata_never_resurfaces_when_same_id_enrolls_again(self):
        self.update({'label': 'Old host name', 'role': 'audio_host', 'location': 'Old room', 'allowed': False})
        self.registry.offline(self.socket.dev)
        result = retire_devices(self.core, {'device_ids': ['mac'], 'reason': 'Local test retirement',
                                           'physical_off_confirmed': True})
        self.assertEqual(result['retired'], ['mac'])
        self.assertNotIn('mac', self.registry.metadata.records)
        self.assertNotIn('mac', self.registry.metadata.observed_at)
        self.assertEqual(self.registry.metadata.public_devices(), [])
        self.assertEqual(json.loads(self.path.read_text())['device_metadata'], {})
        socket = self.enroll(label='Fresh adapter')
        row = self.row()
        self.assertEqual(row['label'], 'Fresh adapter')
        self.assertIsNone(row['role'])
        self.assertIsNone(row['location'])
        self.assertTrue(row['allowed'])
        self.assertEqual(row['metadata_revision'], 0)
        self.assertIs(self.registry.metadata.binding('mac'), socket.dev)


    def test_postreplace_host_denial_stays_sticky_until_trusted_reload(self):
        lease = self.core.leases.create(scopes={'say'})
        self.core.leases.current(lease.guest_id, activate=True)
        self.assertTrue(self.registry.metadata.value('mac', 'allowed', True))
        real_fsync, count = os.fsync, [0]
        def fail_directory(fd):
            count[0] += 1
            if count[0] == 2:
                raise OSError('denial directory sync unconfirmed')
            return real_fsync(fd)
        with patch('brain.core.persistence.os.fsync', side_effect=fail_directory):
            response = self.update({'allowed': False})
        self.assertEqual(response.status_code, 503)
        self.assertTrue(self.registry.metadata.value('mac', 'allowed', True))
        ambiguous_disk = self.path.read_bytes()
        self.assertFalse(json.loads(ambiguous_disk)['device_metadata']['mac']['host']['allowed']['value'])
        self.assertFalse(self.registry.persistence_healthy)
        self.assertIsNone(self.core.leases.current(lease.guest_id))
        writes = []
        self.registry.on_change = lambda _: writes.append('untrusted overwrite')
        self.assertFalse(self.registry.persist())
        with self.assertRaises(ValueError):
            self.enroll('unrelated')
        self.registry.offline(self.socket.dev)
        with self.assertRaises(ValueError):
            self.enroll(label='Untrusted reconnect')
        self.assertEqual(writes, [])
        self.assertEqual(self.path.read_bytes(), ambiguous_disk)
        self.assertFalse(self.registry.persistence_healthy)
        self.assertNotIn('unrelated', self.registry.enrollments)
        restored = self.store.load_registry('IGNORED')
        self.assertTrue(restored.persistence_healthy)
        self.assertFalse(restored.metadata.value('mac', 'allowed', True))
        _, core = make_app(registry=restored)
        resumed = restored.register(hello('mac', cap='say'), Socket(core.bus))
        self.assertFalse(restored.metadata.available(resumed, 'say'))
        self.assertFalse(restored.metadata.public_devices()[0]['allowed'])

    def test_configured_private_literals_and_controls_are_sanitized_before_label_persistence(self):
        metadata = self.registry.metadata
        metadata.configure_private_values(('provider-private', 'host-private', '', None))
        self.registry.offline(self.socket.dev)
        socket = self.enroll(label='  Mac\nprovider-private\t\x00host-private\x7f output  ')
        expected = 'Mac [private value] [private value] output'
        self.assertEqual(socket.dev.label, expected)
        self.assertEqual(metadata.label('mac'), expected)
        self.assertEqual(self.row()['label'], expected)
        durable = json.loads(self.path.read_text())['device_metadata']['mac']['adapter_label']['value']
        self.assertEqual(durable, expected)
        for label in (socket.dev.label, durable, self.row()['label']):
            self.assertNotIn('provider-private', label)
            self.assertNotIn('host-private', label)
            self.assertFalse(any(ord(char) < 32 or ord(char) == 127 for char in label))
        metadata.observe_label('mac', '\n\t\x00')
        self.assertEqual(metadata.label('mac'), 'Enrolled device')

    def test_private_configuration_sanitizes_existing_adapter_record_and_public_cap_names(self):
        metadata = self.registry.metadata
        metadata.records['mac']['adapter_label']['value'] = 'legacy-private\nMac'
        before = metadata.records['mac']['adapter_label']['at']
        metadata.configure_private_values(('legacy-private', 'provider-private'))
        self.assertEqual(metadata.records['mac']['adapter_label'],
                         {'value': '[private value] Mac', 'at': before})
        self.assertTrue(self.registry.persist())
        self.assertNotIn('legacy-private', self.path.read_text())
        self.registry.offline(self.socket.dev)
        caps = {name: {'args': {}, 'description': 'Private schema stays internal'}
                for name in ('say', 'provider-private.output', 'raw\ncapability')}
        self.enroll(caps=caps)
        row = self.row()
        self.assertEqual(row['caps'], ['say'])
        self.assertEqual([cap['name'] for cap in row['capability_status']], ['say'])
        self.assertIn('provider-private.output', self.registry.devices['mac'].caps)
        self.assertNotIn('provider-private', json.dumps(row))

    def test_guard_tracks_exact_connections_and_host_revisions_for_all_selected_devices(self):
        self.enroll('phone')
        metadata = self.registry.metadata
        guard = metadata.guard(['mac', 'phone'])
        self.assertTrue(guard())
        self.socket.dev.last_seen += .01
        self.assertTrue(guard())
        self.update({'role': 'audio_host'})
        self.assertFalse(guard())
        role_guard = metadata.guard(['mac', 'phone'])
        self.assertTrue(role_guard())
        self.update({'location': 'Desk'}, device_id='phone')
        self.assertFalse(role_guard())
        connection_guard = metadata.guard(['mac', 'phone'])
        old = self.socket.dev
        self.registry.offline(old)
        replacement = self.enroll()
        self.assertIsNot(replacement.dev, old)
        self.assertFalse(connection_guard())
        self.assertTrue(metadata.guard(['mac', 'phone'])())

    def test_guard_invalidates_deny_then_reenable_even_when_final_policy_matches(self):
        metadata = self.registry.metadata
        guard = metadata.guard(['mac'])
        before_revision = metadata.revision('mac')
        self.assertTrue(guard())
        self.update({'allowed': False})
        self.assertFalse(guard())
        denied_guard = metadata.guard(['mac'])
        self.assertTrue(denied_guard())
        self.assertFalse(metadata.available(self.socket.dev, 'say'))
        self.update({'allowed': True})
        self.assertFalse(guard())
        self.assertFalse(denied_guard())
        self.assertEqual(metadata.revision('mac'), before_revision + 2)
        self.assertTrue(metadata.available(self.socket.dev, 'say'))
        self.assertEqual(self.socket.frames, [])

    def test_guard_is_only_an_identity_revision_fence_and_never_availability_authority(self):
        metadata = self.registry.metadata
        guard = metadata.guard(['mac'])
        self.assertTrue(guard())
        self.mono.now = self.socket.dev.last_seen + MAX_AGE
        self.assertTrue(guard())
        self.assertFalse(metadata.available(self.socket.dev, 'say'))
        lease = self.core.leases.create(scopes={'light'})
        self.core.leases.current(lease.guest_id, activate=True)
        self.assertTrue(guard())
        self.assertFalse(self.core.leases.allows(lease, self.socket.dev, 'say'))
        self.registry.persistence_healthy = False
        self.assertTrue(guard())
        self.assertIsNone(metadata.binding('mac'))
        self.assertFalse(metadata.available(self.socket.dev, 'say'))

    def test_foreign_room_metadata_update_is_rejected_without_mutation(self):
        self.socket.dev.room_id = 'foreign-room'
        before = self.path.read_bytes()
        self.assertEqual(self.update({'role': 'speaker'}).status_code, 404)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.registry.metadata.revision('mac'), 0)


if __name__ == '__main__':
    unittest.main()
