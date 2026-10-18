"""Real setup routes and persistence, without devices, models or live services."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from brain.config import Config
from brain.core.persistence import RoomStateStore
from brain.main import WEB, create_app
from test_access_core import register


HOST = {'Authorization': 'Bearer host-private'}
SETUP = {'Origin': 'https://testserver', 'X-Host-Token': 'host-private'}


class RoomSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'room.json'
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://testserver'),
                              state_path=self.path)
        self.core = self.app.state.core
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def name(self, label='Tenant demo room', *, headers=HOST):
        return self.client.post('/host/room', headers=headers, json={'label': label})

    def test_root_and_setup_serve_exact_existing_page_and_relative_assets(self):
        for url in ('/', '/setup'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, (WEB / 'setup.html').read_bytes())
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.client.get('/shared.js').status_code, 200)
        self.assertEqual(self.client.get('/tenant.css').status_code, 200)

    def test_setup_header_requires_nonempty_correct_secret_and_approved_origin(self):
        before = self.path.read_bytes()
        for headers in ({}, {'X-Host-Token': ''}, {'Origin': 'https://testserver'},
                        {'Origin': 'https://testserver', 'X-Host-Token': 'wrong'},
                        {'X-Host-Token': 'host-private'},
                        {'Origin': 'https://evil.test', 'X-Host-Token': 'host-private'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.name(headers=headers).status_code, 403)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.name(headers=SETUP).json()['room']['label'], 'Tenant demo room')
        # This compatibility is deliberately unavailable on existing host actions.
        self.assertEqual(self.client.post('/host/reset', headers=SETUP).status_code, 403)

    def test_bearer_contract_works_without_origin_and_invalid_bearer_cannot_fall_back(self):
        self.assertEqual(self.name(headers=HOST).status_code, 200)
        mixed = {**SETUP, 'Authorization': 'Bearer wrong'}
        self.assertEqual(self.name('Bad fallback', headers=mixed).status_code, 403)
        self.assertEqual(self.core.registry.room.label, 'Tenant demo room')

    def test_empty_server_host_token_never_authorizes_naming(self):
        app = create_app(Config('device-private', '', 'TEST', 'https://testserver'))
        with TestClient(app) as client:
            for headers in ({'Authorization': 'Bearer '},
                            {'Origin': 'https://testserver', 'X-Host-Token': ''}):
                self.assertEqual(client.post('/host/room', headers=headers, json={'label': 'No'}).status_code, 403)

    def test_invalid_labels_and_private_literals_never_mutate_state(self):
        before = self.path.read_bytes()
        self.core.agent.private_values = ('photon-private',)
        for label in ('', '  ', None, True, 42, 'x' * 129, 'two\nlines', 'tab\tname', 'null\0name',
                      'host-private', 'device-private', 'photon-private'):
            with self.subTest(label=label):
                self.assertEqual(self.name(label).status_code, 400)
        for body in ({}, [], {'label': 'Valid', 'epoch': 0}):
            self.assertEqual(self.client.post('/host/room', headers=HOST, json=body).status_code, 400)
        self.assertEqual(self.client.post('/host/room', headers=HOST, content='{').status_code, 400)
        self.assertEqual(self.path.read_bytes(), before)

    def test_saved_label_preserves_invitation_epoch_lease_history_credentials_and_connections(self):
        phone = register(self.core)
        lease = self.core.leases.create()
        self.core.leases.current(lease.guest_id, activate=True)
        token = self.core.issue_credential(lease.guest_id)
        history = self.core.leases.sessions[lease.guest_id]
        history.messages.append({'role': 'user', 'content': 'Existing conversation'})
        room = self.core.registry.room
        identity = room.id, room.code, room.epoch, lease.expires_at
        aliases = {key: set(value) for key, value in self.core.registry.enrollments.items()}
        result = self.name('  Tenant café 🎵  ')
        self.assertEqual(result.json(), {'ok': True, 'room': {
            'code': identity[1], 'label': 'Tenant café 🎵', 'join_url': 'https://testserver/j/' + identity[1]}})
        self.assertEqual((room.id, room.code, room.epoch, lease.expires_at), identity)
        self.assertIs(self.core.leases.current(lease.guest_id), lease)
        self.assertTrue(self.core.authentic_token(lease.guest_id, token))
        self.assertIs(self.core.leases.sessions[lease.guest_id], history)
        self.assertEqual(len(history.messages), 1)
        self.assertIs(self.core.registry.devices['phone'], phone.dev)
        self.assertIs(phone.dev.ws, phone)
        self.assertEqual(self.core.registry.enrollments, aliases)
        self.assertEqual(phone.frames, [])
        restored = RoomStateStore(self.path).load_registry('IGNORED')
        self.assertEqual(restored.room.label, 'Tenant café 🎵')
        self.assertEqual((restored.room.id, restored.room.code, restored.room.epoch), identity[:3])

    def test_display_state_broadcasts_actual_saved_label(self):
        with self.client.websocket_connect('/ws/display', headers={'Origin': 'https://testserver'}) as display:
            initial = display.receive_json()
            result = self.name('Live saved room')
            self.assertEqual(result.status_code, 200)
            state = display.receive_json()
            self.assertEqual(state['room'], result.json()['room'])
            self.assertEqual(state['room']['code'], initial['room']['code'])
            self.assertEqual(json.loads(self.path.read_text())['room']['label'], state['room']['label'])
            self.assertNotIn('host-private', json.dumps(state))

    def test_custom_name_survives_invitation_reset_and_restart_but_generated_name_tracks_code(self):
        old_code = self.core.registry.room.code
        self.assertEqual(self.core.registry.room.label, 'Room ' + old_code)
        generated = self.client.post('/host/reset', headers=HOST).json()
        self.assertNotEqual(generated['room_code'], old_code)
        self.assertEqual(self.core.registry.room.label, 'Room ' + generated['room_code'])
        self.assertEqual(self.name('Tenant shared room').status_code, 200)
        custom = self.client.post('/host/reset', headers=HOST).json()
        self.assertNotEqual(custom['room_code'], generated['room_code'])
        self.assertEqual(self.core.registry.room.label, 'Tenant shared room')
        restored = RoomStateStore(self.path).load_registry('IGNORED')
        self.assertEqual(restored.room.label, 'Tenant shared room')
        self.assertEqual(restored.room.code, custom['room_code'])

    def test_failed_save_restores_visible_label_and_fails_guest_access_closed(self):
        lease = self.core.leases.create()
        room = self.core.registry.room
        old = room.label, room.code, room.epoch
        previous = self.path.read_bytes()
        with patch('brain.core.persistence.os.replace', side_effect=OSError('disk unavailable')):
            response = self.name('Unsaved room')
        self.assertEqual(response.status_code, 503)
        self.assertEqual((room.label, room.code, room.epoch), old)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertFalse(self.core.registry.persistence_healthy)
        self.assertIsNone(self.core.leases.current(lease.guest_id))
        self.assertEqual(self.name('No bypass').status_code, 503)
