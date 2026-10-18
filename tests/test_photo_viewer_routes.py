"""Fixed private-viewer bootstrap routes; no browser, model, camera or service."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain.api import photos


class PhotoViewerRouteTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.html = Path(directory) / 'photo_viewer.html'
        self.script = Path(directory) / 'photo_viewer.js'
        self.html.write_text('<!doctype html><script src="/photos/viewer.js" defer></script>')
        self.script.write_text('"use strict"; /* empty offline bootstrap fixture */')
        self.enterContext(patch.object(photos, 'VIEWER_HTML', self.html))
        self.enterContext(patch.object(photos, 'VIEWER_SCRIPT', self.script))
        self.app = FastAPI()
        self.app.state.core = SimpleNamespace(photos=Mock())
        self.app.include_router(photos.router)
        self.client = self.enterContext(TestClient(self.app, base_url='https://tenant.test'))

    def assert_private_response(self, response):
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')

    def test_only_fixed_empty_bootstrap_assets_are_served_without_authority(self):
        for route, file, mime in (('/photos/viewer', self.html, 'text/html'),
                                  ('/photos/viewer.js', self.script, 'text/javascript')):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, file.read_bytes())
                self.assertEqual(response.headers['content-type'], mime + '; charset=utf-8')
                self.assert_private_response(response)
                self.assertNotIn('set-cookie', response.headers)
                self.assertNotIn('tenant_photo_viewer', response.text)
        self.assertEqual(self.app.state.core.photos.mock_calls, [])

    def test_bootstrap_policy_allows_local_renderer_but_no_inline_script_or_external_resources(self):
        for route in ('/photos/viewer', '/photos/viewer.js'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                directives = dict(part.strip().split(' ', 1)
                                  for part in response.headers['content-security-policy'].split(';'))
                for key in ('default-src', 'base-uri', 'object-src', 'frame-ancestors', 'form-action'):
                    self.assertEqual(directives[key], "'none'")
                self.assertEqual(directives['script-src'], "'self'")
                self.assertEqual(directives['connect-src'], "'self'")
                self.assertEqual(directives['img-src'], "'self' blob:")
                self.assertEqual(directives['style-src'], "'unsafe-inline'")

    def test_query_credentials_and_arbitrary_paths_cannot_select_files(self):
        for route in ('/photos/viewer', '/photos/viewer.js'):
            for query in ('?token=private', '?path=../../private', '?file=other.js', '?v=1'):
                with self.subTest(route=route, query=query):
                    response = self.client.get(route + query)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()['code'], 'INVALID_REQUEST')
                    self.assert_private_response(response)
                    self.assertNotIn('private', response.text)
        for route in ('/photos/viewer/other.js', '/photos/viewer.js/other', '/photos/other.js'):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.app.state.core.photos.mock_calls, [])

    def test_missing_or_unreadable_assets_fail_privately_without_file_fallback(self):
        self.html.unlink()
        for route in ('/photos/viewer', '/photos/viewer.js'):
            with self.subTest(route=route):
                with patch.object(Path, 'read_bytes', side_effect=PermissionError('private-file-detail')):
                    response = self.client.get(route)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {'ok': False, 'code': 'PHOTO_VIEWER_UNAVAILABLE',
                                                  'message': 'Photo viewer is unavailable'})
                self.assert_private_response(response)
                self.assertNotIn(str(self.html.parent), response.text)
                self.assertNotIn('private-file-detail', response.text)
        self.assertEqual(self.client.get('/photos/viewer').status_code, 503)

    def test_bootstrap_never_substitutes_for_existing_viewer_cookie_authorization(self):
        self.assertEqual(self.client.get('/photos/viewer').status_code, 200)
        for route in ('/photos/viewer/state', '/photos/images/photo-1'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['code'], 'PHOTO_AUTH_REQUIRED')
                self.assert_private_response(response)
        self.assertEqual(self.app.state.core.photos.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
