"""Deterministic audio checks: never invoke macOS or produce sound."""
import asyncio
import aifc
import json
import subprocess
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from agent import laptop


def synthetic_speech(path, duration=.05):
    """Silent AIFF bytes only; never invokes a player or the speech engine."""
    with aifc.open(str(path), 'wb') as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(1000)
        clip.writeframes(b'\x00\x00' * round(duration * 1000))


class Runner:
    def __init__(self, stdout='1\n', error=None, speech_duration=.05):
        self.calls = []
        self.stdout = stdout
        self.error = error
        self.speech_duration = speech_duration

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error
        if argv[:2] == ['/usr/bin/say', '-o']:
            synthetic_speech(argv[2], self.speech_duration)
        return subprocess.CompletedProcess(argv, 0, self.stdout, '')


# Tests use only injected subprocess responses; these are protocol/safety
# checks, not evidence of Music availability or audible playback.

class FakeSocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return json.dumps(self.frames.pop(0))


def command(req='r1', cap='say', args=None, epoch=3, deadline_ms=5000):
    return {'type': 'do', 'req': req, 'cap': cap,
            'args': {'text': 'hello'} if args is None else args,
            'epoch': epoch, 'deadline_ms': deadline_ms}

class DispatchTests(unittest.TestCase):
    def make(self, runner=None, playlist='Room', exists=lambda p: True, system='Darwin'):
        self.runner = runner or Runner()
        return laptop.AudioDispatcher(laptop.Config(playlist=playlist), runner=self.runner,
                                      exists=exists, system=system)

    def test_linux_advertises_nothing(self):
        self.assertEqual(self.make(system='Linux').discover(), {})
        self.assertEqual(self.runner.calls, [])

    def test_missing_commands_advertise_nothing(self):
        self.assertEqual(self.make(exists=lambda p: False).discover(), {})

    def test_unconfigured_music_omitted(self):
        caps = self.make(playlist=None).discover()
        self.assertTrue({'say', 'volume'} <= set(caps))
        self.assertNotIn('music.play', caps)
        self.assertNotIn('music.pause', caps)

    def test_empty_media_omitted_and_dispatch_honest(self):
        d = self.make(Runner('0'))
        self.assertNotIn('music.play', d.discover())
        with self.assertRaises(laptop.AudioError) as err:
            d.dispatch('music.play', {})
        self.assertEqual(err.exception.code, 'UNSUPPORTED')

    def test_missing_media_os_error_omits_music(self):
        def runner(argv, **opts):
            return subprocess.CompletedProcess(argv, 1, '', 'File not found')
        d = self.make(runner)
        self.assertNotIn('music.play', d.discover())
        with self.assertRaises(laptop.AudioError):
            d.dispatch('music.play', {})

    def test_missing_music_app_omitted(self):
        d = self.make(exists=lambda p: not p.endswith('Music.app'))
        self.assertNotIn('music.play', d.discover())
        self.assertEqual(self.runner.calls, [])

    def test_discovery_timeout_omits_music(self):
        d = self.make(Runner(error=subprocess.TimeoutExpired('osascript', 1)))
        self.assertNotIn('music.play', d.discover())
        self.assertIn('unknown', d.discovery_error)

    def test_text_passed_as_stdin_never_executable(self):
        d = self.make()
        text = '-o /tmp/pwn; "\n do shell script "touch /tmp/pwn" $(touch x)'
        result = d.dispatch('say', {'text': text})
        argv, opts = self.runner.calls[0]
        self.assertEqual(argv[:2], ['/usr/bin/say', '-o'])
        self.assertEqual(opts['input'], text)
        self.assertNotIn('shell', opts)
        playback, playback_opts = self.runner.calls[1]
        self.assertEqual(playback, ['/usr/bin/afplay', argv[2]])
        self.assertLessEqual(playback_opts['timeout'], opts['timeout'])
        self.assertIsNone(playback_opts['input'])
        self.assertEqual(len(self.runner.calls), 2)
        self.assertFalse(Path(argv[2]).parent.exists())
        self.assertFalse(result['audible_verified'])

    def test_speech_not_advertised_without_default_output_player(self):
        self.assertNotIn('say', self.make(exists=lambda p: p != '/usr/bin/afplay').capabilities())

    def test_speech_render_deadline_prevents_late_physical_playback(self):
        d = self.make()
        with patch('agent.laptop.time.monotonic', side_effect=[0, 1]), self.assertRaises(laptop.AudioError) as err:
            d.dispatch('say', {'text': 'hello'}, timeout=.5)
        self.assertEqual(err.exception.code, 'FAILED')
        self.assertEqual(len(self.runner.calls), 1)
        self.assertFalse(Path(self.runner.calls[0][0][2]).parent.exists())

    def test_playback_timeout_is_unknown_and_not_retried(self):
        calls = []
        def runner(argv, **opts):
            calls.append(argv)
            if argv[0] == '/usr/bin/afplay':
                raise subprocess.TimeoutExpired('afplay', opts['timeout'])
            synthetic_speech(argv[2])
            return subprocess.CompletedProcess(argv, 0, '', '')
        d = self.make(runner)
        with self.assertRaises(laptop.AudioError) as err:
            d.dispatch('say', {'text': 'hello'})
        self.assertEqual(err.exception.code, 'UNKNOWN')
        self.assertEqual([argv[0] for argv in calls], ['/usr/bin/say', '/usr/bin/afplay'])
        self.assertFalse(Path(calls[0][2]).parent.exists())

    def test_real_rendered_duration_allows_ordinary_sentence_with_sufficient_deadline(self):
        d = self.make(Runner(speech_duration=5))
        text = 'Done, I blinked the phone five times and spoke the phrase.'
        with patch('agent.laptop.time.monotonic', side_effect=[0, .1]):
            result = d.dispatch('say', {'text': text}, timeout=15)
        self.assertEqual(self.runner.calls[0][1]['input'], text)
        self.assertEqual(self.runner.calls[0][1]['timeout'], 15)
        self.assertEqual(self.runner.calls[1][1]['timeout'], 14.65)
        self.assertEqual(result['rendered_duration_ms'], 5000)
        self.assertTrue(result['spoken'])
        self.assertFalse(result['audible_verified'])

    def test_playback_can_use_remaining_deadline_for_overhead_beyond_nominal_plus_one(self):
        calls = []
        def runner(argv, **options):
            calls.append((argv, options))
            if argv[0] == '/usr/bin/say':
                synthetic_speech(argv[2], duration=5)
            elif options['timeout'] < 8:
                # A simulated loaded player takes eight seconds for a five-
                # second clip. This fits the real deadline but not duration+1.
                raise subprocess.TimeoutExpired('afplay', options['timeout'])
            return subprocess.CompletedProcess(argv, 0, '', '')
        with patch('agent.laptop.time.monotonic', side_effect=[0, .1]):
            result = self.make(runner).dispatch('say', {'text': 'An ordinary spoken reply.'}, timeout=15)
        self.assertTrue(result['spoken'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1]['timeout'], 14.65)
        self.assertLess(calls[1][1]['timeout'], 15 - .1)

    def test_actual_macos_pcm_render_is_duration_checked_with_explicit_format_flags(self):
        # Captured using render-only say on the room Mac; the default AIFF-C
        # twos file failed aifc. This real standard-AIFF fixture avoids testing
        # only the synthetic writer's supported format. Neither OS tool runs.
        fixture = Path(__file__).parent / 'fixtures' / 'say-pcm-bei16.aiff'
        calls = []
        def runner(argv, **options):
            calls.append((argv, options))
            if argv[:2] == ['/usr/bin/say', '-o']:
                self.assertIn('--file-format=AIFF', argv)
                self.assertIn('--data-format=BEI16', argv)
                Path(argv[2]).write_bytes(fixture.read_bytes())
            else:
                self.assertEqual(argv[0], '/usr/bin/afplay')
            return subprocess.CompletedProcess(argv, 0, '', '')
        with patch('agent.laptop.time.monotonic', side_effect=[0, .1]):
            result = self.make(runner).dispatch('say', {'text': 'Tenant can coordinate'}, timeout=15)
        self.assertEqual(fixture.read_bytes()[8:12], b'AIFF')
        self.assertEqual(result['rendered_duration_ms'], 1139)
        self.assertEqual([argv[0] for argv, _options in calls], ['/usr/bin/say', '/usr/bin/afplay'])
        self.assertEqual(calls[1][1]['timeout'], 14.65)
        self.assertFalse(result['audible_verified'])
        self.assertFalse(Path(calls[0][0][2]).parent.exists())

    def test_actual_clip_that_cannot_fit_is_refused_before_playback(self):
        for duration, elapsed in ((5, .1), (3, 1), (.05, 3.9)):
            with self.subTest(duration=duration, elapsed=elapsed):
                d = self.make(Runner(speech_duration=duration))
                with patch('agent.laptop.time.monotonic', side_effect=[0, elapsed]), self.assertRaises(laptop.AudioError) as err:
                    d.dispatch('say', {'text': 'An ordinary sentence.'}, timeout=4)
                self.assertEqual(err.exception.code, 'FAILED')
                self.assertIn('no audio started', str(err.exception))
                self.assertEqual(len(self.runner.calls), 1)
                self.assertFalse(Path(self.runner.calls[0][0][2]).parent.exists())

    def test_missing_malformed_or_empty_rendered_audio_is_not_played(self):
        for content in (None, b'not an AIFF clip', b'FORM\x00\x00\x00\x04AIFF'):
            calls = []
            def runner(argv, **opts):
                calls.append(argv)
                if content is not None:
                    Path(argv[2]).write_bytes(content)
                return subprocess.CompletedProcess(argv, 0, '', '')
            with self.subTest(content=content), self.assertRaises(laptop.AudioError) as err:
                self.make(runner).dispatch('say', {'text': 'Hello'})
            self.assertEqual(err.exception.code, 'FAILED')
            self.assertEqual(len(calls), 1)
        with self.assertRaises(laptop.AudioError) as err:
            self.make(Runner(speech_duration=0)).dispatch('say', {'text': 'Hello'})
        self.assertEqual(err.exception.code, 'FAILED')
        self.assertEqual(len(self.runner.calls), 1)

    def test_invalid_speech_rejected_before_os(self):
        d = self.make()
        for args in ({}, {'text': ''}, {'text': ' '}, {'text': 'x'*161},
                     {'text': '\x00'}, {'text': 9}, {'text': 'ok', 'extra': 1}, []):
            with self.subTest(args=args), self.assertRaises(laptop.AudioError):
                d.dispatch('say', args)
        self.assertEqual(self.runner.calls, [])

    def test_volume_bounds_and_types(self):
        d = self.make()
        for level in (-1, 101, True, False, 1.2, '20', None, float('nan')):
            with self.subTest(level=level), self.assertRaises(laptop.AudioError):
                d.dispatch('volume', {'level': level})
        self.assertEqual(self.runner.calls, [])

    def test_volume_observed_not_assumed(self):
        d = self.make(Runner('20'))
        self.assertEqual(d.dispatch('volume', {'level': 20})['level'], 20)
        argv, opts = self.runner.calls[-1]
        self.assertEqual(argv[-1], '20')
        self.assertEqual(opts['timeout'], 4.0)
        with self.assertRaises(laptop.AudioError):
            d.dispatch('volume', {'level': 21})

    def test_render_timeout_is_unsent_speech_not_success(self):
        d = self.make(Runner(error=subprocess.TimeoutExpired('say', 1)))
        with self.assertRaises(laptop.AudioError) as err:
            d.dispatch('say', {'text': 'hi'}, timeout=.2)
        self.assertIn('no audio started', str(err.exception))
        self.assertEqual(err.exception.code, 'FAILED')
        self.assertEqual(self.runner.calls[0][1]['timeout'], .2)
        self.assertEqual(len(self.runner.calls), 1)

    def test_missing_binary_fails(self):
        d = self.make(Runner(error=FileNotFoundError()))
        with self.assertRaises(laptop.AudioError) as err:
            d.dispatch('say', {'text': 'hi'})
        self.assertEqual(err.exception.code, 'UNSUPPORTED')

    def test_permission_error_redacted(self):
        def runner(argv, **opts):
            return subprocess.CompletedProcess(argv, 1, '', 'secret user text -1743')
        d = self.make(runner)
        with self.assertRaises(laptop.AudioError) as err:
            d.dispatch('say', {'text': 'hi'})
        self.assertEqual(err.exception.code, 'PERMISSION')
        self.assertNotIn('secret', str(err.exception))

    def test_music_uses_configured_playlist_as_data(self):
        name = 'Room"\n do shell script "bad"'
        d = self.make(playlist=name)
        d.discover()
        self.runner.stdout = 'playing'
        self.assertEqual(d.dispatch('music.play', {})['state'], 'playing')
        argv = self.runner.calls[-1][0]
        self.assertEqual(argv[-1], name)
        self.assertNotIn(name, argv[2])
        self.runner.stdout = 'paused'
        self.assertEqual(d.dispatch('music.pause', {})['state'], 'paused')

    def test_music_rejects_fake_state_or_extra_args(self):
        d = self.make()
        d.discover()
        with self.assertRaises(laptop.AudioError):
            d.dispatch('music.play', {})  # fake runner returns 1, not playing
        with self.assertRaises(laptop.AudioError):
            d.dispatch('music.play', {'name': 'anything'})

    def test_pausing_already_stopped_music_confirms_no_playback(self):
        d = self.make()
        d.discover()
        self.runner.stdout = 'stopped'
        self.assertEqual(d.dispatch('music.pause', {})['state'], 'stopped')


