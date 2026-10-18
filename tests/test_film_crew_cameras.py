"""Local setup tests only. No network, OBS, browser, camera or phone access."""
from pathlib import Path
import stat
import tempfile
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from PIL import Image
import qrcode

from film_crew.cameras import (CameraManifestError, SOURCE_NAMES, load_manifest,
                               prepare_manifest, validate_manifest)


class FilmCrewCameraTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.runtime = Path(self.temporary) / 'private'
        self.manifest = prepare_manifest(self.runtime)
        self.path = self.runtime / 'cameras.json'

    def value(self):
        return self.manifest.to_private_dict()

    def replace_query(self, entry, kind, **changes):
        key = kind + '_url'
        url = urlsplit(entry[key])
        params = {name: values[0] for name, values in parse_qs(url.query, keep_blank_values=True).items()}
        params.update(changes)
        entry[key] = 'https://vdo.ninja/?' + urlencode(params)

    def assert_invalid(self, value):
        with self.assertRaises(CameraManifestError) as caught:
            validate_manifest(value)
        message = str(caught.exception)
        for feed in self.manifest.feeds:
            for url in (feed.push_url, feed.view_url):
                for private in parse_qs(urlsplit(url).query).values():
                    if len(private[0]) >= 24:
                        self.assertNotIn(private[0], message)

    def test_two_distinct_identity_pairs_and_source_names(self):
        self.assertEqual([feed.role for feed in self.manifest.feeds], ['wide', 'detail'])
        ids, passwords = [], []
        for feed in self.manifest.feeds:
            push = parse_qs(urlsplit(feed.push_url).query, keep_blank_values=True)
            view = parse_qs(urlsplit(feed.view_url).query, keep_blank_values=True)
            self.assertEqual(push['push'], view['view'])
            self.assertEqual(push['password'], view['password'])
            self.assertEqual(feed.source_name, SOURCE_NAMES[feed.role])
            ids.extend(push['push'])
            passwords.extend(push['password'])
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(len(set(passwords)), 2)
        self.assertEqual(self.manifest.feed('detail').role, 'detail')

    def test_vendor_video_only_rear_preview_and_reconnect_options(self):
        for feed in self.manifest.feeds:
            push = parse_qs(urlsplit(feed.push_url).query, keep_blank_values=True)
            view = parse_qs(urlsplit(feed.view_url).query, keep_blank_values=True)
            self.assertEqual(push['audiodevice'], ['0'])
            self.assertEqual(push['vdo'], ['back'])
            self.assertIn('webcam', push)
            self.assertNotIn('autostart', push)
            self.assertEqual(push['maxframerate'], ['30'])
            self.assertEqual((push['width'], push['height']), (['1280'], ['720']))
            self.assertIn('noaudio', view)
            self.assertEqual(view['retry'], ['10'])
            self.assertEqual(view['retrytimeout'], ['5000'])
            for params in (push, view):
                self.assertNotIn('room', params)
                self.assertNotIn('api', params)
                self.assertNotIn('record', params)

    def test_private_artifacts_and_exact_qr_payloads(self):
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        for feed in self.manifest.feeds:
            path = self.runtime / (feed.role + '-phone-qr.png')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            # Compare pixels against a separately rendered QR for the exact URL,
            # including its password. This catches swapped/incorrect QR payloads.
            with Image.open(path) as actual:
                actual.load()
                expected = qrcode.make(feed.push_url, box_size=8, border=4).convert('1')
                self.assertEqual(actual.convert('1').size, expected.size)
                self.assertEqual(actual.convert('1').tobytes(), expected.tobytes())

    def test_load_and_repeat_prepare_preserve_links_and_valid_manifest(self):
        original = self.path.read_bytes()
        loaded = load_manifest(self.path)
        repeated = prepare_manifest(self.runtime)
        self.assertEqual(loaded, self.manifest)
        self.assertEqual(repeated, loaded)
        self.assertEqual(self.path.read_bytes(), original)
        (self.runtime / 'wide-phone-qr.png').unlink()
        self.assertEqual(prepare_manifest(self.runtime), loaded)
        self.assertTrue((self.runtime / 'wide-phone-qr.png').is_file())

    def test_object_reprs_never_include_urls_ids_or_passwords(self):
        for feed in self.manifest.feeds:
            representation = repr(self.manifest) + repr(feed)
            self.assertNotIn('https://', representation)
            params = parse_qs(urlsplit(feed.push_url).query)
            self.assertNotIn(params['push'][0], representation)
            self.assertNotIn(params['password'][0], representation)

    def test_reject_duplicate_role_source_and_shared_feed_identity(self):
        for field in ('role', 'source_name', 'push_url', 'view_url'):
            value = self.value()
            value['feeds'][1][field] = value['feeds'][0][field]
            self.assert_invalid(value)
        value = self.value()
        value['feeds'][1].update({key: value['feeds'][0][key] for key in ('push_url', 'view_url')})
        self.assert_invalid(value)

    def test_reject_mismatched_viewer_and_reused_password(self):
        value = self.value()
        self.replace_query(value['feeds'][0], 'view', view='Z' * 24)
        self.assert_invalid(value)
        value = self.value()
        first_password = parse_qs(urlsplit(value['feeds'][0]['push_url']).query)['password'][0]
        for direction in ('push', 'view'):
            self.replace_query(value['feeds'][1], direction, password=first_password)
        self.assert_invalid(value)

    def test_reject_audio_enabling_unexpected_origin_and_query_injection(self):
        mutations = [lambda entry: self.replace_query(entry, 'push', audiodevice='1'),
                     lambda entry: self.replace_query(entry, 'view', noaudio='false'),
                     lambda entry: self.replace_query(entry, 'push', api='unexpected-control'),
                     lambda entry: entry.update(push_url=entry['push_url'].replace('https:', 'http:')),
                     lambda entry: entry.update(view_url=entry['view_url'].replace('vdo.ninja', 'vdo.ninja.evil')),
                     lambda entry: entry.update(view_url=entry['view_url'] + '&view=another'),
                     lambda entry: entry.update(view_url=entry['view_url'] + '#password=other')]
        for mutate in mutations:
            with self.subTest(case=mutations.index(mutate)):
                value = self.value()
                mutate(value['feeds'][0])
                self.assert_invalid(value)

    def test_optional_viewer_h264_and_vp8_preserve_phone_identity_and_options(self):
        original = self.value()
        for codec in ('h264', 'vp8'):
            value = self.value()
            for entry in value['feeds']:
                self.replace_query(entry, 'view', codec=codec)
            validated = validate_manifest(value)
            for before, after in zip(self.manifest.feeds, validated.feeds):
                self.assertEqual(after.push_url, before.push_url)
                self.assertEqual(after.source_name, before.source_name)
                query = parse_qs(urlsplit(after.view_url).query, keep_blank_values=True)
                self.assertEqual(query['codec'], [codec])
                self.assertIn('noaudio', query)
            self.assertEqual(validate_manifest(original), self.manifest)

    def test_reject_unsupported_duplicate_or_sender_codec(self):
        for codec in ('', 'H264', 'h265', 'vp9', 'h264,vp8'):
            value = self.value()
            self.replace_query(value['feeds'][0], 'view', codec=codec)
            self.assert_invalid(value)
        value = self.value()
        self.replace_query(value['feeds'][0], 'push', codec='h264')
        self.assert_invalid(value)
        value = self.value()
        value['feeds'][0]['view_url'] += '&codec=h264&codec=vp8'
        self.assert_invalid(value)

    def test_loading_and_preparing_codec_manifest_preserves_credentials_and_qrs(self):
        value = self.value()
        qr_bytes = {feed.role: (self.runtime / (feed.role + '-phone-qr.png')).read_bytes()
                    for feed in self.manifest.feeds}
        for entry in value['feeds']:
            self.replace_query(entry, 'view', codec='h264')
        import json
        self.path.write_text(json.dumps(value))
        loaded = load_manifest(self.path)
        self.assertEqual(prepare_manifest(self.runtime), loaded)
        for before, after in zip(self.manifest.feeds, loaded.feeds):
            self.assertEqual(after.push_url, before.push_url)
            self.assertEqual((self.runtime / (after.role + '-phone-qr.png')).read_bytes(), qr_bytes[after.role])
        self.assertEqual(loaded.to_private_dict(), value)

    def test_reject_missing_extra_and_invalid_manifest_fields(self):
        for value in (None, [], {}, {'schema_version': True, 'feeds': self.value()['feeds']},
                      {**self.value(), 'status': 'live'},
                      {'schema_version': 1, 'feeds': self.value()['feeds'][:1]}):
            self.assert_invalid(value)
        for key in self.value()['feeds'][0]:
            value = self.value()
            del value['feeds'][0][key]
            self.assert_invalid(value)
        with self.assertRaises(CameraManifestError):
            self.manifest.feed('third')

    def test_invalid_existing_manifest_fails_without_rotation(self):
        self.path.write_text('{"secret":"do-not-print","schema_version":1}')
        before = self.path.read_bytes()
        with self.assertRaises(CameraManifestError) as caught:
            prepare_manifest(self.runtime)
        self.assertNotIn('do-not-print', str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)

    def test_reject_public_symlink_and_duplicate_json_manifests(self):
        self.path.chmod(0o644)
        with self.assertRaises(CameraManifestError):
            load_manifest(self.path)
        self.path.chmod(0o600)
        alias = self.runtime / 'alias.json'
        alias.symlink_to(self.path)
        with self.assertRaises(CameraManifestError):
            load_manifest(alias)
        directory_alias = Path(self.temporary) / 'alias-dir'
        directory_alias.symlink_to(self.runtime)
        with self.assertRaises(CameraManifestError):
            prepare_manifest(directory_alias)
        self.path.write_text('{"schema_version":1,"schema_version":1,"feeds":[]}')
        with self.assertRaises(CameraManifestError):
            load_manifest(self.path)


if __name__ == '__main__':
    unittest.main()
