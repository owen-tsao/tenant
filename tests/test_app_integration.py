"""Exercise the assembled app, beyond isolated component tests."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
import re
from fastapi.testclient import TestClient
from brain.config import Config
from brain.main import create_app


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Config('device', 'host', 'TEST', 'https://tenant.test'))
        self.client = self.enterContext(TestClient(self.app, base_url='https://tenant.test'))
        self.host = {'Authorization': 'Bearer host'}

    def enroll(self, ws, caps):
        ws.send_json({'type': 'hello', 'id': 'combo', 'label': 'Room device', 'room': self.app.state.registry.room.code, 'caps': caps})
        self.assertEqual(ws.receive_json()['type'], 'welcome')

    def test_host_audio_route_and_internal_request_correlation(self):
        caps = {'volume': {'description': 'Volume', 'args': {'level': {'type': 'integer', 'minimum': 0, 'maximum': 100}}}}
        with self.client.websocket_connect('/ws/device?t=device') as ws, ThreadPoolExecutor() as pool:
            self.enroll(ws, caps)
            response = pool.submit(self.client.post, '/host/do', headers=self.host,
                                   json={'device_id': 'combo', 'cap': 'volume', 'args': {'level': 25}})
            frame = ws.receive_json()
            ws.send_json({'type': 'ok', 'req': frame['req'], 'result': {'level': 25}})
            self.assertEqual(response.result(2).json(), {'ok': True, 'result': {'level': 25}})
            public = self.app.state.core.log.rows[-1]
            self.assertEqual(public['text'], 'Room device set its volume to 25 percent.')
            self.assertEqual(set(public), {'t', 'kind', 'text'})
            self.assertNotIn(frame['req'], public['text'])
            self.assertEqual(self.app.state.core.log.audit_rows[-1]['audit']['req'], frame['req'])

    def test_reset_revokes_before_cleanup_and_keeps_devices_usable(self):
        caps = {'light': {'description': 'Light', 'args': {'on': {'type': 'boolean'}}},
                'music.pause': {'description': 'Pause', 'args': {}}}
        lease = self.app.state.core.leases.create()
        with self.client.websocket_connect('/ws/device?t=device') as ws, ThreadPoolExecutor() as pool:
            self.enroll(ws, caps)
            pending = pool.submit(self.client.post, '/host/reset', headers=self.host)
            first = ws.receive_json()
            self.assertEqual(lease.state, 'released')
            self.assertEqual(first['cap'], 'light')
            self.assertEqual(first['args'], {'on': False})
            ws.send_json({'type': 'ok', 'req': first['req'], 'result': {'on': False}})
            second = ws.receive_json()
            self.assertEqual(second['cap'], 'music.pause')
            ws.send_json({'type': 'ok', 'req': second['req'], 'result': {'state': 'paused'}})
            result = pending.result(2).json()
            self.assertEqual(result['cleanup'], 'confirmed')
            self.assertNotEqual(result['room_code'], 'TEST')
            follow = pool.submit(self.client.post, '/host/do', headers=self.host,
                                 json={'device_id': 'combo', 'cap': 'light', 'args': {'on': False}})
            frame = ws.receive_json()
            ws.send_json({'type': 'ok', 'req': frame['req'], 'result': {'on': False}})
            self.assertTrue(follow.result(2).json()['ok'])

    def test_offline_cleanup_is_unconfirmed(self):
        caps = {'light': {'description': 'Light', 'args': {'on': {'type': 'boolean'}}}}
        with self.client.websocket_connect('/ws/device?t=device') as ws:
            self.enroll(ws, caps)
        self.assertEqual(self.client.post('/host/reset', headers=self.host).json()['cleanup'], 'unconfirmed')

    def test_reset_after_restart_cannot_claim_cleanup_before_enrolled_devices_return(self):
        self.app.state.registry.enrollments['previous-phone'] = {'TEST'}
        self.assertEqual(self.client.post('/host/reset', headers=self.host).json()['cleanup'], 'unconfirmed')

    def test_real_guest_pages_load_their_relative_browser_assets(self):
        for route in ['/j/TEST', '/g/example-guest']:
            page = self.client.get(route)
            self.assertEqual(page.status_code, 200)
            assets = re.findall(r'(?:href|src)="(tenant\.css|shared\.js)"', page.text)
            self.assertEqual(set(assets), {'tenant.css', 'shared.js'})
            for name in assets:
                response = self.client.get(urljoin(route, name))
                self.assertEqual(response.status_code, 200)
                expected = 'text/css' if name.endswith('.css') else 'javascript'
                self.assertIn(expected, response.headers['content-type'])
                self.assertNotIn('<!doctype html>', response.text.lower())

    def test_guest_qr_is_real_svg_and_changes_with_reset(self):
        before = self.client.get('/qr.svg')
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.headers['cache-control'], 'no-store')
        self.assertIn('image/svg+xml', before.headers['content-type'])
        xml = ET.fromstring(before.content)
        self.assertEqual(xml.tag, '{http://www.w3.org/2000/svg}svg')
        self.assertTrue(xml.findall('.//{http://www.w3.org/2000/svg}path'))
        self.client.post('/host/reset', headers=self.host)
        self.assertNotEqual(before.content, self.client.get('/qr.svg').content)

    def test_reset_requires_observed_defaults_not_only_success_acknowledgment(self):
        for cap, payload, expected in [('light', {'on': True}, 'unconfirmed'),
                                       ('light', {}, 'unconfirmed'),
                                       ('music.pause', {'state': 'playing'}, 'unconfirmed'),
                                       ('music.pause', {}, 'unconfirmed'),
                                       ('music.pause', {'state': 'stopped'}, 'confirmed')]:
            with self.subTest(cap=cap, payload=payload):
                args = {'on': {'type': 'boolean'}} if cap == 'light' else {}
                with self.client.websocket_connect('/ws/device?t=device') as ws, ThreadPoolExecutor() as pool:
                    self.enroll(ws, {cap: {'description': 'Room effect', 'args': args}})
                    response = pool.submit(self.client.post, '/host/reset', headers=self.host)
                    frame = ws.receive_json()
                    ws.send_json({'type': 'ok', 'req': frame['req'], 'result': payload})
                    self.assertEqual(response.result(2).json()['cleanup'], expected)


if __name__ == '__main__':
    unittest.main()
