"""Judge-facing text is ordinary language; technical correlation stays private."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit, parse_qs

from brain.core.bus import Result
from brain.core.copy import confirmed_sentence, failure_sentence
from brain.core.log import EventLog
from test_access_core import (Clock, HEADERS, ORIGIN, Planner,
                              make_app, register)
from fastapi.testclient import TestClient


class ResultCopyTests(unittest.TestCase):
    def setUp(self):
        self.dev = SimpleNamespace(id='internal_device_884', label='Jay phone')

    def test_light_uses_observed_state_even_when_request_differed(self):
        self.assertEqual(confirmed_sentence(self.dev, 'light', {'on': True}, {'on': False}),
                         'Jay phone turned its flashlight off.')
        self.assertEqual(confirmed_sentence(self.dev, 'light', {'on': True}, {}),
                         'Jay phone confirmed the request.')
        self.assertEqual(confirmed_sentence(self.dev, 'light', {'on': True}, {'on': 1}),
                         'Jay phone confirmed the request.')

    def test_pause_and_speech_do_not_claim_more_than_acknowledgment(self):
        cases = [('music.play', {'state': 'playing'}, 'Jay phone started playing music.'),
                 ('music.pause', {'state': 'paused'}, 'Jay phone paused the music.'),
                 ('music.pause', {'state': 'stopped'}, 'Jay phone confirmed the music is stopped.'),
                 ('say', {'spoken': True, 'audible_verified': False},
                  'Jay phone reported that speech playback finished.')]
        for cap, payload, sentence in cases:
            with self.subTest(cap=cap, payload=payload):
                self.assertEqual(confirmed_sentence(self.dev, cap, {'text': 'private words'}, payload), sentence)

    def test_failure_never_echoes_terminal_error_or_internal_identifier(self):
        for code in ('UNKNOWN', 'TIMEOUT', 'PERMISSION', 'OFFLINE', 'FAILED', 'weird_internal_error'):
            sentence = failure_sentence(self.dev, 'music.pause', {}, Result(False, code=code, message='secret traceback'))
            for private in (self.dev.id, 'music.pause', 'secret traceback', code):
                self.assertNotIn(private, sentence)
            if code == 'UNKNOWN':
                self.assertIn('unknown', sentence)
                self.assertIn('did not retry', sentence)
                self.assertNotIn('nothing was sent', sentence)

    def test_private_audit_is_persisted_without_expanding_public_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.jsonl'
            log = EventLog(path, clock=lambda: 123)
            public = log.append('ok', 'Jay phone turned its flashlight off.',
                                device_id=self.dev.id, cap='light', req='r_private_884', ok=True)
            self.assertEqual(public, {'t': 123, 'kind': 'ok', 'text': 'Jay phone turned its flashlight off.'})
            self.assertNotIn('r_private_884', json.dumps(log.rows))
            saved = json.loads(path.read_text())
            self.assertEqual(saved['audit']['req'], 'r_private_884')
            self.assertEqual(saved['audit']['device_id'], self.dev.id)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            log.clear()
            self.assertEqual(log.rows, [])
            self.assertEqual(log.audit_rows, [saved])


class PublicAgentCopyTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_result_keeps_acknowledged_connection_label_across_reconnect(self):
        app, core = make_app()
        original = register(core, 'stable-private-id', auto=False, label='Original phone')
        task = asyncio.create_task(core.host_do({'device_id': 'stable-private-id', 'cap': 'light', 'args': {'on': True}}))
        await original.sent.wait()
        req = original.frames[0]['req']
        core.bus.receive(original.dev, {'type': 'ok', 'req': req, 'result': {'on': True}})
        # Replace the registry entry before the waiting host task resumes.
        core.bus.disconnect(original.dev)
        replacement = register(core, 'stable-private-id', label='Replacement phone')
        self.assertTrue((await task)['ok'])
        self.assertEqual(core.log.rows[-1]['text'], 'Original phone turned its flashlight on.')
        self.assertEqual(core.log.audit_rows[-1]['audit']['req'], req)
        self.assertEqual(replacement.frames, [])

    async def test_action_and_inventory_use_labels_and_ordinary_language(self):
        planner = Planner({'kind': 'action', 'device_id': 'internal-phone-88', 'cap': 'light', 'args': {'on': False}})
        app, core = make_app(planner=planner)
        phone = register(core, 'internal-phone-88', label='Jay phone')
        lease = core.leases.create()
        frames = await core.agent.turn(lease.guest_id, 'turn off Jay phone')
        for frame in frames:
            self.assertEqual(frame['text'], 'Jay phone turned its flashlight off.')
        self.assertEqual(core.log.audit_rows[-1]['audit']['req'], phone.frames[0]['req'])
        public = json.dumps(core.snapshot()['log'])
        for value in ('internal-phone-88', phone.frames[0]['req'], '.light', 'device_id'):
            self.assertNotIn(value, public)
        planner.output = {'kind': 'message', 'text': 'I did something.'}
        help_frames = await core.agent.turn(lease.guest_id, 'what can I do')
        self.assertIn('Jay phone can turn its flashlight on or off.', help_frames[-1]['text'])
        self.assertNotIn('internal-phone-88', help_frames[-1]['text'])

    async def test_alternative_identifiers_are_private_and_labels_are_the_only_choice(self):
        planner = Planner({'kind': 'action', 'device_id': 'private-primary-88', 'cap': 'light', 'args': {'on': True}})
        app, core = make_app(planner=planner)
        primary = register(core, 'private-primary-88', label='Jay phone')
        backup = register(core, 'private-backup-88', label='Owen phone')
        core.bus.disconnect(primary.dev)
        lease = core.leases.create()
        frames = await core.agent.turn(lease.guest_id, 'turn on Jay phone')
        self.assertIn('Owen phone', frames[-1]['text'])
        self.assertNotIn(backup.dev.id, frames[-1]['text'])
        await core.agent.turn(lease.guest_id, backup.dev.id)
        self.assertEqual(backup.frames, [])
        await core.agent.turn(lease.guest_id, 'use Owen phone')
        self.assertEqual(len(backup.frames), 1)

    async def test_duplicate_label_added_after_offer_blocks_yes_confirmation(self):
        planner = Planner()
        app, core = make_app(planner=planner)
        primary = register(core, label='Jay phone')
        core.bus.disconnect(primary.dev)
        backup = register(core, 'private-backup', label='Owen phone')
        lease = core.leases.create()
        await core.agent.turn(lease.guest_id, 'turn on Jay phone')
        other = register(core, 'private-other', label='Owen  phone')
        frames = await core.agent.turn(lease.guest_id, 'yes')
        self.assertIn('different names', frames[-1]['text'])
        self.assertEqual(backup.frames + other.frames, [])
        self.assertNotIn(lease.guest_id, core.agent.pending)


class JoinRoomCopyTests(unittest.TestCase):
    def test_opaque_chat_url_carries_current_room_after_reset_and_secret_only_in_fragment(self):
        app, core = make_app(clock=Clock())
        with TestClient(app, base_url=ORIGIN) as client:
            reset = client.post('/host/reset', headers={'Authorization': 'Bearer host-private'}).json()
            room_code = reset['room_code']
            response = client.post('/join', headers=HEADERS, json={'room_code': room_code})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            url = urlsplit(body['chat_url'])
            self.assertEqual(url.path, '/g/' + body['guest_id'])
            self.assertEqual(parse_qs(url.query), {'room': [room_code]})
            self.assertEqual(parse_qs(url.fragment), {'t': [body['guest_token']]})
            self.assertNotIn(body['guest_token'], url.path + '?' + url.query)
            self.assertNotIn(body['guest_token'], json.dumps(core.snapshot()))


if __name__ == '__main__':
    unittest.main()
