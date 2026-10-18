"""Lifecycle failure checks; no real services, signals, volume or audio."""
import contextlib
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import runtime


class RuntimeServiceTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.state = Path(directory)
        self.enterContext(patch.object(runtime, 'STATE', self.state))
        self.record = self.state / 'brain.json'

    def invoke(self, action):
        with patch('sys.argv', ['runtime.py', action, 'brain']), contextlib.redirect_stdout(io.StringIO()) as output:
            runtime.main()
        return output.getvalue()

    def existing(self):
        runtime.save(self.record, {'pid': 12345, 'identity': 'owned-service'})

    def test_term_survivor_retains_ownership_and_cannot_duplicate(self):
        self.existing()
        with patch.object(runtime, 'identity', return_value='owned-service'), \
             patch.object(runtime.os, 'getpgid', return_value=12345), \
             patch.object(runtime.os, 'killpg') as signals, \
             patch.object(runtime.subprocess, 'Popen') as spawn:
            self.assertIn('still running', self.invoke('stop'))
            self.assertTrue(json.loads(self.record.read_text())['stopping'])
            self.assertTrue(json.loads(self.invoke('status'))['running'])
            self.assertIn('already running', self.invoke('start'))
            spawn.assert_not_called()
            signals.assert_called_once_with(12345, signal.SIGTERM)

    def test_stop_removes_record_only_after_group_is_gone(self):
        self.existing()
        with patch.object(runtime, 'identity', side_effect=['owned-service', None]), \
             patch.object(runtime, 'group_alive', return_value=False), \
             patch.object(runtime.os, 'getpgid', return_value=12345), \
             patch.object(runtime.os, 'killpg'):
            self.assertIn('stopped', self.invoke('stop'))
        self.assertFalse(self.record.exists())

    def test_failed_inspection_preserves_record_and_blocks_new_start(self):
        self.existing()
        before = self.record.read_bytes()
        with patch.object(runtime, 'identity', side_effect=runtime.InspectionError('inspection failed')), \
             patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaises(runtime.InspectionError):
                self.invoke('start')
            spawn.assert_not_called()
        self.assertEqual(self.record.read_bytes(), before)

    def test_surviving_group_without_leader_blocks_new_start(self):
        self.existing()
        with patch.object(runtime, 'identity', return_value=None), \
             patch.object(runtime, 'group_alive', return_value=True), \
             patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaises(runtime.InspectionError):
                self.invoke('start')
            spawn.assert_not_called()
        self.assertTrue(self.record.exists())

    def test_startup_inspection_failure_rolls_back_new_group(self):
        process = Mock(pid=23456)
        process.poll.return_value = None
        with patch.object(runtime, 'commands', return_value={'brain': ['fake-service']}), \
             patch.object(runtime.subprocess, 'Popen', return_value=process), \
             patch.object(runtime.time, 'sleep'), \
             patch.object(runtime, 'identity', side_effect=runtime.InspectionError('failed')), \
             patch.object(runtime, 'group_alive', return_value=False), \
             patch.object(runtime.os, 'killpg') as signals:
            with self.assertRaises(SystemExit):
                self.invoke('start')
            signals.assert_called_once_with(23456, signal.SIGKILL)
            process.wait.assert_called_once_with(timeout=2)
        self.assertFalse(self.record.exists())

    def test_failed_rollback_retains_provisional_recovery_record(self):
        process = Mock(pid=23456)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('fake-service', 2)
        with patch.object(runtime, 'commands', return_value={'brain': ['fake-service']}), \
             patch.object(runtime.subprocess, 'Popen', return_value=process), \
             patch.object(runtime.time, 'sleep'), \
             patch.object(runtime, 'identity', side_effect=runtime.InspectionError('failed')), \
             patch.object(runtime.os, 'killpg'):
            with self.assertRaises(SystemExit):
                self.invoke('start')
        self.assertEqual(json.loads(self.record.read_text()), {'pid': 23456, 'identity': None})

    def test_exited_launcher_still_cleans_its_surviving_process_group(self):
        process = Mock(pid=23456)
        process.poll.return_value = 0
        with patch.object(runtime, 'commands', return_value={'brain': ['fake-service']}), \
             patch.object(runtime.subprocess, 'Popen', return_value=process), \
             patch.object(runtime.time, 'sleep'), \
             patch.object(runtime, 'identity') as identity, \
             patch.object(runtime, 'group_alive', return_value=False), \
             patch.object(runtime.os, 'killpg') as signals:
            with self.assertRaises(SystemExit):
                self.invoke('start')
            identity.assert_not_called()
            signals.assert_called_once_with(23456, signal.SIGKILL)
            process.wait.assert_called_once_with(timeout=2)
        self.assertFalse(self.record.exists())

    def test_ps_error_and_absence_are_distinct(self):
        with patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            self.assertIsNone(runtime.identity(12345))
        with patch.object(runtime.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ps', 2)):
            with self.assertRaises(runtime.InspectionError):
                runtime.identity(12345)
        with patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, '', 'unavailable')):
            with self.assertRaises(runtime.InspectionError):
                runtime.identity(12345)


if __name__ == '__main__':
    unittest.main()
