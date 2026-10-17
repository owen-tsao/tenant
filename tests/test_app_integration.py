"""Exercise the assembled app, beyond isolated component tests."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from fastapi.testclient import TestClient
from brain.config import Config
from brain.main import create_app


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Config('device', 'host', 'TEST', 'https://tenant.test'))
        self.client = self.enterContext(TestClient(self.app, base_url='https://tenant.test'))
        self.host = {'Authorization': 'Bearer host'}

    def enroll(self, ws, caps):
        ws.send_json({'type': 'hello', 'id': 'combo', 'label': 'Room device', 'room': 'TEST', 'caps': caps})
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
            self.assertIn(frame['req'], self.app.state.core.log.rows[-1]['text'])

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


if __name__ == '__main__':
    unittest.main()
