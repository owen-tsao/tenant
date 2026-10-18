"""Explicit isolated queue/continuation checks. Synthetic bridges only."""
import asyncio
from types import SimpleNamespace
import unittest

from brain.core.device_metadata import update_metadata
import test_native_devices as native_fixtures
import test_room_programs as program_fixtures
from test_room_program_sync import Clock
import test_song_programs as song_fixtures
import test_conversation_speech as speech_fixtures


def update(owner, device_id, **values):
    core = SimpleNamespace(registry=owner.registry, agent=SimpleNamespace(),
                           config=SimpleNamespace(host_token='host-private', device_token='device-private'))
    return update_metadata(core, device_id, values)


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


class SpeechSchedulingChecks(unittest.IsolatedAsyncioTestCase):
    setUp = speech_fixtures.SpeechTests.setUp
    asyncTearDown = speech_fixtures.SpeechTests.asyncTearDown
    register = speech_fixtures.SpeechTests.register
    grant = speech_fixtures.SpeechTests.grant
    enable = speech_fixtures.SpeechTests.enable
    reply = speech_fixtures.SpeechTests.reply
    status = speech_fixtures.SpeechTests.status

    async def test_scheduled_narration_cannot_survive_host_revoke_before_task_starts(self):
        speaker = self.register()
        self.enable(speaker)
        old_reply = self.reply(turn_id='before-host-policy-change')
        queued = self.speech.schedule_reply(old_reply)
        # No yield: the native reply was queued, but the speech task has not run.
        update(self, speaker.device.id, allowed=False)
        update(self, speaker.device.id, allowed=True)
        await queued
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.status(), 'POLICY_CHANGED')
        self.assertIsNone(self.speech.schedule_reply(old_reply))
        fresh = self.reply(turn_id='fresh-after-host-reenable')
        await self.speech.schedule_reply(fresh)
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(self.status(), 'ACKNOWLEDGED')


class NativeQueueChecks(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native_fixtures.NativeDeviceTests.asyncSetUp
    asyncTearDown = native_fixtures.NativeDeviceTests.asyncTearDown
    call = native_fixtures.NativeDeviceTests.call

    async def test_outer_logical_queue_keeps_original_metadata_revision(self):
        self.tools.action_timeout = 1
        lock = self.tools.device_locks['phone']
        await lock.acquire()
        task = asyncio.create_task(self.tools.dispatch(self.call()))
        try:
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            update(self, 'phone', allowed=False)
            update(self, 'phone', allowed=True)
        finally:
            lock.release()
        result = await task
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual(self.phone.frames, [])
        fresh = await self.tools.dispatch(self.call(request_id='fresh-off', args={'on': False}))
        self.assertTrue(fresh['ok'], fresh)
        self.assertEqual([f['args'] for f in self.phone.frames], [{'on': False}])

    async def test_blink_sleep_does_not_resume_after_host_reenable(self):
        paused, resume = asyncio.Event(), asyncio.Event()
        async def hold(_seconds):
            paused.set()
            await resume.wait()
        self.tools._blink_sleep = hold
        task = asyncio.create_task(self.tools.dispatch({'token': self.grant.token, 'operation': 'light-blink',
            'request_id': 'blink', 'device_id': 'phone', 'count': 2}))
        await paused.wait()
        update(self, 'phone', allowed=False)
        update(self, 'phone', allowed=True)
        resume.set()
        result = await task
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual([f['args'] for f in self.phone.frames], [{'on': True}])
        fresh = await self.tools.dispatch(self.call(request_id='fresh-off', args={'on': False}))
        self.assertTrue(fresh['ok'], fresh)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})

    async def test_duplicate_inflight_result_survives_later_metadata_change_without_resend(self):
        self.phone.auto = False
        self.tools.action_timeout = 1
        first = asyncio.create_task(self.tools.dispatch(self.call()))
        await self.phone.sent.wait()
        update(self, 'phone', location='Shelf')
        duplicate = asyncio.create_task(self.tools.dispatch(self.call()))
        await asyncio.sleep(0)
        frame = self.phone.frames[0]
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': frame['req'], 'result': {'on': True}})
        self.assertEqual(await first, await duplicate)
        self.assertEqual(len(self.phone.frames), 1)


