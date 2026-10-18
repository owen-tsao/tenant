"""Read-only host diagnostics using actual core guards and a private service spy.

All requests use an in-process ASGI transport; no enrolled device, live API,
native session, model, camera or browser is contacted.
"""
import copy
from types import SimpleNamespace
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain.api.photos import VIEWER_COOKIE, router
from brain.core.integration import Core as AccessCore
from brain.core.photos import PhotoError


ORIGIN = 'https://tenant.test'
HOST = {'Origin': ORIGIN, 'Authorization': 'Bearer host-private'}
UNCONFIGURED = {'ok': True, 'enabled': False, 'source_device_id': None, 'viewer_id': None,
                'source': None, 'viewer': {'enrolled': False, 'online': False},
                'ready': False, 'pending': False, 'blockers': ['Photo source and viewer are not configured.']}
CONFIGURED = {'ok': True, 'enabled': True, 'source_device_id': 'phone-1', 'viewer_id': 'mac-main',
              'source': {'online': True, 'consent': True}, 'viewer': {'enrolled': True, 'online': True},
              'ready': True, 'pending': False, 'blockers': []}


class ConfigurationSpy:
    def __init__(self):
        self.safe = copy.deepcopy(UNCONFIGURED)
        self.reads = 0
        self.error = None
        # These private service details must never be returned or used as a
        # shortcut to configure/enroll/touch a viewer during a diagnostic GET.
        self.enabled = False
        self.source_device_id = None
        self.viewer = SimpleNamespace(token='viewer-private', seen=1000.)
        self.latest = b'private-image-pixels'
        self.ticket = 'upload-private'
        self.consent_revision = 4
        self.authority_grants = []

    def configuration(self):
        self.reads += 1
        if self.error:
            raise self.error
        return copy.deepcopy(self.safe)

    def configure(self, *args, **kwargs):
        raise AssertionError('Diagnostic read must not configure photos')

    def enroll_viewer(self, *args, **kwargs):
        raise AssertionError('Diagnostic read must not enroll a viewer')

    def viewer_state(self, *args, **kwargs):
        raise AssertionError('Diagnostic read must not refresh viewer liveness')


class Core(AccessCore):
    def __init__(self):
        self.config = SimpleNamespace(public_url=ORIGIN, host_token='host-private')
        self.photos = ConfigurationSpy()
        self.credentials = {}


class PhotoConfigurationApiTests(unittest.TestCase):
    def setUp(self):
        self.core = Core()
        self.app = FastAPI()
        self.app.state.core = self.core
        self.app.include_router(router)
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN))

    def read(self, *, headers=HOST, query=''):
        return self.client.get('/host/photos/config' + query, headers=headers)

    def test_unconfigured_read_returns_service_diagnostics_without_enabling(self):
        response = self.read()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), UNCONFIGURED)
        self.assertEqual(self.core.photos.reads, 1)
        self.assertFalse(self.core.photos.enabled)
        self.assertNotIn('set-cookie', response.headers)

    def test_configured_read_returns_safe_diagnostics_and_no_credentials_or_pixels(self):
        self.core.photos.safe = copy.deepcopy(CONFIGURED)
        response = self.read()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), CONFIGURED)
        for private in ('host-private', 'viewer-private', 'upload-private', 'private-image-pixels',
                        'image_url', 'upload_token', 'ticket', 'token'):
            self.assertNotIn(private, response.text)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')

    def test_guest_viewer_and_anonymous_credentials_cannot_read_host_diagnostics(self):
        guest = self.core.issue_credential('guest-1')
        self.assertTrue(self.core.authentic_guest('guest-1', {self.core.cookie_name('guest-1'): guest}))
        self.client.cookies.set(self.core.cookie_name('guest-1'), guest)
        self.client.cookies.set(VIEWER_COOKIE, 'viewer-private')
        for headers in ({}, {'Origin': ORIGIN}, {'Origin': ORIGIN, 'Authorization': 'Bearer ' + guest},
                        {'Origin': ORIGIN, 'Authorization': 'Bearer viewer-private'},
                        {'Origin': ORIGIN, 'X-Host-Token': 'host-private'},
                        {**HOST, 'Authorization': 'Bearer wrong'}):
            with self.subTest(headers=headers):
                response = self.read(headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.core.photos.reads, 0)

    def test_only_approved_exact_origin_with_host_bearer_reaches_service(self):
        for origin in (None, '', 'null', 'http://tenant.test', 'https://tenant.test/',
                       'https://tenant.test/path', 'https://tenant.test?query=1',
                       'https://tenant.test.evil', 'https://evil.test', 'https://user@tenant.test'):
            headers = {'Authorization': 'Bearer host-private'}
            if origin is not None:
                headers['Origin'] = origin
            with self.subTest(origin=origin):
                self.assertEqual(self.read(headers=headers).status_code, 403)
        self.assertEqual(self.core.photos.reads, 0)
        self.assertEqual(self.read().status_code, 200)
        self.assertEqual(self.core.photos.reads, 1)

    def test_duplicate_or_fallback_authentication_and_origin_are_rejected(self):
        for headers in (list(HOST.items()) + [('Authorization', 'Bearer other')],
                        list(HOST.items()) + [('Origin', 'https://evil.test')],
                        {**HOST, 'X-Host-Token': 'host-private'},
                        {**HOST, 'Authorization': 'Bearer wrong', 'X-Host-Token': 'host-private'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.read(headers=headers).status_code, 403)
        self.assertEqual(self.core.photos.reads, 0)

    def test_query_fields_cannot_supply_credentials_or_change_configuration(self):
        for query in ('?host_token=host-private', '?viewer_id=other', '?enabled=true',
                      '?token=viewer-private', '?guest_id=guest-1', '?enabled=true&enabled=false'):
            with self.subTest(query=query):
                self.assertEqual(self.read(query=query).status_code, 400)
        self.assertEqual(self.core.photos.reads, 0)

    def test_repeated_reads_never_enroll_enable_refresh_viewer_or_grant_authority(self):
        photos = self.core.photos
        before = copy.deepcopy({key: value for key, value in vars(photos).items() if key != 'reads'})
        for _ in range(2):
            self.assertEqual(self.read().status_code, 200)
        after = {key: value for key, value in vars(photos).items() if key != 'reads'}
        self.assertEqual(after, before)
        self.assertEqual(photos.reads, 2)
        self.assertEqual(photos.viewer.seen, 1000.)
        self.assertEqual(photos.authority_grants, [])

    def test_expected_service_failure_preserves_structured_private_response(self):
        self.core.photos.error = PhotoError(503, 'PHOTO_UNAVAILABLE', 'Photo diagnostics are unavailable')
        response = self.read()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'ok': False, 'code': 'PHOTO_UNAVAILABLE',
                                           'message': 'Photo diagnostics are unavailable'})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')


if __name__ == '__main__':
    unittest.main()
