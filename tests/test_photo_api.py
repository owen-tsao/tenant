"""Private photo HTTP boundaries; no device, browser, model or live service."""
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from brain.api.photos import IMAGE_LIMIT, JSON_LIMIT, VIEWER_COOKIE, _body, router
from brain.core.integration import Core as AccessCore
from brain.core.photos import PhotoError


ORIGIN = 'https://tenant.test'
HOST = {'Origin': ORIGIN, 'Authorization': 'Bearer host-private'}
JSON = {'Origin': ORIGIN, 'Content-Type': 'application/json'}


class Photos:
    def __init__(self):
        self.calls = []
        self.error = None

    def result(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.error:
            raise self.error
        return {'ok': True, 'state': 'pending'}

    def configure(self, *args, **kwargs):
        return self.result('configure', *args, **kwargs)

    def enroll_viewer(self, *args):
        self.result('enroll_viewer', *args)
        return 'private-viewer-token'

    async def capture(self, *args, **kwargs):
        return self.result('capture', *args, **kwargs)

    def status(self, *args):
        return self.result('status', *args)

    def viewer_state(self, *args):
        return self.result('viewer_state', *args)

    def image(self, *args):
        self.result('image', *args)
        return b'normalized-jpeg'

    def viewer_receipt(self, *args):
        return self.result('viewer_receipt', *args)

    async def upload(self, *args):
        return self.result('upload', *args)


class Core(AccessCore):
    def __init__(self):
        self.photos = Photos()
        self.config = SimpleNamespace(public_url=ORIGIN, host_token='host-private')
        self.agent = SimpleNamespace(_generation=17)
        self.lease = object()
        self.leases = SimpleNamespace(leases={'guest-1': self.lease})

    def cookie_name(self, guest_id):
        return 'guest_' + guest_id

    def authentic_guest(self, guest_id, cookies):
        return guest_id == 'guest-1' and cookies.get(self.cookie_name(guest_id)) == 'guest-private'


class PhotoApiTests(unittest.TestCase):
    def setUp(self):
        self.core = Core()
        self.app = FastAPI()
        self.app.state.core = self.core
        self.app.include_router(router)
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN))
        self.client.cookies.set('guest_guest-1', 'guest-private')
        self.client.cookies.set(VIEWER_COOKIE, 'private-viewer-token')
        self.capture_body = {'guest_id': 'guest-1', 'request_id': 'request-1', 'source_device_id': 'phone-1'}
        self.config_body = {'source_device_id': 'phone-1', 'viewer_id': 'mac-main', 'enabled': True}

    def test_host_configuration_requires_both_bearer_and_origin(self):
        for headers in ({}, {'Authorization': 'Bearer host-private'}, {'Origin': ORIGIN},
                        {**HOST, 'Origin': 'https://evil.test'},
                        {**HOST, 'Authorization': 'Bearer wrong'},
                        {'Origin': ORIGIN, 'X-Host-Token': 'host-private'},
                        {**HOST, 'X-Host-Token': 'host-private'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post('/host/photos/config', headers=headers,
                                                 json=self.config_body).status_code, 403)
        self.assertFalse(self.core.photos.calls)
        response = self.client.post('/host/photos/config', headers=HOST, json=self.config_body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.core.photos.calls[-1], ('configure', ('phone-1', 'mac-main'), {'enabled': True}))

    def test_viewer_enrollment_sets_private_scoped_secure_cookie_only(self):
        response = self.client.post('/host/photos/viewer', headers=HOST, json={'viewer_id': 'mac-main'})
        self.assertEqual(response.json(), {'ok': True, 'viewer_id': 'mac-main'})
        cookie = response.headers['set-cookie']
        for piece in (VIEWER_COOKIE + '=private-viewer-token', 'HttpOnly', 'Path=/photos',
                      'SameSite=strict', 'Secure'):
            self.assertIn(piece, cookie)
        self.assertNotIn('private-viewer-token', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_core_http_guard_exceptions_are_private_and_keep_standard_detail(self):
        for headers, detail in (({**HOST, 'Authorization': 'Bearer wrong'}, 'Host authorization required'),
                                ({**HOST, 'Origin': 'https://evil.test'}, 'Approved same-origin request required')):
            with self.subTest(detail=detail):
                response = self.client.post('/host/photos/config', headers=headers, json=self.config_body)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {'detail': detail})
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertFalse(self.core.photos.calls)

    def test_http_exception_headers_are_preserved_without_allowing_cache(self):
        def reject(request):
            raise HTTPException(401, 'Host authorization required',
                                headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'public'})

        self.core.require_host = reject
        response = self.client.post('/host/photos/config', headers=HOST, json=self.config_body)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['www-authenticate'], 'Bearer')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertFalse(self.core.photos.calls)

    def test_plain_http_enrollment_does_not_set_secure(self):
        self.core.config.public_url = 'http://tenant.test'
        response = self.client.post('/host/photos/viewer', headers={**HOST, 'Origin': 'http://tenant.test'},
                                    json={'viewer_id': 'mac-main'})
        self.assertNotIn('; Secure', response.headers['set-cookie'])

    def test_capture_passes_exact_lease_and_server_generation(self):
        response = self.client.post('/photos/captures', headers={'Origin': ORIGIN}, json=self.capture_body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.core.photos.calls[-1],
                         ('capture', (self.core.lease, 'request-1', 'phone-1'), {'generation': 17}))
        self.assertNotIn('token', response.text)
        self.assertNotIn('image', response.text)
        self.assertNotIn('upload', response.text)

    def test_status_does_not_renew_or_activate_lease_and_needs_guest_cookie(self):
        response = self.client.get('/photos/captures/request-1?guest_id=guest-1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.core.photos.calls[-1], ('status', (self.core.lease, 'request-1'), {}))
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/photos/captures/request-1?guest_id=guest-1').status_code, 403)

    def test_capture_denies_wrong_missing_and_nonexistent_guest_credentials(self):
        self.client.cookies.clear()
        for cookie in ('', 'guest_guest-1=wrong', 'guest_guest-2=guest-private'):
            with self.subTest(cookie=cookie):
                response = self.client.post('/photos/captures', headers={'Origin': ORIGIN, 'Cookie': cookie},
                                            json=self.capture_body)
                self.assertEqual(response.status_code, 403)
        self.client.cookies.set('guest_guest-1', 'guest-private')
        self.core.leases.leases.clear()
        self.assertEqual(self.client.post('/photos/captures', headers={'Origin': ORIGIN},
                                          json=self.capture_body).status_code, 403)
        self.assertFalse(self.core.photos.calls)

    def test_guest_cannot_supply_generation_tokens_or_extra_fields(self):
        for key, value in (('generation', 17), ('guest_token', 'guest-private'), ('upload_token', 'private'),
                           ('lease', 'guest-1')):
            with self.subTest(key=key):
                self.assertEqual(self.client.post('/photos/captures', headers={'Origin': ORIGIN},
                                                  json={**self.capture_body, key: value}).status_code, 400)
        self.assertFalse(self.core.photos.calls)

    def test_every_mutation_requires_approved_single_origin(self):
        cases = [('/host/photos/config', self.config_body, {'Authorization': 'Bearer host-private'}),
                 ('/host/photos/viewer', {'viewer_id': 'mac-main'}, {'Authorization': 'Bearer host-private'}),
                 ('/photos/captures', self.capture_body, {}),
                 ('/photos/viewer/receipt', {'photo_id': 'photo-1', 'version': 1}, {})]
        for path, body, auth in cases:
            for origin in (None, 'https://evil.test'):
                headers = dict(auth)
                if origin:
                    headers['Origin'] = origin
                with self.subTest(path=path, origin=origin):
                    self.assertEqual(self.client.post(path, headers=headers, json=body).status_code, 403)
            headers = list(auth.items()) + [('Origin', ORIGIN), ('Origin', 'https://evil.test')]
            self.assertEqual(self.client.post(path, headers=headers, json=body).status_code, 403)
        self.assertFalse(self.core.photos.calls)

    def test_cookie_authorized_viewer_reads_need_no_origin(self):
        state = self.client.get('/photos/viewer/state')
        self.assertEqual(state.status_code, 200)
        image = self.client.get('/photos/images/photo-1')
        self.assertEqual(image.content, b'normalized-jpeg')
        self.assertEqual(image.headers['content-type'], 'image/jpeg')
        self.assertEqual(image.headers['x-content-type-options'], 'nosniff')
        for response in (state, image):
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')

    def test_no_url_host_or_guest_credential_can_authorize_viewer(self):
        self.client.cookies.clear()
        for path in ('/photos/viewer/state', '/photos/images/photo-1'):
            self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer host-private'}).status_code, 403)
            self.assertEqual(self.client.get(path + '?token=private-viewer-token').status_code, 400)
            self.assertEqual(self.client.get(path + '?guest_id=guest-1').status_code, 400)
        self.assertFalse(self.core.photos.calls)

    def test_viewer_receipt_exact_identity_version_cookie(self):
        response = self.client.post('/photos/viewer/receipt', headers={'Origin': ORIGIN},
                                    json={'photo_id': 'photo-1', 'version': 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.core.photos.calls[-1],
                         ('viewer_receipt', ('private-viewer-token', 'photo-1', 3), {}))
        for version in (True, False, -1, 1.5, '1', None, 2 ** 53):
            self.assertEqual(self.client.post('/photos/viewer/receipt', headers={'Origin': ORIGIN},
                                              json={'photo_id': 'photo-1', 'version': version}).status_code, 400)

    def test_no_duplicate_or_alternate_authorization_is_accepted(self):
        headers = [('Origin', ORIGIN), ('Authorization', 'Bearer host-private'),
                   ('Authorization', 'Bearer wrong')]
        self.assertEqual(self.client.post('/host/photos/config', headers=headers,
                                          json=self.config_body).status_code, 403)
        for path, cookie in (('/photos/viewer/state', VIEWER_COOKIE + '=one; ' + VIEWER_COOKIE + '=two'),
                             ('/photos/captures/request-1?guest_id=guest-1',
                              'guest_guest-1=guest-private; guest_guest-1=wrong')):
            self.assertEqual(self.client.get(path, headers={'Cookie': cookie}).status_code, 403)
        for path in ('/photos/viewer/state', '/photos/captures/request-1?guest_id=guest-1'):
            self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer host-private'}).status_code, 403)
        self.assertFalse(self.core.photos.calls)

    def test_json_schema_is_exact_and_rejects_duplicate_keys_invalid_types_and_bounds(self):
        bad = [{}, [], True, {**self.config_body, 'enabled': 1},
               {**self.config_body, 'viewer_id': None}, {**self.config_body, 'viewer_id': ''},
               {**self.config_body, 'viewer_id': 'x' * 129},
               {**self.config_body, 'viewer_id': 'mac/other'},
               {**self.config_body, 'viewer_id': 'café'},
               {**self.config_body, 'source_device_id': 'phone\nother'},
               {**self.config_body, 'extra': 'ignored?'}]
        for body in bad:
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/host/photos/config', headers=HOST, json=body).status_code, 400)
        for raw in ('{', '{"viewer_id":"one","viewer_id":"two"}',
                    '{"source_device_id":NaN,"viewer_id":"mac","enabled":true}'):
            self.assertEqual(self.client.post('/host/photos/config', headers={**HOST, 'Content-Type': 'application/json'},
                                              content=raw).status_code, 400)
        self.assertFalse(self.core.photos.calls)

    def test_json_body_size_and_media_are_bounded_before_service(self):
        response = self.client.post('/host/photos/config', headers={**HOST, 'Content-Type': 'application/json'},
                                    content=b' ' * (JSON_LIMIT + 1))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['code'], 'PHOTO_TOO_LARGE')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.post('/host/photos/config', headers=HOST, content='{}').status_code, 415)
        self.assertFalse(self.core.photos.calls)

    def test_query_parameters_are_exact_and_cannot_carry_secrets(self):
        for query in ('', '?guest_id=guest-1&guest_id=guest-1', '?guest_id=guest-1&token=guest-private'):
            self.assertEqual(self.client.get('/photos/captures/request-1' + query).status_code, 400)
        self.assertEqual(self.client.post('/photos/captures?generation=17', headers={'Origin': ORIGIN},
                                          json=self.capture_body).status_code, 400)
        self.assertEqual(self.client.post('/host/photos/viewer?host_token=host-private', headers=HOST,
                                          json={'viewer_id': 'mac'}).status_code, 400)
        self.assertFalse(self.core.photos.calls)

    def test_upload_uses_only_one_bearer_and_passes_raw_media_to_service(self):
        headers = {'Origin': ORIGIN, 'Authorization': 'Bearer one-use-private', 'Content-Type': 'image/jpeg'}
        response = self.client.post('/photos/uploads/capture-1', headers=headers, content=b'jpeg-input')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.core.photos.calls[-1],
                         ('upload', ('capture-1', 'one-use-private', b'jpeg-input', 'image/jpeg'), {}))
        self.assertNotIn('one-use-private', response.text)

    def test_upload_denies_missing_ambiguous_url_and_alternate_tickets(self):
        self.client.cookies.set('upload_token', 'one-use-private')
        for auth in (None, '', 'Bearer ', 'Basic one-use-private', 'Bearer one-use-private,other',
                     'Bearer one-use private'):
            headers = {'Origin': ORIGIN, 'Content-Type': 'image/jpeg'}
            if auth is not None:
                headers['Authorization'] = auth
            self.assertEqual(self.client.post('/photos/uploads/capture-1', headers=headers,
                                              content=b'jpeg').status_code, 403)
        valid = {'Origin': ORIGIN, 'Content-Type': 'image/jpeg', 'Authorization': 'Bearer one-use-private'}
        self.assertEqual(self.client.post('/photos/uploads/capture-1?token=one-use-private',
                                          headers=valid, content=b'jpeg').status_code, 400)
        self.assertEqual(self.client.post('/photos/uploads/capture-1', headers={**valid, 'X-Host-Token': 'host-private'},
                                          content=b'jpeg').status_code, 403)
        duplicate = list(valid.items()) + [('Authorization', 'Bearer other')]
        self.assertEqual(self.client.post('/photos/uploads/capture-1', headers=duplicate, content=b'jpeg').status_code, 403)
        self.assertFalse(self.core.photos.calls)

    def test_upload_needs_origin_and_rejects_oversize_before_service(self):
        headers = {'Content-Type': 'image/jpeg', 'Authorization': 'Bearer one-use-private'}
        self.assertEqual(self.client.post('/photos/uploads/capture-1', headers=headers, content=b'jpeg').status_code, 403)
        self.assertEqual(self.client.post('/photos/uploads/capture-1', headers={**headers, 'Origin': ORIGIN},
                                          content=b'x' * (IMAGE_LIMIT + 1)).status_code, 413)
        self.assertFalse(self.core.photos.calls)

    def test_service_errors_are_safe_structured_and_not_cached(self):
        self.core.photos.error = PhotoError(409, 'PHOTO_STALE', 'Capture is no longer current')
        response = self.client.get('/photos/viewer/state')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'ok': False, 'code': 'PHOTO_STALE', 'message': 'Capture is no longer current'})
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_programming_errors_are_not_mislabeled_as_expected_photo_failures(self):
        self.core.photos.error = RuntimeError('bug')
        with self.assertRaisesRegex(RuntimeError, 'bug'):
            self.client.get('/photos/viewer/state')


class StreamingBodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_without_content_length_stops_at_limit(self):
        remaining = [b'ab', b'cdef', b'never-read']

        async def receive():
            return {'type': 'http.request', 'body': remaining.pop(0), 'more_body': True}

        request = Request({'type': 'http', 'headers': []}, receive)
        with self.assertRaises(PhotoError) as caught:
            await _body(request, 5)
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(remaining, [b'never-read'])

    async def test_lying_short_content_length_does_not_bypass_stream_limit(self):
        async def receive():
            return {'type': 'http.request', 'body': b'longer-than-five', 'more_body': False}

        request = Request({'type': 'http', 'headers': [(b'content-length', b'1')]}, receive)
        with self.assertRaises(PhotoError) as caught:
            await _body(request, 5)
        self.assertEqual(caught.exception.status, 413)

    async def test_oversize_declared_body_is_rejected_without_read(self):
        async def receive():
            self.fail('An oversized request must not be consumed')

        for value in (str(IMAGE_LIMIT + 1).encode(), b'9' * 5000):
            request = Request({'type': 'http', 'headers': [(b'content-length', value)]}, receive)
            with self.assertRaises(PhotoError) as caught:
                await _body(request, IMAGE_LIMIT)
            self.assertEqual(caught.exception.status, 413)


if __name__ == '__main__':
    unittest.main()