class FakeDispatcher:
    def __init__(self):
        self.calls = []
        self.thread_ids = []
        self.started = threading.Event()
        self.release = None
        self.error = None
    def capabilities(self):
        return {'say': {'description': 'test only', 'args': {'text': {'type': 'string'}}}}
    def dispatch(self, cap, args, timeout=4):
        self.calls.append((cap, args, timeout))
        self.thread_ids.append(threading.get_ident())
        self.started.set()
        if self.release:
            self.release.wait(1)
        if self.error:
            raise self.error
        return {'audible_verified': False}


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dispatcher = FakeDispatcher()
        self.agent = laptop.DeviceAgent(self.dispatcher, '7F3A')

    async def test_correlation_and_off_event_loop(self):
        result = await self.agent.handle(command())
        self.assertEqual((result['type'], result['req']), ('ok', 'r1'))
        self.assertNotEqual(self.dispatcher.thread_ids[0], threading.get_ident())

    async def test_deadline_capped(self):
        await self.agent.handle(command(deadline_ms=125))
        self.assertGreater(self.dispatcher.calls[-1][-1], 0)
        self.assertLessEqual(self.dispatcher.calls[-1][-1], .125)
        await self.agent.handle(command(req='r2', cap='volume', args={'level': 50}, deadline_ms=99000))
        self.assertEqual(self.dispatcher.calls[-1][-1], 4)

    async def test_speech_receives_full_remaining_server_budget_instead_of_four_seconds(self):
        async def immediate_worker(function):
            with patch('agent.laptop.time.monotonic', return_value=1):
                return function()
        with patch('agent.laptop.asyncio.to_thread', new=immediate_worker):
            result = await self.agent.handle(command(deadline_ms=15000), received_at=0)
        self.assertEqual(result['type'], 'ok')
        self.assertEqual(self.dispatcher.calls[-1][-1], 14)

    async def test_duplicate_never_replays(self):
        first = await self.agent.handle(command())
        second = await self.agent.handle(command())
        self.assertEqual(first, second)
        self.assertEqual(len(self.dispatcher.calls), 1)

    async def test_timeout_duplicate_never_replays(self):
        self.dispatcher.error = laptop.AudioError('FAILED', 'outcome unknown')
        self.assertEqual((await self.agent.handle(command()))['type'], 'err')
        await self.agent.handle(command())
        self.assertEqual(len(self.dispatcher.calls), 1)

    async def test_stale_no_os_call(self):
        await self.agent.handle(command(epoch=4))
        result = await self.agent.handle(command(req='r2', epoch=3))
        self.assertEqual(result['code'], 'STALE')
        self.assertEqual(len(self.dispatcher.calls), 1)

    async def test_malformed_frames_no_os_call(self):
        for updates in ({'req': None}, {'epoch': None}, {'epoch': True},
                        {'deadline_ms': 0}, {'deadline_ms': True},
                        {'deadline_ms': float('nan')}):
            f = command(); f.update(updates)
            self.assertEqual((await self.agent.handle(f))['type'], 'err')
        self.assertEqual(self.dispatcher.calls, [])
        self.assertIsNone(await self.agent.handle([]))

    async def test_busy_heartbeat_and_duplicate_while_running(self):
        self.dispatcher.release = threading.Event()
        task = asyncio.create_task(self.agent.handle(command()))
        while not self.dispatcher.started.is_set():
            await asyncio.sleep(0)
        self.assertEqual(await self.agent.handle({'type': 'ping'}), {'type': 'pong'})
        self.assertIn('unknown', (await self.agent.handle(command()))['message'])
        self.assertEqual((await self.agent.handle(command(req='r2')))['code'], 'BUSY')
        self.dispatcher.release.set()
        await task
        self.assertEqual(len(self.dispatcher.calls), 1)

    async def test_ledger_full_fails_closed(self):
        self.agent.ledger_limit = 1
        await self.agent.handle(command())
        self.assertEqual((await self.agent.handle(command(req='r2')))['code'], 'BUSY')
        self.assertEqual(len(self.dispatcher.calls), 1)

    async def test_session_hello_ping_and_reconnect_duplicate(self):
        ws = FakeSocket([{'type': 'ping'}, command()])
        await self.agent.session(ws)
        self.assertEqual(ws.sent[0], self.agent.hello())
        self.assertIn({'type': 'pong'}, ws.sent)
        ws2 = FakeSocket([command()])
        await self.agent.session(ws2)
        self.assertEqual(ws2.sent[0]['type'], 'hello')
        self.assertEqual(len(self.dispatcher.calls), 1)

    async def test_disconnect_loses_ack_but_not_ledger(self):
        class LostAckSocket(FakeSocket):
            async def send(self, payload):
                if json.loads(payload)['type'] == 'ok':
                    raise ConnectionError('disconnected after physical action')
                await super().send(payload)
        await self.agent.session(LostAckSocket([command()]))
        ws = FakeSocket([command()])
        await self.agent.session(ws)
        self.assertEqual(len(self.dispatcher.calls), 1)
        self.assertEqual(ws.sent[-1]['req'], 'r1')


