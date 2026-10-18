import json
from pathlib import Path
import tempfile
import unittest

from film_crew.config import ConfigError, load_obs_config


class ObsConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'obs.json'
        self.value = dict(host='127.0.0.1', port=4455, password='private-test-password')

    def write(self):
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o600)

    def test_local_credentials_load_without_repr_leak(self):
        self.write()
        config = load_obs_config(self.path)
        self.assertEqual(config.password, self.value['password'])
        self.assertNotIn(self.value['password'], repr(config))
        self.assertEqual(config.collection, 'Tenant Film Crew')

    def test_wrong_endpoint_auth_or_collection_is_rejected_privately(self):
        for key, invalid in [('host', '192.0.2.1'), ('password', ''),
                             ('port', True), ('port', 1), ('collection', 'Personal')]:
            with self.subTest(key=key, value=invalid):
                value = self.value.copy()
                value[key] = invalid
                self.path.write_text(json.dumps(value)); self.path.chmod(0o600)
                with self.assertRaises(ConfigError) as error:
                    load_obs_config(self.path)
                self.assertNotIn(self.value['password'], str(error.exception))

    def test_shared_symlink_duplicate_and_missing_files_are_rejected(self):
        with self.assertRaises(ConfigError):
            load_obs_config(self.path)
        self.write(); self.path.chmod(0o644)
        with self.assertRaises(ConfigError):
            load_obs_config(self.path)
        self.path.chmod(0o600)
        link = self.path.with_name('link.json'); link.symlink_to(self.path)
        with self.assertRaises(ConfigError):
            load_obs_config(link)
        self.path.write_text('{"host":"127.0.0.1","host":"localhost","port":4455,"password":"secret"}')
        with self.assertRaises(ConfigError):
            load_obs_config(self.path)