class ProgramQueueChecks(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = program_fixtures.ProgramTests.asyncSetUp
    asyncTearDown = program_fixtures.ProgramTests.asyncTearDown
    grant_for = program_fixtures.ProgramTests.grant_for
    register = program_fixtures.ProgramTests.register
    start = program_fixtures.ProgramTests.start
    update = program_fixtures.ProgramTests.update

    async def test_program_control_queue_keeps_original_target_revision(self):
        await self.engine._control.acquire()
        task = asyncio.create_task(self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'queued', 'device_id': 'laptop', 'bpm': 60}))
        try:
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            update(self, 'laptop', allowed=False)
            update(self, 'laptop', allowed=True)
        finally:
            self.engine._control.release()
        result = await task
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual(self.audio.frames, [])
        self.assertEqual(self.engine.programs, {})

    async def test_generated_pulse_stops_after_metadata_change_but_fresh_cleanup_is_allowed(self):
        timeline = Clock()
        self.engine.clock, self.engine.sleep = timeline, timeline.sleep
        async def hold_monitor(_program):
            await asyncio.Event().wait()
        self.engine._monitor = hold_monitor
        program = await self.start(bpm=60)
        program.phase = 100
        timeline.advance_to(100.37)
        attach = asyncio.create_task(self.update(program, light_device_id='phone'))
        await until(lambda: any(abs(due - 101) < 1e-6 for due, _ in timeline.waiters))
        timeline.advance_to(101)
        await until(lambda: bool(self.phone.frames))
        self.assertTrue(self.phone.frames[0]['args']['on'])
        await until(lambda: any(abs(due - 101.5) < 1e-6 for due, _ in timeline.waiters))
        update(self, 'phone', allowed=False)
        update(self, 'phone', allowed=True)
        timeline.advance_to(101.5)
        result = await attach
        self.assertFalse(result['ok'], result)
        await program.cleanup_task
        self.assertEqual(sum(frame['args']['on'] for frame in self.phone.frames), 1)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
        # This fresh OFF owns its own current authority, not the stale pulse guard.
        fresh = await self.engine.explicit_off(self.grant, 'phone', authorized=lambda: True, timeout=.2)
        self.assertTrue(fresh['ok'], fresh)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
        stopped = await self.engine.dispatch(self.grant, 'program-stop',
            {'request_id': 'fresh-stop', 'program_id': program.id})
        self.assertTrue(stopped['ok'], stopped)

    async def test_audio_monitor_invalidates_old_run_after_metadata_change(self):
        program = await self.start(bpm=60)
        await asyncio.sleep(0)
        update(self, 'laptop', output_description='Host updated the current output description')
        await until(lambda: program.cleanup_task is not None)
        await program.cleanup_task
        self.assertFalse(program.active)
        self.assertEqual([frame['cap'] for frame in self.audio.frames], ['beat.prepare', 'beat.start', 'beat.stop'])


class SongContinuationChecks(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = song_fixtures.SongProgramTests.asyncSetUp
    asyncTearDown = song_fixtures.SongProgramTests.asyncTearDown
    grant_for = song_fixtures.SongProgramTests.grant_for
    register = song_fixtures.SongProgramTests.register
    register_song = song_fixtures.SongProgramTests.register_song
    update = song_fixtures.SongProgramTests.update
    start_song = song_fixtures.SongProgramTests.start_song
    running = song_fixtures.SongProgramTests.running

    async def test_song_pulses_never_resume_old_target_after_metadata_change(self):
        program = await self.running()
        attach = asyncio.create_task(self.update(program, light_device_id='phone'))
        await until(lambda: any(frame['args'].get('on') is True for frame in self.phone.frames))
        before = sum(frame['args'].get('on') is True for frame in self.phone.frames)
        update(self, 'phone', allowed=False)
        update(self, 'phone', allowed=True)
        await until(lambda: program.cleanup_task is not None)
        await program.cleanup_task
        await attach
        self.assertEqual(sum(frame['args'].get('on') is True for frame in self.phone.frames), before)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