class URLTests(unittest.TestCase):
    def test_token_encoded_replaced_and_never_path_injected(self):
        self.assertEqual(laptop.device_url('wss://example/ws/device?t=old&x=1', 'a&b'),
                         'wss://example/ws/device?x=1&t=a%26b')
    def test_invalid_urls(self):
        for url in ('https://example', 'ws://u:p@example', 'ws://example/#frag', 'ws:///x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                laptop.device_url(url, 'x')

class DeadlineRegression(unittest.IsolatedAsyncioTestCase):
    async def test_expired_in_executor_queue_never_dispatches(self):
        from concurrent.futures import ThreadPoolExecutor
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        occupied = threading.Event()
        def blocker():
            occupied.set()
            time.sleep(.06)
        first = loop.run_in_executor(None, blocker)
        while not occupied.is_set():
            await asyncio.sleep(0)
        dispatcher = FakeDispatcher()
        agent = laptop.DeviceAgent(dispatcher, '7F3A')
        result = await agent.handle(command(deadline_ms=5))
        await first
        self.assertEqual(result['type'], 'err')
        self.assertEqual(dispatcher.calls, [])


class RealWebSocketTransport(unittest.IsolatedAsyncioTestCase):
    async def test_actual_local_socket_reconnect_and_no_replay(self):
        from websockets.asyncio.server import serve
        dispatcher = FakeDispatcher()
        agent = laptop.DeviceAgent(dispatcher, '7F3A')
        hellos = []
        completed = asyncio.Event()
        failures = []
        async def server(ws):
            try:
                hellos.append(json.loads(await ws.recv()))
                await ws.send(json.dumps({'type': 'ping'}))
                self.assertEqual(json.loads(await ws.recv()), {'type': 'pong'})
                await ws.send(json.dumps(command()))
                reply = json.loads(await ws.recv())
                self.assertEqual((reply['type'], reply['req']), ('ok', 'r1'))
                if len(hellos) >= 2:
                    completed.set()
                    await ws.wait_closed()
            except BaseException as exc:
                failures.append(exc)
                completed.set()
        async with serve(server, '127.0.0.1', 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            task = asyncio.create_task(agent.run(f'ws://127.0.0.1:{port}/ws/device?t=test'))
            try:
                await asyncio.wait_for(completed.wait(), timeout=3)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(failures, [])
        self.assertGreaterEqual(len(hellos), 2)
        self.assertTrue(all(h['room'] == '7F3A' for h in hellos))
        self.assertEqual(len(dispatcher.calls), 1)


if __name__ == '__main__':
    unittest.main()
