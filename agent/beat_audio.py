"""Generated local drum loop through afplay's existing default audio output.

Only launches explicitly requested, expiry-bounded program IDs. No Music library,
system volume, output-device changes, model API or third-party packages.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import wave


class BeatError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def render_beat(path, bpm, duration, *, sample_rate=22050, permitted=lambda: True):
    """Stream a deterministic kick/hat pattern; duration follows the real grant."""
    total = max(1, math.ceil(duration * sample_rate))
    period_seconds = 60 / bpm
    exact_period = min(total, sample_rate * period_seconds)
    if exact_period < 1:
        raise BeatError('INVALID', 'Tempo exceeds the rendered audio sample clock.')
    period = max(1, min(total, math.ceil(exact_period)))
    samples = array('h')
    for index in range(period):
        if index % 1024 == 0 and not permitted():
            raise BeatError('FAILED', 'Beat preparation ended before playback.')
        t = index / sample_rate
        kick = .32 * math.exp(-35 * t) * math.sin(2 * math.pi * (55 * t + 35 * (1 - math.exp(-25 * t)) / 25))
        hat_t = t - period_seconds / 2
        hat = (.07 * math.exp(-150 * hat_t) * (1 if (index * 7919) % 17 < 8 else -1)) if 0 <= hat_t < .04 else 0
        samples.append(round(max(-1, min(1, kick + hat)) * 32767))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        written, beat = 0, 0
        while written < total:
            if not permitted():
                raise BeatError('FAILED', 'Beat preparation ended before playback.')
            # Round each absolute beat boundary, not one repeated rounded period:
            # this keeps backend BPM and audio phase within one sample over time.
            boundary = min(total, round((beat + 1) * exact_period))
            chunk = samples[:boundary - written]
            output.writeframesraw(chunk.tobytes())
            written += len(chunk)
            beat += 1


def capabilities():
    identifier = {'type': 'string', 'maxLength': 80}
    return {
        'beat.prepare': {'description': 'Render an expiry-bounded generated loop without any playback.',
                         'args': {'program_id': identifier, 'bpm': {'type': 'number', 'minimum': 0},
                                  'expires_at_ms': {'type': 'number', 'minimum': 0}}},
        'beat.start': {'description': 'Launch only an already prepared loop; process timing is not acoustic verification.',
                       'args': {'program_id': identifier}},
        'beat.stop': {'description': 'Stop only this generated program ID.', 'args': {'program_id': identifier}},
        'beat.status': {'description': 'Observe this generated program process; never claims audibility.', 'args': {'program_id': identifier}},
    }


@dataclass
class BeatJob:
    program_id: str
    bpm: float
    expires_at_ms: float
    directory: object
    state: str = 'preparing'
    launched_at_ms: float | None = None
    process: object = None
    cancelled: object = None
    lock: object = None


class BeatAudio:
    def __init__(self, *, popen=subprocess.Popen, wall_clock=time.time, sleep=time.sleep, watch=True, render=render_beat):
        self.popen, self.wall_clock, self.sleep, self.watch = popen, wall_clock, sleep, watch
        self.jobs = {}
        self._lock = threading.RLock()
        self.render = render

    def dispatch(self, cap, args, timeout=4):
        if not isinstance(args, dict) or cap not in capabilities() or set(args) != set(capabilities()[cap]['args']):
            raise BeatError('INVALID', 'Invalid generated beat command.')
        program_id = args.get('program_id')
        if (not isinstance(program_id, str) or not 1 <= len(program_id) <= 80
                or any(not (c.isascii() and (c.isalnum() or c in '_-')) for c in program_id)):
            raise BeatError('INVALID', 'Invalid generated program ID.')
        if cap == 'beat.prepare':
            return self._prepare(program_id, args, timeout)
        if cap == 'beat.start':
            return self._start(program_id)
        if cap == 'beat.stop':
            return self.stop(program_id)
        return self.status(program_id)

    def _prepare(self, program_id, args, timeout):
        for key in ('bpm', 'expires_at_ms'):
            if type(args[key]) not in (int, float) or not math.isfinite(args[key]):
                raise BeatError('INVALID', 'Generated beat timing must be finite.')
        bpm, expiry = args['bpm'], args['expires_at_ms']
        if bpm <= 0 or expiry <= self.wall_clock() * 1000:
            raise BeatError('INVALID', 'Generated beat requires positive tempo and unexpired access.')
        started = time.monotonic()
        with self._lock:
            if program_id in self.jobs:
                raise BeatError('CONFLICT', 'This program ID was already used; it is never replayed.')
            directory = tempfile.TemporaryDirectory(prefix='tenant-beat-')
            job = BeatJob(program_id, bpm, expiry, directory, cancelled=threading.Event(), lock=threading.RLock())
            self.jobs[program_id] = job
        if self.watch:
            threading.Thread(target=self._watch, args=(job,), daemon=True).start()
        def permitted():
            return (not job.cancelled.is_set() and self.wall_clock() * 1000 < expiry
                    and time.monotonic() - started < timeout)
        try:
            self.render(Path(directory.name) / 'beat.wav', bpm, (expiry - self.wall_clock() * 1000) / 1000,
                        permitted=permitted)
            with job.lock:
                if not permitted():
                    raise BeatError('FAILED', 'Preparation expired or stopped; no playback started.')
                job.state = 'prepared'
            return self.status(program_id)
        except BaseException:
            job.cancelled.set()
            with job.lock:
                job.state = 'failed'
            directory.cleanup()
            raise

    def _start(self, program_id):
        with self._lock:
            job = self.jobs.get(program_id)
        if job is None:
            raise BeatError('INVALID', 'This generated program was not prepared.')
        with job.lock:
            if job.state != 'prepared' or job.cancelled.is_set() or self.wall_clock() * 1000 >= job.expires_at_ms:
                raise BeatError('PERMISSION', 'This prepared program cannot start; it was not replayed.')
            job.state = 'starting'  # Consume before the OS call; even a failed spawn is not replayed.
            try:
                job.process = self.popen(['/usr/bin/afplay', str(Path(job.directory.name) / 'beat.wav')],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                job.state = 'failed'
                job.cancelled.set()
                job.directory.cleanup()
                raise BeatError('UNKNOWN', 'Generated audio launch failed; it was not retried.') from None
            job.launched_at_ms, job.state = self.wall_clock() * 1000, 'launched'
        return self.status(program_id)

    def _watch(self, job):
        while (not job.cancelled.is_set() and (job.process is None or job.process.poll() is None)
               and self.wall_clock() * 1000 < job.expires_at_ms):
            self.sleep(min(.05, max(0, job.expires_at_ms / 1000 - self.wall_clock())))
        if not job.cancelled.is_set() and (job.process is None or job.process.poll() is None):
            self.stop(job.program_id, reason='expired')
        elif job.process is not None:
            with job.lock:
                if job.state == 'launched':
                    job.state = 'completed' if job.process.poll() == 0 else 'failed'
                job.directory.cleanup()

    def status(self, program_id):
        with self._lock:
            job = self.jobs.get(program_id)
            if job is None:
                return {'program_id': program_id, 'state': 'absent', 'stopped': True, 'audible_verified': False}
        with job.lock:
            if job.state == 'launched' and job.process is not None and job.process.poll() is not None:
                job.state = 'completed' if job.process.poll() == 0 else 'failed'
            return {'program_id': program_id, 'state': job.state, 'bpm': job.bpm,
                    'launched_at_ms': job.launched_at_ms, 'expires_at_ms': job.expires_at_ms,
                    'stopped': job.cancelled.is_set() or (job.process is not None and job.process.poll() is not None),
                    'audible_verified': False}

    def stop(self, program_id, *, reason='stopped'):
        with self._lock:
            job = self.jobs.get(program_id)
            if job is None:
                return self.status(program_id)
        job.cancelled.set()  # Preparation observes this without waiting for a global render lock.
        with job.lock:
            try:
                if job.process is not None and job.process.poll() is None:
                    job.process.terminate()
                    try:
                        job.process.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        job.process.kill()
                        job.process.wait(timeout=.5)
                job.state = reason
                job.directory.cleanup()
                return self.status(program_id)
            except (OSError, subprocess.TimeoutExpired):
                raise BeatError('UNKNOWN', 'Generated audio stop was not confirmed; do not retry automatically.') from None

    def close(self):
        confirmed = True
        for program_id in tuple(self.jobs):
            try:
                self.stop(program_id, reason='disconnected')
            except BeatError:
                confirmed = False
        return confirmed
