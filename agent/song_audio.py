"""One selected real recording, through mpv's normal default output and JSON IPC.

Optional: importing this module neither opens a player nor resolves any media.
The host-prepared canonical recording and its analysis are checksum-bound.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time


class SongError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_map(data):
    """Validate public timing data independently of a host-private audio path."""
    if (not isinstance(data, dict) or not isinstance(data.get('song_id'), str)
            or not 1 <= len(data['song_id']) <= 80
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in data['song_id'])
            or not isinstance(data.get('sha256'), str) or len(data['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in data['sha256'])
            or data.get('artist') != 'Daniel Caesar' or not isinstance(data.get('title'), str)
            or not data['title'].strip() or len(data['title']) > 160
            or not finite(data.get('duration_seconds')) or data['duration_seconds'] <= 0):
        raise SongError('INVALID', 'The selected recording identity is invalid.')
    beats = data.get('beat_seconds')
    if (not isinstance(beats, list) or len(beats) < 3
            or any(not finite(value) or not 0 <= value < data['duration_seconds'] for value in beats)
            or any(left >= right for left, right in zip(beats, beats[1:]))):
        raise SongError('INVALID', 'The recording has no valid ordered beat timeline.')
    return data


def validate_visual(recording):
    """Validate optional host-prepared video metadata; never open a player.

    Container silence/PTS and visible TV placement are verified by the host's
    preparation check. Checksums bind those reviewed bytes to this recording.
    Public timing validation deliberately remains independent of private paths.
    """
    if 'visual' not in recording:
        return None
    visual = recording['visual']
    fields = {'path', 'sha256', 'source_sha256', 'width', 'height', 'fps',
              'duration_seconds', 'description'}
    valid_hash = lambda value: (isinstance(value, str) and len(value) == 64
                                and all(c in '0123456789abcdef' for c in value))
    if (not isinstance(visual, dict) or set(visual) != fields
            or not isinstance(visual['path'], str) or not visual['path']
            or not Path(visual['path']).is_absolute() or Path(visual['path']).suffix.lower() != '.mp4'
            or not valid_hash(visual['sha256']) or not valid_hash(visual['source_sha256'])
            or visual['source_sha256'] != recording['sha256']
            or any(type(visual[key]) is not int or not 64 <= visual[key] <= 4096
                   or visual[key] % 2 for key in ('width', 'height'))
            or not finite(visual['fps']) or not 1 <= visual['fps'] <= 60
            or not finite(visual['duration_seconds']) or visual['duration_seconds'] <= 0
            or abs(visual['duration_seconds'] - recording['duration_seconds']) > 1 / visual['fps'] + 1e-6
            or not isinstance(visual['description'], str) or not visual['description'].strip()
            or not 1 <= len(visual['description']) <= 160
            or not visual['description'].isprintable()
            or any(c in visual['description'] for c in ('/', '\\'))
            or 'file:' in visual['description'].lower()):
        raise SongError('INVALID', 'The prepared visual metadata does not match the selected recording.')
    return visual


def _verify_visual_file(recording):
    visual = validate_visual(recording)
    if visual is None:
        return None
    try:
        path = Path(visual['path']).resolve(strict=True)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != visual['sha256']:
            raise ValueError
    except (OSError, ValueError):
        raise SongError('INVALID', 'The prepared visual file is missing or changed; no player was opened.') from None
    return dict(visual, path=str(path))


def load_recording(manifest):
    data = validate_map(json.loads(Path(manifest).read_text()))
    path = Path(data['audio_path']).resolve(strict=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != data['sha256']:
        raise SongError('INVALID', 'The analyzed recording changed; no playback was started.')
    result = dict(data, audio_path=str(path))
    visual = _verify_visual_file(result)
    if visual is not None:
        result['visual'] = visual
    return result


def capabilities(recording, *, live_visual=False):
    identifier = {'type': 'string', 'maxLength': 80}
    label = recording['artist'] + ' — ' + recording['title']
    visual = recording.get('visual')
    if visual:
        label += '; prepared ambient beat-ring video: ' + visual['description']
    result = {
        'song.prepare': {'description': 'Prepare selected real recording: ' + label + '; never plays.',
            'args': {'program_id': identifier, 'song_id': {**identifier, 'enum': [recording['song_id']]},
                     'expires_at_ms': {'type': 'number', 'minimum': 0}}},
        **{'song.' + name: {'description': description, 'args': {'program_id': identifier}}
           for name, description in (
               ('start', 'Play only the prepared real recording, once, through the current default output.'),
               ('status', 'Read selected-source identity, buffering/pause and actual audio playhead; no audibility claim.'),
               ('stop', 'Stop only this owned selected recording and close its player.'))}}
    if live_visual:
        result['song.visual'] = {'description': 'Show or hide the live transparent orb on this already-playing owned song; canonical audio energy follows its verified playhead. Music and phone lights continue.',
            'args': {'program_id': identifier, 'visible': {'type': 'boolean'}}}
    return result


class MpvPlayer:
    """Private inherited IPC FD: closing the owner also terminates this player."""
    def __init__(self, recording, *, binary='mpv', popen=subprocess.Popen):
        self.connection, child = socket.socketpair()
        self.buffer, self.counter = b'', 0
        self.lock = threading.RLock()
        self.path = recording['audio_path']
        self.visual_path = recording.get('visual', {}).get('path')
        try:
            # No mixer, device, output-volume, normalization or user config edits.
            visual_args = (['--force-window=yes', '--audio-display=embedded-first', '--external-file=' + self.visual_path,
                '--aid=1', '--vid=1', '--video-sync=audio', '--fullscreen=no',
                '--screen=1', '--geometry=1600x900+160+70'] if self.visual_path else [
                '--force-window=no', '--audio-display=no', '--input-default-bindings=no',
                '--input-media-keys=no', '--input-terminal=no', '--media-controls=no'])
            self.process = popen([binary, '--no-config', '--pause=yes', '--idle=no',
                '--terminal=no', *visual_args,
                '--keep-open=yes', '--loop-file=no', '--input-ipc-client=fd://' + str(child.fileno()),
                '--title=' + recording['artist'] + ' — ' + recording['title'],
                '--osd-level=3', '--osd-msg1=' + recording['artist'] + ' — ' + recording['title'],
                '--', self.path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, pass_fds=(child.fileno(),))
        except BaseException:
            self.connection.close()
            raise
        finally:
            child.close()

    def command(self, command, deadline):
        with self.lock:
            self.counter += 1
            request = self.counter
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SongError('UNKNOWN', 'The player deadline elapsed; nothing was repeated.')
            self.connection.settimeout(remaining)
            self.connection.sendall(json.dumps({'command': command, 'request_id': request}).encode() + b'\n')
            while True:
                while b'\n' not in self.buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    self.connection.settimeout(remaining)
                    chunk = self.connection.recv(65536)
                    if not chunk:
                        raise SongError('UNKNOWN', 'The owned player connection ended.')
                    self.buffer += chunk
                    if len(self.buffer) > 1_048_576:
                        raise SongError('UNKNOWN', 'The player response was invalid.')
                line, self.buffer = self.buffer.split(b'\n', 1)
                response = json.loads(line)
                if response.get('request_id') != request:
                    continue  # player events are not command receipts
                if response.get('error') == 'property unavailable' and command[0] == 'get_property':
                    return None  # normal decoder startup; read-only polling is safe
                if response.get('error') != 'success':
                    raise SongError('UNKNOWN', 'The player did not confirm its command.')
                return response.get('data')

    def snapshot(self, deadline):
        values = {name: self.command(['get_property', name], deadline)
                  for name in ('pause', 'paused-for-cache', 'eof-reached', 'speed', 'path', 'time-pos')}
        if ((values['path'] is not None and values['path'] != self.path)
                or (values['speed'] is not None and (not finite(values['speed']) or values['speed'] != 1))):
            raise SongError('FAILED', 'The selected recording or playback speed changed.')
        if any(values[name] is None for name in values):
            return {'state': 'loading', 'position_seconds': 0, 'rate': 1}
        if getattr(self, 'visual_path', None):
            tracks = self.command(['get_property', 'track-list'], deadline)
            if tracks is None or tracks == []:
                return {'state': 'loading', 'position_seconds': 0, 'rate': 1}
            if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
                raise SongError('FAILED', 'The owned visual track selection could not be verified.')
            audio = [track for track in tracks if track.get('type') == 'audio']
            video = [track for track in tracks if track.get('type') == 'video']
            if (len(audio) != 1 or audio[0].get('external') is True
                    or audio[0].get('id') != 1 or audio[0].get('selected') is not True
                    or len(video) != 1 or video[0].get('id') != 1
                    or video[0].get('external') is not True
                    or video[0].get('external-filename') != self.visual_path
                    or video[0].get('image') is True):
                raise SongError('FAILED', 'The canonical audio or prepared silent visual track changed.')
            if video[0].get('selected') is not True:
                return {'state': 'loading', 'position_seconds': 0, 'rate': 1}
        # audio-pts updates at audio cadence and includes mpv's audio-driver delay.
        # Before playback it may be unavailable, so prepared-state time-pos is enough.
        if not values['pause'] and not values['eof-reached']:
            values['time-pos'] = self.command(['get_property', 'audio-pts'], deadline)
            if not finite(values['time-pos']) or values['time-pos'] < 0:
                return {'state': 'buffering', 'position_seconds': 0, 'rate': 1}
        state = ('ended' if values['eof-reached'] else 'paused' if values['pause'] else
                 'buffering' if values['paused-for-cache'] else 'playing')
        return {'state': state, 'position_seconds': values['time-pos'], 'rate': values['speed']}

    def start(self, deadline):
        self.command(['set_property', 'pause', False], deadline)

    def close(self):
        # IPC EOF is mpv's documented owner-disconnect shutdown mechanism.
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        return self.process.poll() is not None


@dataclass
class SongJob:
    recording: dict
    expires: float
    player: object = None
    attempted: bool = False
    state: str = 'preparing'
    stopped: bool = False
    lock: object = field(default_factory=threading.RLock)
    cancelled: object = field(default_factory=threading.Event)
    close_lock: object = field(default_factory=threading.Lock)
    visual: object = None
    visual_pending: bool = False
    visual_lock: object = field(default_factory=threading.RLock)
    visual_stop: object = field(default_factory=threading.Event)
    visual_position: float | None = None
    visual_progress: float = 0
    audio_closed: bool = False


class SongAudio:
    def __init__(self, manifest=None, *, factory=MpvPlayer, clock=time.monotonic,
                 wall_clock=time.time, watch=True, binary=None, visual_factory=None,
                 energy_factory=None, visual_available=None):
        self.factory, self.clock, self.wall_clock, self.watch = factory, clock, wall_clock, watch
        self.binary = binary or shutil.which('mpv')
        self.recording, self.note = None, 'No selected recording is prepared.'
        self.jobs, self.lock = {}, threading.RLock()
        self.visual_factory, self.visual_energy = visual_factory, None
        self.visual_available = visual_available or (lambda: visual_factory is not None)
        if manifest and self.binary:
            try:
                self.recording = load_recording(manifest)
                self.manifest = manifest
            except Exception:
                self.note = 'Selected recording validation failed; no song capability advertised.'
        if self.recording and 'visual' not in self.recording:
            try:
                if __package__:
                    from .song_visual import EnergyEnvelope, OrbHost
                else:
                    from song_visual import EnergyEnvelope, OrbHost
                if visual_factory is None:
                    self.visual_factory = OrbHost
                    self.visual_available = visual_available or OrbHost.available
                if self.visual_available():
                    self.visual_energy = (energy_factory or EnergyEnvelope.from_recording)(self.recording)
            except Exception:
                # Missing optional renderer/analysis must not disable music.
                self.visual_energy = None

    def capabilities(self):
        if not self.recording:
            return {}
        try:
            ready = self.visual_energy is not None and self.visual_available() is True
        except Exception:
            ready = False
        return capabilities(self.recording, live_visual=ready)

    def _public(self, recording):
        result = {key: recording[key] for key in ('song_id', 'artist', 'title', 'sha256',
                                                'duration_seconds', 'beat_seconds', 'analysis')}
        if 'visual' in recording:
            result['visual'] = {key: value for key, value in recording['visual'].items() if key != 'path'}
        return result

    def dispatch(self, cap, args, timeout=4):
        spec = self.capabilities().get(cap)
        if spec is None or not isinstance(args, dict) or set(args) != set(spec['args']):
            raise SongError('INVALID', 'Invalid selected-recording command.')
        identifier = args['program_id']
        if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 80
                or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identifier)):
            raise SongError('INVALID', 'Invalid selected-recording program ID.')
        deadline = self.clock() + timeout
        if cap == 'song.prepare':
            if args['song_id'] != self.recording['song_id'] or not finite(args['expires_at_ms']):
                raise SongError('INVALID', 'Select the exact available recording.')
            remaining = args['expires_at_ms'] / 1000 - self.wall_clock()
            if remaining <= 0:
                raise SongError('PERMISSION', 'Song access expired before preparation.')
            with self.lock:
                if identifier in self.jobs:
                    raise SongError('CONFLICT', 'This song program ID was already used; no replay.')
                if any(not job.stopped for job in self.jobs.values()):
                    raise SongError('BUSY', 'The selected-song player is already owned; stop it first.')
                job = self.jobs[identifier] = SongJob(self.recording, self.clock() + remaining)
            try:
                # Recheck the exact bytes immediately before opening the player.
                if hashlib.sha256(Path(job.recording['audio_path']).read_bytes()).hexdigest() != job.recording['sha256']:
                    raise SongError('INVALID', 'The selected recording changed.')
                _verify_visual_file(job.recording)
                with job.lock:
                    if job.cancelled.is_set() or job.stopped or self.clock() >= min(deadline, job.expires):
                        raise SongError('PERMISSION', 'Preparation was cancelled before the player opened.')
                    job.player = self.factory(job.recording, binary=self.binary)
                    if job.cancelled.is_set() or self.clock() >= min(deadline, job.expires):
                        raise SongError('PERMISSION', 'Access ended during song preparation.')
                    deadline = min(deadline, job.expires)
                    sample = job.player.snapshot(deadline)
                    while sample['state'] == 'loading' and self.clock() < deadline and not job.cancelled.is_set():
                        time.sleep(.02)
                        sample = job.player.snapshot(deadline)
                    if sample['state'] != 'paused':
                        raise SongError('UNKNOWN', 'Preparation did not confirm paused playback.')
                    if job.cancelled.is_set() or self.clock() >= deadline:
                        raise SongError('PERMISSION', 'Access ended during song preparation.')
                    job.state = 'prepared'
                if self.watch:
                    threading.Thread(target=self._watch, args=(identifier,), daemon=True).start()
                return {'program_id': identifier, 'state': 'prepared', 'recording': self._public(job.recording),
                        'audible_verified': False}
            except BaseException:
                self.stop(identifier)
                raise
        job = self.jobs.get(identifier)
        if job is None:
            raise SongError('INVALID', 'That selected-song program does not exist.')
        if cap == 'song.stop':
            return self.stop(identifier)
        if cap == 'song.visual':
            if type(args['visible']) is not bool:
                raise SongError('INVALID', 'Visual visibility must be a boolean.')
            return self._visual(identifier, job, args['visible'], deadline)
        with job.lock:
            if self.clock() >= job.expires:
                self.stop(identifier)
            if job.stopped:
                return {'program_id': identifier, 'state': 'stopped', 'stopped': True}
            if job.cancelled.is_set():
                raise SongError('PERMISSION', 'This selected-song program is stopping.')
            deadline = min(deadline, job.expires)
            if cap == 'song.start':
                if job.attempted or job.state != 'prepared':
                    raise SongError('CONFLICT', 'Song start was already attempted; it was not repeated.')
                job.attempted = True  # consume before IPC, including uncertainty
                if self.clock() >= job.expires or job.cancelled.is_set():
                    raise SongError('PERMISSION', 'Access ended before song playback.')
                job.player.start(deadline)
            sample = job.player.snapshot(deadline)
            if sample['state'] == 'loading':
                sample = {'state': 'buffering', 'position_seconds': 0, 'rate': 1}
            # A harmless pre-start status read must preserve the prepared
            # lifecycle state; observed paused playback is not a start attempt.
            job.state = 'prepared' if not job.attempted and sample['state'] == 'paused' else sample['state']
            return {'program_id': identifier, 'song_id': job.recording['song_id'],
                    'sha256': job.recording['sha256'], **sample, 'audible_verified': False}

    @staticmethod
    def _visual_result(identifier, attached):
        return {'program_id': identifier, 'visible': attached, 'visual_state': 'attached' if attached else 'hidden',
                'visual_ready': attached, 'physical_visibility_verified': False}

    def _hide_visual(self, job, token=None):
        with job.visual_lock:
            if token is not None and token is not job.visual_stop:
                return True
            job.visual_stop.set()
            host = job.visual
            try:
                confirmed = host is None or host.close() is True
            except Exception:
                confirmed = False
            if confirmed and job.visual is host:
                job.visual = None
            return confirmed and not job.visual_pending

    def _playing_sample(self, job, deadline):
        if (job.cancelled.is_set() or job.stopped or self.clock() >= min(deadline, job.expires)
                or not job.attempted or job.player is None):
            raise SongError('PERMISSION', 'A live visual needs the current owned playing song.')
        sample = job.player.snapshot(min(deadline, job.expires))
        position = sample.get('position_seconds')
        if (sample.get('state') != 'playing' or not finite(sample.get('rate')) or sample['rate'] != 1
                or not finite(position) or not 0 <= position < job.recording['duration_seconds']):
            raise SongError('FAILED', 'The owned song has no verified advancing audio playhead.')
        return sample

    def _visual_frame(self, job, sample, now):
        position = sample['position_seconds']
        if job.visual_position is not None:
            if position < job.visual_position - .025:
                raise SongError('FAILED', 'The audio playhead moved backwards; the visual was detached.')
            if position > job.visual_position + .001:
                job.visual_progress = now
            elif now - job.visual_progress >= .75:
                raise SongError('FAILED', 'The audio playhead is stale; the visual was detached.')
        else:
            job.visual_progress = now
        job.visual_position = position
        level = self.visual_energy.level_at(position)
        if not finite(level) or not 0 <= level <= 1:
            raise SongError('FAILED', 'Canonical audio energy is unavailable.')
        return {'playhead_seconds': position, 'level': level, 'playing': True}

    def _visual(self, identifier, job, visible, deadline):
        if not visible:
            if not self._hide_visual(job):
                raise SongError('UNKNOWN', 'Visual cleanup is pending; music was not changed.')
            return self._visual_result(identifier, False)
        with job.lock:
            self._playing_sample(job, deadline)
            with job.visual_lock:
                if job.visual is not None:
                    if not job.visual_stop.is_set() and job.visual.alive():
                        return self._visual_result(identifier, True)
                    raise SongError('BUSY', 'Prior visual cleanup needs confirmation before another overlay.')
                if job.visual_pending:
                    raise SongError('BUSY', 'The owned visual is already being prepared.')
                token = job.visual_stop = threading.Event()
                job.visual_pending = True
        host, published = None, False
        try:
            if (token.is_set() or job.cancelled.is_set() or job.stopped
                    or self.clock() >= min(deadline, job.expires)):
                raise SongError('PERMISSION', 'Visual attachment ended before the host could open.')
            # Native shader startup is outside the song lock: music clock/status
            # and phone timing can continue while this independent window loads.
            host = self.visual_factory(deadline=min(deadline, job.expires))
            with job.lock:
                sample = self._playing_sample(job, deadline)
                job.visual_position = None
                sampled_at = self.clock()
                frame = self._visual_frame(job, sample, sampled_at)
            with job.visual_lock:
                if (token.is_set() or job.cancelled.is_set() or job.stopped
                        or self.clock() >= min(deadline, job.expires)
                        or self.clock() - sampled_at > .25):
                    raise SongError('PERMISSION', 'Visual attachment was cancelled before publication.')
                if not host.alive():
                    raise SongError('FAILED', 'The transparent visual host ended during preparation.')
                host.send(frame)
                job.visual = host
                published = True
            if self.watch:
                threading.Thread(target=self._visual_watch, args=(job, token), daemon=True).start()
            return self._visual_result(identifier, True)
        except SongError:
            raise
        except Exception as error:
            if host is None:
                host = getattr(error, 'owned_host', None)
            raise SongError('UNKNOWN', 'The live visual did not confirm attachment; music was not changed.') from None
        finally:
            if host is not None and not published:
                try:
                    confirmed = host.close() is True
                except Exception:
                    confirmed = False
                if not confirmed:
                    # Keep exact ownership even when cancellation won the race
                    # before publication; later cleanup must not claim absence.
                    with job.visual_lock:
                        job.visual = host
                        token.set()
            with job.visual_lock:
                job.visual_pending = False
            if job.cancelled.is_set():
                self.stop(identifier)

    def _visual_tick(self, job, token=None):
        token = token or job.visual_stop
        try:
            with job.lock:
                if token is not job.visual_stop or token.is_set():
                    return False
                sample = self._playing_sample(job, min(self.clock() + .25, job.expires))
                sampled_at = self.clock()
                frame = self._visual_frame(job, sample, sampled_at)
            with job.visual_lock:
                if token is not job.visual_stop:
                    return False
                if (token.is_set() or job.cancelled.is_set() or job.stopped or self.clock() >= job.expires
                        or self.clock() - sampled_at > .25 or job.visual is None or not job.visual.alive()):
                    raise SongError('FAILED', 'The visual host is unavailable.')
                job.visual.send(frame)
            return True
        except Exception:
            # Visual errors detach only the overlay; never pause/restart audio
            # or send any phone operation. Close outside the song status lock.
            self._hide_visual(job, token)
            return False

    def _visual_watch(self, job, token):
        while not token.wait(.1):
            if not self._visual_tick(job, token):
                return

    def _watch(self, identifier):
        job = self.jobs[identifier]
        while not job.stopped:
            if self.clock() >= job.expires or job.player.process.poll() is not None:
                self.stop(identifier)
                return
            time.sleep(.05)

    def stop(self, identifier):
        job = self.jobs.get(identifier)
        if job is None:
            return {'program_id': identifier, 'state': 'stopped', 'stopped': True}
        job.cancelled.set()  # fence a still-hashing/spawning worker before waiting
        with job.close_lock:
            if not job.stopped:
                if job.player is None:
                    # A factory can be in flight without having published its
                    # child yet. Report pending, never confirmed absent cleanup.
                    acquired = job.lock.acquire(blocking=False)
                    if not acquired:
                        return {'program_id': identifier, 'state': 'stopping', 'stopped': False}
                    job.lock.release()
                if not job.audio_closed:
                    confirmed = job.player is None or job.player.close()
                    if not confirmed:
                        raise SongError('UNKNOWN', 'Owned song shutdown was not confirmed.')
                    job.audio_closed = True
                if not self._hide_visual(job):
                    return {'program_id': identifier, 'state': 'stopping', 'stopped': False}
                job.stopped, job.state = True, 'stopped'
            return {'program_id': identifier, 'state': 'stopped', 'stopped': True}

    def stop_all(self):
        for identifier in tuple(self.jobs):
            self.stop(identifier)
