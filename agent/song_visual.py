"""Recording-derived energy and a private, bounded native-orb subprocess.

Importing this module never starts a process or opens media. The caller owns
song identity, playback observations, authorization, and visual lifecycle.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time
import wave


ROOT = Path(__file__).resolve().parents[1]
HOST_BINARY = ROOT / '.venv' / 'orb' / 'TenantOrb'
ASSET_ROOT = ROOT / 'agent' / 'orb' / 'dist'
ASSETS = ('index.html', 'orb.js', 'style.css', 'perlin.png')


class VisualError(Exception):
    """A sanitized error; never contains paths, renderer output or credentials."""

    def __init__(self, message, *, owned_host=None):
        super().__init__(message)
        # Private cleanup authority must survive a failed constructor. Keep it
        # out of Exception.args, str() and repr(), which can reach public logs.
        self.owned_host = owned_host


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class EnergyEnvelope:
    levels: tuple[float, ...]
    window_seconds: float
    duration_seconds: float

    @classmethod
    def from_recording(cls, recording):
        """Verify the canonical bytes before reusing a small checksum-keyed cache."""
        try:
            expected = recording['sha256']
            if (not isinstance(expected, str) or len(expected) != 64
                    or any(c not in '0123456789abcdef' for c in expected)):
                raise ValueError
            data = Path(recording['audio_path']).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError
            with _ENERGY_LOCK:
                cached = _ENERGY_CACHE.get(expected)
                if cached is not None:
                    return cached
            with wave.open(io.BytesIO(data), 'rb') as source:
                channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
                count = source.getnframes()
                if channels not in (1, 2) or width != 2 or rate <= 0 or count <= 0 or source.getcomptype() != 'NONE':
                    raise ValueError
                samples = array('h', source.readframes(count))
                if len(samples) != count * channels:
                    raise ValueError
            if sys.byteorder != 'little':
                samples.byteswap()
            window_frames = max(1, round(rate * .025))
            window_samples = window_frames * channels
            levels = []
            for offset in range(0, len(samples), window_samples):
                chunk = samples[offset:offset + window_samples]
                # Average channel powers, not channel values: opposite-phase
                # stereo must not disappear through cancellation.
                level = math.sqrt(sum(value * value for value in chunk) / len(chunk)) / 32768
                levels.append(min(1., max(0., level)))
            result = cls(tuple(levels), window_frames / rate, count / rate)
            with _ENERGY_LOCK:
                if len(_ENERGY_CACHE) >= 4:
                    _ENERGY_CACHE.pop(next(iter(_ENERGY_CACHE)))
                _ENERGY_CACHE[expected] = result
            return result
        except (KeyError, TypeError, ValueError, OSError, EOFError, wave.Error):
            raise VisualError('The selected recording energy could not be verified.') from None

    def level_at(self, playhead_seconds):
        if not _finite(playhead_seconds):
            raise VisualError('The recording playhead is invalid.')
        if playhead_seconds < 0 or playhead_seconds >= self.duration_seconds:
            return 0.
        return self.levels[min(int(playhead_seconds / self.window_seconds), len(self.levels) - 1)]


_ENERGY_CACHE = {}
_ENERGY_LOCK = threading.Lock()


class OrbHost:
    """One owned native host, connected only through inherited standard pipes."""

    @staticmethod
    def available():
        return (HOST_BINARY.is_file() and os.access(HOST_BINARY, os.X_OK)
                and all((ASSET_ROOT / name).is_file() for name in ASSETS))

    def __init__(self, *, deadline, clock=time.monotonic, popen=subprocess.Popen):
        self.deadline, self.clock = deadline, clock
        self.process = None
        self._closed = False
        self._lock = threading.RLock()
        try:
            if not _finite(deadline) or deadline <= clock() or not self.available():
                raise ValueError
            self.process = popen([str(HOST_BINARY), '--assets', str(ASSET_ROOT)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=0, close_fds=True)
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            self._ready()
        except Exception:
            try:
                confirmed = self.close()
            except Exception:
                confirmed = False
            raise VisualError('The native visual host did not confirm readiness.',
                              owned_host=None if confirmed else self) from None

    def _ready(self):
        pending = b''
        while self.clock() < self.deadline and self.process.poll() is None:
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                break
            readable, _, _ = select.select([self.process.stdout.fileno()], [], [], min(.05, remaining))
            if not readable:
                continue
            try:
                chunk = os.read(self.process.stdout.fileno(), 4096)
            except BlockingIOError:
                continue
            if not chunk:
                break
            pending += chunk
            if len(pending) > 16384:
                break
            if b'\n' in pending:
                line, _ = pending.split(b'\n', 1)
                ready = json.loads(line)
                if (isinstance(ready, dict) and {'type', 'webgl', 'transparent'} <= set(ready)
                        and ready['type'] == 'ready' and ready['webgl'] is True
                        and ready['transparent'] is True and self.clock() < self.deadline
                        and self.process.poll() is None):
                    return
                break
        raise VisualError('The native visual host did not confirm readiness.')

    def alive(self):
        return not self._closed and self.process is not None and self.process.poll() is None

    def send(self, frame):
        with self._lock:
            try:
                if (not isinstance(frame, dict) or set(frame) != {'playhead_seconds', 'level', 'playing'}
                        or not _finite(frame['playhead_seconds']) or frame['playhead_seconds'] < 0
                        or not _finite(frame['level']) or not 0 <= frame['level'] <= 1
                        or type(frame['playing']) is not bool or not self.alive()):
                    raise ValueError
                payload = (json.dumps(frame, allow_nan=False, separators=(',', ':')) + '\n').encode()
                # The constructor deadline bounds readiness only. The caller
                # independently fences every frame by the song's original lease.
                deadline = self.clock() + .05
                while self.clock() < deadline:
                    remaining = deadline - self.clock()
                    if remaining <= 0:
                        break
                    _, writable, _ = select.select([], [self.process.stdin.fileno()], [], remaining)
                    if not writable:
                        break
                    try:
                        written = os.write(self.process.stdin.fileno(), payload)
                    except BlockingIOError:
                        continue
                    if written == len(payload):
                        return
                    # A partial frame is uncertain. Close this host, never append
                    # or replay the message into a different host.
                    break
                raise ValueError
            except Exception:
                self.close()
                raise VisualError('The native visual host update was not confirmed.') from None

    def close(self):
        with self._lock:
            self._closed = True
            if self.process is None:
                return True
            try:
                if self.process.stdin is not None:
                    self.process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                for action in (None, 'terminate', 'kill'):
                    if self.process.poll() is not None:
                        break
                    if action is not None:
                        getattr(self.process, action)()
                    try:
                        self.process.wait(timeout=.3)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except (OSError, ValueError):
                return False
            finally:
                try:
                    if self.process.stdout is not None:
                        self.process.stdout.close()
                except (OSError, ValueError):
                    pass
            return self.process.poll() is not None
