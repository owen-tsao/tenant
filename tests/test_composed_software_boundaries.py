"""Cross-feature authority/UNKNOWN boundaries on real Core and fake bridges.

Native turns, song clocks, light acknowledgements and image bytes are synthetic.
No browser, model, camera, media player, remote source or physical output runs.
Individual readiness, inventory and metadata queue checks live in their existing
photo/device suites; these checks cover only the shared lifecycle and Bus fence.
"""
import asyncio
from dataclasses import replace
import unittest
from unittest.mock import patch

from agent.beat_audio import capabilities as beat_capabilities
from agent.song_audio import capabilities as song_capabilities
from brain.config import Config
from brain.core.device_metadata import update_metadata
from brain.core.photos import CAPTURE_ARGS, PhotoError
from brain.main import create_app
from test_room_conversation import Clock, NativeSession, settings_for
from test_song_programs import SongSocket


class PhotoLightSocket:
    def __init__(self, core):
        self.core, self.frames = core, []
        self.sent = asyncio.Queue()
        self.ack_light = True

    async def send_json(self, frame):
        self.frames.append(frame)
        self.sent.put_nowait(frame)
        # Captures deliberately wait for the test's correlated ACK/upload.
        if frame['cap'] == 'light' and self.ack_light:
            self.core.bus.receive(self.device, {'type': 'ok', 'req': frame['req'],
                                                'result': dict(frame['args'])})


class ComposedSoftwareBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.native, self.clock = NativeSession(), Clock()
        self.native.auto_finish = False
        settings = replace(settings_for(self.native), turn_timeout=4)
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                              conversation=settings)
        self.core = self.app.state.core
        self.core.leases.clock = self.clock
        self.core.photos.clock = self.clock
        self.core.photos.normalizer = lambda body, content_type: b'synthetic-normalized-pixels'
        self.core.photos.capture_timeout = .05
        self.tools = self.core.agent.device_tools
        self.engine = self.core.agent.programs
        self.engine.action_timeout = .05
        self.engine.audio_queue_timeout = .3
        self.lease = self.core.leases.create()
        self.audio = SongSocket(self.core.bus)
        self.audio.device = self.core.registry.register({'type': 'hello', 'id': 'song-mac',
            'label': 'Synthetic recording bridge', 'room': 'TEST', 'caps': {
                **beat_capabilities(), **song_capabilities(self.audio.recording)}}, self.audio)
        self.phone = PhotoLightSocket(self.core)
        self.phone.device = self.core.registry.register({'type': 'hello', 'id': 'shared-phone',
            'label': 'Synthetic photo and light bridge', 'room': 'TEST', 'caps': {
                'light': {'description': 'Light', 'args': {'on': {'type': 'boolean'}}},
                'camera.capture': {'description': 'One consented still', 'args': CAPTURE_ARGS}}}, self.phone)
        self.core.photos.configure('shared-phone', 'room-viewer')
        self.viewer = self.core.photos.enroll_viewer('room-viewer')
        self.core.photos.device_event(self.phone.device,
                                     {'type': 'photo.consent', 'enabled': True, 'ready': True})
        self.turn = asyncio.create_task(self.core.agent.turn(self.lease.guest_id, 'Synthetic boundary check.'))
        await asyncio.wait_for(self.native.started.wait(), 1)
        self.grant = next(iter(self.tools._grants.values()))
        self.pending = []

    async def asyncTearDown(self):
        for task in self.pending + [self.turn]:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.pending, self.turn, return_exceptions=True)
        self.core.photos.close()
        await self.core.agent.close()

    async def helper(self, operation, request_id, **payload):
        return await self.tools.dispatch({'token': self.grant.token, 'operation': operation,
                                         'request_id': request_id, **payload})

    async def start_song(self):
        result = await self.helper('program-start', 'song-start', device_id='song-mac',
                                   song_id='selected-recording')
        self.assertTrue(result['ok'], result)
        return self.engine.programs[result['result']['program_id']]

    def capture_task(self):
        task = asyncio.create_task(self.helper('photo-capture', 'photo-start',
                                               source_device_id='shared-phone'))
        self.pending.append(task)
        return task

    def acknowledge(self, frame):
        result = ({'capture_id': frame['args']['capture_id'], 'state': 'captured'}
                  if frame['cap'] == 'camera.capture' else dict(frame['args']))
        self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': frame['req'], 'result': result})

    async def test_core_revoke_fences_running_song_and_sent_photo_before_late_completion(self):
        program = await self.start_song()
        self.core.photos.capture_timeout = .5
        pending = self.capture_task()
        frame = await asyncio.wait_for(self.phone.sent.get(), 1)
        self.assertEqual(frame['cap'], 'camera.capture')
        record = self.core.photos.pending
        self.assertTrue(record.sent)
        self.core.revoke(self.lease.guest_id)
        # Both effects lose authority synchronously, before cleanup can run.
        self.assertFalse(program.active)
        self.assertIsNone(self.core.photos.pending)
        self.assertEqual(record.state, 'cancelled')
        self.assertFalse(self.tools.permitted(self.grant))
        with self.assertRaises(PhotoError) as denied_upload:
            await self.core.photos.upload(frame['args']['capture_id'], frame['args']['upload_token'],
                                           b'synthetic-input-pixels', 'image/jpeg')
        self.assertEqual(denied_upload.exception.code, 'STALE')
        self.acknowledge(frame)
        self.assertEqual((await asyncio.wait_for(pending, 1))['state'], 'cancelled')
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(program.cleanup['audio'], 'confirmed')
        self.assertIsNone(self.core.photos.viewer_state(self.viewer)['photo'])
        self.assertIsNone(self.core.photos.latest)
        self.assertEqual([item['cap'] for item in self.audio.frames].count('song.start'), 1)
        self.assertEqual([item['cap'] for item in self.audio.frames].count('song.stop'), 1)
        self.assertEqual([item['cap'] for item in self.phone.frames], ['camera.capture'])

    async def test_photo_queued_before_host_deny_cannot_revive_after_reenable(self):
        await self.grant.lock.acquire()
        pending = self.capture_task()
        try:
            await asyncio.sleep(0)
            self.assertTrue(self.grant.lock._waiters)
            self.assertFalse(pending.done())
            update_metadata(self.core, 'shared-phone', {'allowed': False})
            update_metadata(self.core, 'shared-phone', {'allowed': True})
        finally:
            self.grant.lock.release()
        result = await asyncio.wait_for(pending, 1)
        self.assertEqual(result['code'], 'PERMISSION', result)
        self.assertEqual(self.phone.frames, [])
        self.assertIsNone(self.core.photos.pending)
        self.assertIsNone(self.core.photos.latest)

    async def test_unknown_photo_blocks_song_phone_attach_even_after_late_ack(self):
        program = await self.start_song()
        response = await self.capture_task()
        self.assertEqual(response['code'], 'UNKNOWN', response)
        frame = self.phone.frames[0]
        self.assertIn(frame['req'], self.core.bus.uncertain)
        self.acknowledge(frame)
        self.assertNotIn(frame['req'], self.core.bus.uncertain)
        attached = await self.helper('program-update', 'fresh-attach', program_id=program.id,
                                     light_device_id='shared-phone')
        self.assertEqual(attached['code'], 'UNKNOWN', attached)
        self.assertEqual([item['cap'] for item in self.phone.frames], ['camera.capture'])
        # The independent, acknowledged recording continues without replay.
        self.assertTrue(program.active)
        status = await self.helper('program-status', 'song-status', program_id=program.id)
        self.assertTrue(status['ok'], status)
        self.assertEqual([item['cap'] for item in self.audio.frames].count('song.start'), 1)
        self.assertNotIn('song.stop', [item['cap'] for item in self.audio.frames])
        self.assertIsNone(self.core.photos.pending)
        self.assertIsNone(self.core.photos.latest)

    async def test_admitted_photo_rechecks_phone_unknown_after_wait_and_late_ack(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original_call = self.core.bus.call
        self.phone.ack_light = False
        self.tools.action_timeout = .03
        self.core.photos.capture_timeout = .3

        async def hold_camera(device_id, cap, args, *positional, **options):
            if cap == 'camera.capture':
                entered.set()
                await release.wait()
            return await original_call(device_id, cap, args, *positional, **options)

        with patch.object(self.core.bus, 'call', hold_camera):
            pending = self.capture_task()
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertIsNotNone(self.core.photos.pending)
                self.assertFalse(self.core.photos.pending.sent)
                light = await self.helper('call', 'light-unknown-during-photo', device_id='shared-phone',
                                           cap='light', args={'on': True})
                self.assertEqual(light['code'], 'UNKNOWN', light)
                frame = self.phone.frames[0]
                self.assertEqual(frame['cap'], 'light')
                self.assertIn(frame['req'], self.core.bus.uncertain)
                self.acknowledge(frame)
                self.assertNotIn(frame['req'], self.core.bus.uncertain)
                self.assertIn('shared-phone', self.grant.unknown_devices)
            finally:
                release.set()
            photo = await asyncio.wait_for(pending, 1)
        self.assertEqual(photo['code'], 'PERMISSION', photo)
        self.assertFalse(photo['sent'])
        self.assertEqual([item['cap'] for item in self.phone.frames], ['light'])
        self.assertIsNone(self.core.photos.pending)
        self.assertIsNone(self.core.photos.latest)

    async def test_unknown_song_phone_attach_blocks_photo_even_after_late_ack(self):
        program = await self.start_song()
        self.phone.ack_light = False
        response = await self.helper('program-update', 'attach-unknown', program_id=program.id,
                                     light_device_id='shared-phone')
        self.assertEqual(response['code'], 'UNKNOWN', response)
        self.assertIn('shared-phone', response['unknown_device_ids'])
        frame = self.phone.frames[0]
        self.assertEqual((frame['cap'], frame['args']['on']), ('light', True))
        self.assertIn(frame['req'], self.core.bus.uncertain)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.acknowledge(frame)
        self.assertNotIn(frame['req'], self.core.bus.uncertain)
        photo = await self.helper('photo-capture', 'fresh-photo', source_device_id='shared-phone')
        self.assertEqual(photo['code'], 'UNKNOWN', photo)
        self.assertFalse(program.active)
        self.assertEqual([item['cap'] for item in self.phone.frames], ['light'])
        self.assertIsNone(self.core.photos.pending)
        self.assertEqual(self.core.photos.records, {})
        self.assertEqual([item['cap'] for item in self.audio.frames].count('song.start'), 1)


if __name__ == '__main__':
    unittest.main()
