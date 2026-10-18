"""Lease-owned generated beats with optional phones on one monotonic clock.

Jobs survive a native turn, never their owner. The existing phone boolean bridge
has no device-side scheduling: reported timing measures dispatch/ACK, not physical
audio/light synchronization. Generic native OS tools remain outside this policy.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import uuid
from collections import defaultdict
from brain.core.song_timing import SongTimeline


def failure(code, message):
    return {'ok': False, 'code': code, 'message': message}


def positive_finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def next_beat_index(phase, now, period):
    """Strictly future grid point, including nonbinary-exact BPM boundaries."""
    index = max(0, math.floor((now - phase) / period) + 1)
    if phase + index * period <= now:
        index += 1
    return index


@dataclass(frozen=True)
class ProgramOwner:
    guest_id: str
    generation: int
    lease: object = field(repr=False)
    thread_id: str
    room_id: str
    epoch: int

    @classmethod
    def from_grant(cls, grant):
        return cls(*(getattr(grant, key) for key in ('guest_id', 'generation', 'lease', 'thread_id', 'room_id', 'epoch')))


@dataclass
class Program:
    id: str
    owner: ProgramOwner
    audio: object
    audio_connection: object
    bpm: float
    state: str = 'starting'
    run_id: str = ''
    phase: float = 0
    phase_wall_ms: float = 0
    active: bool = False
    lights: dict = field(default_factory=dict)
    last_on: dict = field(default_factory=dict)
    tasks: set = field(default_factory=set)
    cleanup_task: object = None
    cleanup: dict = field(default_factory=dict)
    reason: str | None = None
    missed_ticks: int = 0
    timings: list = field(default_factory=list)
    light_locks: dict = field(default_factory=dict)
    light_tasks: dict = field(default_factory=dict)
    detached: set = field(default_factory=set)
    output_cleanup: dict = field(default_factory=dict)
    detach_tasks: dict = field(default_factory=dict)
    restart_pending: bool = False
    restart_allowed: object = None
    recovery: dict = field(default_factory=dict)
    participants: dict = field(default_factory=dict)
    first_cycles: dict = field(default_factory=dict)
    failure_devices: set = field(default_factory=set)
    light_cadences: dict = field(default_factory=dict)
    light_dispatches: dict = field(default_factory=dict)
    monitor_task: object = None
    status_dispatch: str | None = None
    cleanup_workers: dict = field(default_factory=dict)
    song_id: str | None = None
    song_timeline: object = None
    audio_metadata_guard: object = None
    light_metadata_guards: dict = field(default_factory=dict)
    visual: dict = field(default_factory=dict)


class RoomPrograms:
    def __init__(self, registry, bus, leases, log, current, *, action_timeout=5,
                 clock=None, wall_clock=None, sleep=asyncio.sleep, device_locks=None,
                 audio_queue_timeout=None):
        import time
        self.registry, self.bus, self.leases, self.log, self.current = registry, bus, leases, log, current
        self.clock, self.wall_clock = clock or time.monotonic, wall_clock or time.time
        self.sleep, self.action_timeout = sleep, action_timeout
        self.audio_queue_timeout = action_timeout if audio_queue_timeout is None else audio_queue_timeout
        self.programs, self._light_owners = {}, {}
        self.device_locks = device_locks if device_locks is not None else defaultdict(asyncio.Lock)
        self._control = asyncio.Lock()
        self._off_locks = defaultdict(asyncio.Lock)
        self._closed = False

    def _allowed(self, owner):
        return (not self._closed and self.registry.room.id == owner.room_id
                and self.registry.room.epoch == owner.epoch
                and self.leases.current(owner.guest_id) is owner.lease
                and self.current(owner))

    def _same_owner(self, left, right):
        return (left.guest_id == right.guest_id and left.generation == right.generation
                and left.lease is right.lease and left.thread_id == right.thread_id
                and left.room_id == right.room_id and left.epoch == right.epoch)

    def _connection(self, device, connection):
        return (self.registry.devices.get(device.id) is device and device.ws is connection
                and device.online and device.room_id == self.registry.room.id)

    def _status(self, program):
        song = program.song_timeline
        return {'program_id': program.id, 'state': program.state, 'bpm': program.bpm,
                'source': 'selected_recording' if program.song_id else 'generated_beat',
                **({'song_id': program.song_id, 'title': song.recording['title'] if song else None,
                    'artist': song.recording['artist'] if song else None,
                    'song_clock': song.status(self.clock()) if song else {'state': 'pending'}} if program.song_id else {}),
                'clock': ('recording-derived beats mapped from bracketed live audio playhead' if program.song_id else
                          'backend monotonic; generated audio process launch is the phase reference'),
                'phase_wall_ms': program.phase_wall_ms, 'audio_device_id': program.audio.id,
                'light_device_ids': sorted(device_id for device_id, participant in program.participants.items()
                                          if program.active and participant['participant_state'] == 'following'
                                          and (not song or song.ready(self.clock()))
                                          and device_id not in program.detached),
                'participants': {device_id: {**participant, 'first_cycle': dict(participant['first_cycle'])}
                                 for device_id, participant in program.participants.items()},
                'reserved_light_ids': sorted(device_id for device_id in program.lights
                                             if self._light_owners.get(device_id) is program
                                             and program.cleanup.get(device_id) == 'unknown'),
                'missed_ticks': program.missed_ticks,
                'reason': program.reason, 'cleanup': dict(program.cleanup), 'recovery': dict(program.recovery),
                'recent_dispatch_timings': list(program.timings[-12:]),
                'visual': {**program.visual, 'update_available': self._visual_available(program),
                           'physical_rendering_verified': False},
                'physical_sync_measured': False, 'audio_light_clock_alignment': (
                    'live playhead bracket uncertainty reported; optical/acoustic offset unmeasured' if program.song_id else
                    'assumed same host clock; optical/acoustic offset unmeasured')}

    def _visual_available(self, program):
        return bool(program.song_id and program.active and program.state == 'running'
                    and program.visual.get('state') != 'unknown'
                    and self.programs.get(program.id) is program
                    and self._allowed(program.owner)
                    and self._connection(program.audio, program.audio_connection)
                    and program.audio_metadata_guard is not None and program.audio_metadata_guard()
                    and self.registry.metadata.available(program.audio, 'song.visual')
                    and self.leases.allows(program.owner.lease, program.audio, 'song.visual'))

    def device_busy(self, device_id):
        program = self._light_owners.get(device_id)
        return program.id if program is not None else None

    def retirement_blocked(self, device_id):
        """A host cannot forget an active or incompletely settled program claim."""
        if self.device_busy(device_id) is not None:
            return True
        for program in self.programs.values():
            if device_id != program.audio.id and device_id not in program.lights:
                continue
            tasks = (*program.tasks, *program.detach_tasks.values(), *program.output_cleanup.values(), *program.cleanup_workers.values())
            if (program.active or program.state != 'stopped' or not program.cleanup
                    or any(value != 'confirmed' for value in program.cleanup.values())
                    or any(not task.done() for task in tasks)
                    or (program.cleanup_task is not None and not program.cleanup_task.done())):
                return True
        return False

    def inventory(self, grant):
        owner = ProgramOwner.from_grant(grant)
        if not self._allowed(owner):
            return {'audio_devices': [], 'programs': []}
        return {'audio_devices': [{'device_id': dev.id, 'label': dev.label, 'online': dev.online,
                                  'generated_beat': all(self.registry.metadata.available(dev, cap) for cap in ('beat.prepare', 'beat.start', 'beat.stop', 'beat.status')),
                                  'song_visual': self.registry.metadata.available(dev, 'song.visual') and self.leases.allows(owner.lease, dev, 'song.visual'),
                                  'songs': ([{'song_id': identifier, 'label': dev.caps['song.prepare'].description} for identifier in
                                             dev.caps['song.prepare'].args.get('song_id', {}).get('enum', [])]
                                            if all(self.registry.metadata.available(dev, 'song.' + name) for name in ('prepare', 'start', 'stop', 'status')) else [])}
                                 for dev in self.registry.devices.values() if dev.room_id == owner.room_id
                                 and (self.registry.metadata.available(dev, 'beat.start') or self.registry.metadata.available(dev, 'song.start'))],
                'programs': [self._status(p) for p in self.programs.values() if self._same_owner(p.owner, owner)]}

    async def dispatch(self, grant, operation, payload, *, authorized=lambda: True):
        response = await self._dispatch(grant, operation, payload, authorized=authorized)
        if response.get('code') == 'UNKNOWN':
            program_id = payload.get('program_id') if isinstance(payload, dict) else None
            program = self.programs.get(program_id) if isinstance(program_id, str) else None
            if program is None and operation == 'program-start' and isinstance(payload, dict):
                candidates = [p for p in self.programs.values() if p.owner.lease is grant.lease
                              and p.audio.id == payload.get('device_id')]
                program = candidates[-1] if candidates else None
            unknown = set(response.get('unknown_device_ids', []))
            if program is not None:
                unknown.update(program.failure_devices)
                unknown.update(program.audio.id if name == 'audio' else name
                               for name, status in program.cleanup.items() if status == 'unknown')
                if not unknown:
                    unknown.add(payload.get('remove_light_device_id') or program.audio.id)
                response['program_id'] = program.id
            response['unknown_device_ids'] = sorted(unknown)
        return response

    async def _dispatch(self, grant, operation, payload, *, authorized=lambda: True):
        owner = ProgramOwner.from_grant(grant)
        if not isinstance(payload, dict) or not self._allowed(owner) or not authorized():
            return failure('PERMISSION', 'This turn cannot change a room program.')
        keys = set(payload)
        song_start = operation == 'program-start' and keys == {'request_id', 'device_id', 'song_id'}
        start = operation == 'program-start' and (keys == {'request_id', 'device_id', 'bpm'} or song_start)
        visual_update = operation == 'program-update' and keys == {'request_id', 'program_id', 'visual'}
        update = visual_update or (operation == 'program-update' and {'request_id', 'program_id'} < keys
                  and keys <= {'request_id', 'program_id', 'bpm', 'light_device_id', 'remove_light_device_id', 'light_beats_per_state'}
                  and ('light_beats_per_state' not in keys or 'light_device_id' in keys))
        simple = operation in ('program-stop', 'program-status') and keys == {'request_id', 'program_id'}
        if not (start or update or simple):
            return failure('INVALID', 'Invalid room program operation.')
        if visual_update and type(payload['visual']) is not bool:
            return failure('INVALID', 'Visual visibility must be a boolean.')
        if 'bpm' in payload and not positive_finite(payload['bpm']):
            return failure('INVALID', 'Tempo must be a positive finite BPM.')
        if 'light_beats_per_state' in payload and not positive_finite(payload['light_beats_per_state']):
            return failure('INVALID', 'Phone cadence must be a positive finite number of beats per state.')
        # A pending first-cycle receipt must remain observable while a mutation
        # waits. This branch reads only and performs the same owner checks.
        if operation == 'program-status':
            program_id = payload.get('program_id')
            if not isinstance(program_id, str):
                return failure('INVALID', 'A program ID is required.')
            program = self.programs.get(program_id)
            if program is None or not self._same_owner(program.owner, owner):
                return failure('PERMISSION', 'This guest does not own that room program.')
            return {'ok': True, 'result': self._status(program)}
        # Preserve request-time targets through the room-program mutation queue.
        # Status/stop/detach own fresh cleanup authority, not the old run's fence.
        targets = set()
        program_guard = lambda: True
        if start and isinstance(payload.get('device_id'), str):
            targets.add(payload['device_id'])
        elif update:
            prior = self.programs.get(payload.get('program_id')) if isinstance(payload.get('program_id'), str) else None
            if visual_update and prior is not None:
                prior_run, prior_song, prior_connection = prior.run_id, prior.song_id, prior.audio_connection
                program_guard = lambda: (self.programs.get(prior.id) is prior
                                         and prior.run_id == prior_run and prior.song_id == prior_song
                                         and prior.audio_connection is prior_connection)
            if ('bpm' in payload or visual_update) and prior is not None:
                targets.add(prior.audio.id)
            if isinstance(payload.get('light_device_id'), str):
                targets.add(payload['light_device_id'])
        metadata_guard = self.registry.metadata.guard(targets)
        caller_authorized = authorized
        authorized = lambda: caller_authorized() and metadata_guard() and program_guard()
        async with self._control:
            if not self._allowed(owner) or not authorized():
                return failure('PERMISSION', 'This turn can no longer change a room program.')
            if start:
                dev = self.registry.devices.get(payload['device_id']) if isinstance(payload['device_id'], str) else None
                prefix = 'song' if song_start else 'beat'
                caps = tuple(prefix + '.' + name for name in ('prepare', 'start', 'stop', 'status'))
                if dev is None or not self._connection(dev, dev.ws) or not all(cap in dev.caps for cap in caps):
                    return failure('OFFLINE', 'That exact audio bridge is unavailable. No alternative was used.')
                if not all(self.leases.allows(owner.lease, dev, cap) for cap in caps):
                    return failure('PERMISSION', 'This guest cannot start and manage that audio source.')
                if song_start and payload['song_id'] not in dev.caps['song.prepare'].args.get('song_id', {}).get('enum', []):
                    return failure('INVALID', 'Select an exact available recording from inventory; no substitution was made.')
                if any(p.audio is dev and (song_start or p.song_id) and
                       (p.state != 'stopped' or any(v != 'confirmed' for v in p.cleanup.values())) for p in self.programs.values()):
                    return failure('CONFLICT', 'Stop the existing owned audio before selecting this recording or mixing another clock.')
                program = Program('p_' + uuid.uuid4().hex, owner, dev, dev.ws, payload.get('bpm', 0),
                                  song_id=payload.get('song_id'))
                self.programs[program.id] = program
                if song_start:
                    return await self._launch_song(program, authorized)
                return await self._launch(program, authorized)
            if not isinstance(payload.get('program_id'), str):
                return failure('INVALID', 'A program ID is required.')
            program = self.programs.get(payload['program_id'])
            if program is None or not self._same_owner(program.owner, owner):
                return failure('PERMISSION', 'This guest does not own that room program.')
            if operation == 'program-stop':
                self._invalidate(program, 'requested_stop')
                await asyncio.shield(program.cleanup_task)
                confirmed = all(value == 'confirmed' for value in program.cleanup.values())
                return {'ok': confirmed, **({} if confirmed else {'code': 'UNKNOWN'}),
                        'result': self._status(program), 'message': 'Future program steps stopped; cleanup status is reported separately.'}
            if program.state != 'running':
                return failure('STOPPED', 'That program is not running. It was not restarted or replayed.')
            if visual_update:
                # Own no cadence, phase, audio preparation or restart on this path.
                return await self._update_visual(program, payload['visual'], authorized)
            if program.song_id and 'bpm' in payload:
                return failure('UNSUPPORTED', 'A recording follows its analyzed beats. Tempo edits require time stretching and are unavailable; no audio changed.')
            cadences = dict(program.light_cadences)
            if isinstance(payload.get('light_device_id'), str):
                device_id = payload['light_device_id']
                cadences[device_id] = payload.get('light_beats_per_state', cadences.get(device_id, 1 if program.song_id else .5))
            for cadence in cadences.values():
                duration = 60 / payload.get('bpm', program.bpm) * cadence
                now = self.clock()
                if (not math.isfinite(2 * duration * 1000) or duration <= 0
                        or now + duration <= now):
                    return failure('INVALID', 'The requested phone cadence cannot be represented by the room clock.')
            wait_ids = set()
            if 'remove_light_device_id' in payload:
                result = await self._detach(program, payload['remove_light_device_id'])
                if not result['ok']:
                    return result
            if 'bpm' in payload:
                program.restart_pending, program.restart_allowed = True, authorized
                try:
                    self._invalidate(program, 'tempo_change')
                    await asyncio.shield(program.cleanup_task)
                    if not all(value == 'confirmed' for value in program.cleanup.values()):
                        return failure('UNKNOWN', 'Previous loop cleanup is unconfirmed. No replacement beat started.')
                    if not self._allowed(owner) or not authorized():
                        return failure('PERMISSION', 'Access ended before the new tempo started.')
                    program.bpm = payload['bpm']
                    result = await self._launch(program, authorized)
                    if not result['ok']:
                        return result
                    wait_ids.update(program.lights)
                finally:
                    program.restart_pending = False
                    if not program.active:
                        self._release_clean_lights(program)
            if 'light_device_id' in payload:
                device_id = payload['light_device_id']
                dev = self.registry.devices.get(device_id) if isinstance(device_id, str) else None
                if dev is None or not self._connection(dev, dev.ws) or 'light' not in dev.caps:
                    return failure('OFFLINE', 'That exact phone light is unavailable. No alternative was used.')
                if not self.leases.allows(owner.lease, dev, 'light'):
                    return failure('PERMISSION', 'This guest cannot control that phone light.')
                claimed = self._light_owners.get(dev.id)
                if claimed is not None and claimed is not program:
                    return dict(failure('CONFLICT', 'Detach that light from its existing program before assigning another clock.'),
                                program_id=claimed.id, detach_operation='program-update', remove_light_device_id=dev.id)
                if dev.id in program.detached:
                    return dict(failure('UNKNOWN', 'Previous phone cleanup is unconfirmed. Keep it reserved; use explicit host reset or reconnect verification.'),
                                program_id=program.id, device_id=dev.id)
                cadence = cadences[dev.id]
                if dev.id in program.lights and cadence != program.light_cadences.get(dev.id, .5):
                    # Changing cadence owns only this phone: confirm OFF before
                    # installing a fresh loop on the original audio phase.
                    result = await self._detach(program, dev.id)
                    if not result['ok']:
                        return result
                    if not self._allowed(owner) or not authorized() or not program.active:
                        return failure('PERMISSION', 'Access ended before the replacement phone cadence started.')
                    claimed = None
                if claimed is None:
                    lock = self.device_locks[dev.id]
                    if lock.locked():
                        return failure('CONFLICT', 'That phone is still carrying out another logical action; no program edge was sent.')
                    await lock.acquire()
                    program.light_locks[dev.id] = lock
                self._light_owners[dev.id] = program
                if dev.id not in program.lights:
                    program.output_cleanup.pop(('light', dev.id, program.run_id), None)
                    program.cleanup.pop(dev.id, None)
                    program.lights[dev.id] = (dev, dev.ws)
                    program.light_metadata_guards[dev.id] = self.registry.metadata.guard((dev.id,))
                    program.light_cadences[dev.id] = cadence
                    self._begin_first_cycle(program, dev.id)
                    program.light_tasks[dev.id] = self._task(program, self._light_loop(program, dev, dev.ws))
                wait_ids.add(dev.id)
        # Waiting is read-only: release mutation serialization so a later stop
        # or detach can settle a pending first cycle immediately.
        return await self._await_first_cycles(program, grant, authorized, wait_ids)

    async def _update_visual(self, program, visible, authorized):
        if not program.song_id:
            return failure('UNSUPPORTED', 'Visual updates require an existing selected-recording program.')
        if 'song.visual' not in program.audio.caps:
            return failure('UNSUPPORTED', 'That audio bridge does not advertise live song visuals.')
        if program.visual.get('state') == 'unknown':
            return failure('UNKNOWN', 'An earlier visual outcome is unknown. Do not retry or restart the song.')
        if not self._connection(program.audio, program.audio_connection):
            return failure('OFFLINE', 'The original selected-song bridge changed; no visual command was sent.')
        if not self._visual_available(program) or not authorized():
            return failure('PERMISSION', 'Current song ownership, visual scope and host allowance are required.')
        run_id, song_id = program.run_id, program.song_id
        metadata_guard = self.registry.metadata.guard((program.audio.id,))
        previous = dict(program.visual)
        def current():
            return (authorized() and metadata_guard() and self._visual_available(program)
                    and program.run_id == run_id and program.song_id == song_id)
        def permitted(dev, cap, args):
            return (current() and dev is program.audio and cap == 'song.visual'
                    and args == {'program_id': run_id, 'visible': visible})
        def dispatched(*_):
            program.visual = {'state': 'pending', 'requested_visible': visible,
                              'acknowledged_visible': None}
        try:
            result = await self.bus.call(program.audio.id, 'song.visual',
                {'program_id': run_id, 'visible': visible}, timeout=self.action_timeout,
                authorize=permitted, on_dispatch=dispatched)
        except BaseException as exc:
            if program.visual.get('state') == 'pending':
                program.visual['state'] = 'unknown'
            if isinstance(exc, asyncio.CancelledError):
                raise
            return failure('UNKNOWN', 'The visual outcome is unknown; no retry or song restart was attempted.')
        data = result.result if isinstance(result.result, dict) else {}
        if not result.ok:
            if result.code == 'UNKNOWN':
                program.visual = {'state': 'unknown', 'requested_visible': visible,
                                  'acknowledged_visible': None}
            else:
                program.visual = previous
            return dict(failure(result.code or 'UNKNOWN',
                        'The visual change was not confirmed; the song was not restarted.'),
                        result=self._status(program), status='unknown' if result.code == 'UNKNOWN' else 'unconfirmed')
        if (data.get('program_id') != run_id or type(data.get('visible')) is not bool
                or data['visible'] is not visible):
            program.visual = {'state': 'unknown', 'requested_visible': visible,
                              'acknowledged_visible': None}
            return dict(failure('UNKNOWN', 'The bridge did not confirm this visual change. Do not retry or restart the song.'),
                        result=self._status(program))
        if not current():
            program.visual = {'state': 'unknown', 'requested_visible': visible,
                              'acknowledged_visible': None}
            return dict(failure('PERMISSION', 'The visual reply arrived after access, connection or the running song changed.'),
                        result=self._status(program))
        program.visual = {'state': 'shown' if visible else 'hidden', 'requested_visible': visible,
                          'acknowledged_visible': visible}
        return {'ok': True, 'result': self._status(program),
                'message': 'Visual visibility acknowledged on the existing song player; physical rendering is unverified.'}

    def _begin_first_cycle(self, program, device_id):
        beats_per_state = program.light_cadences.get(device_id, 1 if program.song_id else .5)
        duration_ms = 60 / program.bpm * beats_per_state * 1000
        program.participants[device_id] = {'participant_state': 'pending',
            'light_beats_per_state': beats_per_state, 'on_duration_ms': duration_ms, 'off_duration_ms': duration_ms,
            'first_cycle': {'on_ack': False, 'off_ack': False, 'physical_verified': False}}
        if program.song_id:
            program.participants[device_id]['durations_are_estimates'] = True
            program.participants[device_id]['timing_source'] = 'actual per-beat timestamps, not median BPM'
        program.first_cycles[device_id] = asyncio.get_running_loop().create_future()

    async def _await_first_cycles(self, program, grant, authorized, device_ids):
        run_id = program.run_id
        cycles = {device_id: future for device_id, future in program.first_cycles.items()
                  if device_id in device_ids and device_id in program.lights and device_id not in program.detached}
        pending = [future for future in cycles.values() if not future.done()]
        try:
            if pending:
                remaining = max(0, program.owner.lease.expires_at - self.leases.clock())
                deadline = getattr(grant, 'deadline', None)
                if deadline is not None:
                    remaining = min(remaining, max(0, deadline - self.clock()))
                wait_until = asyncio.get_running_loop().time() + remaining
                while pending:
                    done, pending = await asyncio.wait(pending,
                        timeout=max(0, wait_until - asyncio.get_running_loop().time()),
                        return_when=asyncio.FIRST_COMPLETED)
                    if not done or any(not future.result()['ok'] for future in done):
                        break
            unchanged = all(program.first_cycles.get(device_id) is future for device_id, future in cycles.items())
            if program.run_id != run_id or not unchanged:
                return dict(failure('STOPPED', 'That phone cycle was replaced by a later explicit update.'),
                            result=self._status(program))
            if not self._allowed(program.owner) or not authorized():
                self._invalidate(program, 'PERMISSION')
                return dict(failure('PERMISSION', 'Access ended while waiting for the first phone cycle.'),
                            result=self._status(program))
            failed = [future.result() for future in cycles.values()
                      if future.done() and not future.result()['ok']]
            if failed or not program.active:
                code = failed[0]['code'] if failed else (program.reason or 'STOPPED')
                return dict(failure(code, 'The first phone cycle was not confirmed. No automatic replay was attempted.'),
                            result=self._status(program), unknown_device_ids=sorted(program.failure_devices))
            following = all(program.participants[device_id]['participant_state'] == 'following'
                            for device_id in cycles)
            return {'ok': True, 'complete': following, **({} if following else {'code': 'PENDING'}),
                    'result': self._status(program),
                    'message': ('Each selected phone acknowledged its first ON and OFF. Visible pulses and physical synchronization remain unverified.'
                                if following and cycles else 'Program updated; individual participant and cleanup status are reported separately.'
                                if following else 'Phone participation is pending; its first ON and OFF are not both acknowledged. Do not report visible pulses or synchronization.')}
        except asyncio.CancelledError:
            # A canceled caller must not leave an unreported, pending first ON
            # scheduled after its request ended. Background running jobs otherwise
            # survive completed native turns under their captured lease.
            if (program.run_id == run_id
                    and all(program.first_cycles.get(device_id) is future for device_id, future in cycles.items())
                    and any(not future.done() for future in cycles.values())):
                self._invalidate(program, 'CANCELLED')
            raise

    def _task(self, program, coroutine):
        task = asyncio.create_task(coroutine)
        program.tasks.add(task)
        task.add_done_callback(program.tasks.discard)
        return task

    async def _launch(self, program, authorized):
        program.audio_metadata_guard = self.registry.metadata.guard((program.audio.id,))
        if any(self._light_owners.get(device_id) is not program
               or program.light_locks.get(device_id) is not self.device_locks[device_id]
               or not self.device_locks[device_id].locked() for device_id in program.lights):
            return failure('CONFLICT', 'Phone ownership changed before restart. No new beat was launched.')
        program.state, program.reason, program.cleanup = 'starting', None, {}
        program.failure_devices.clear()
        program.cleanup_task = None
        program.cleanup_workers = {}
        program.run_id = 'b_' + uuid.uuid4().hex
        remaining = max(0, program.owner.lease.expires_at - self.leases.clock())
        args = {'program_id': program.run_id, 'bpm': program.bpm,
                'expires_at_ms': (self.wall_clock() + remaining) * 1000}
        try:
            def permitted(dev, cap, _):
                return (authorized() and self._allowed(program.owner)
                        and self._connection(dev, program.audio_connection) and dev is program.audio
                        and self.leases.allows(program.owner.lease, dev, cap))
            prepared = await self.bus.call(program.audio.id, 'beat.prepare', args,
                                           timeout=self.action_timeout, authorize=permitted)
            data = prepared.result if isinstance(prepared.result, dict) else {}
            if not prepared.ok or data.get('program_id') != program.run_id or data.get('state') != 'prepared':
                self._invalidate(program, prepared.code or 'UNKNOWN')
                return failure(prepared.code or 'UNKNOWN', 'Beat preparation was not confirmed. No playback start was sent.')
            result = await self.bus.call(program.audio.id, 'beat.start', {'program_id': program.run_id},
                                         timeout=self.action_timeout, authorize=permitted)
            data = result.result if isinstance(result.result, dict) else {}
            launched = data.get('launched_at_ms')
            if (not result.ok or data.get('program_id') != program.run_id or data.get('state') != 'launched'
                    or type(launched) not in (int, float) or not math.isfinite(launched)):
                self._invalidate(program, result.code or 'UNKNOWN')
                return failure(result.code or 'UNKNOWN', 'Generated beat launch was not confirmed. It was not repeated.')
            if not self._allowed(program.owner) or not authorized():
                self._invalidate(program, 'PERMISSION')
                return failure('PERMISSION', 'Access ended while the beat launch was in flight. Cleanup status may be unknown.')
            program.phase_wall_ms = launched
            program.phase = self.clock() + launched / 1000 - self.wall_clock()
            program.active, program.state = True, 'running'
            program.monitor_task = self._task(program, self._monitor(program))
            for dev, connection in program.lights.values():
                self._begin_first_cycle(program, dev.id)
                program.light_tasks[dev.id] = self._task(program, self._light_loop(program, dev, connection))
            return {'ok': True, 'result': self._status(program),
                    'message': 'Generated beat process launched on the default audio output; audibility and physical sync remain unverified.'}
        except BaseException as exc:
            self._invalidate(program, 'UNKNOWN')
            if isinstance(exc, asyncio.CancelledError):
                raise
            return failure('UNKNOWN', 'Generated beat outcome is unknown. No automatic replay or substitution.')

    async def _launch_song(self, program, authorized):
        program.audio_metadata_guard = self.registry.metadata.guard((program.audio.id,))
        program.run_id = 's_' + uuid.uuid4().hex
        remaining = max(0, program.owner.lease.expires_at - self.leases.clock())
        args = {'program_id': program.run_id, 'song_id': program.song_id,
                'expires_at_ms': (self.wall_clock() + remaining) * 1000}
        def permitted(dev, cap, _):
            return (authorized() and self._allowed(program.owner) and dev is program.audio
                    and self._connection(dev, program.audio_connection)
                    and self.leases.allows(program.owner.lease, dev, cap))
        try:
            result = await self.bus.call(program.audio.id, 'song.prepare', args,
                                         timeout=self.action_timeout, authorize=permitted)
            data = result.result if isinstance(result.result, dict) else {}
            if not result.ok or data.get('program_id') != program.run_id or data.get('state') != 'prepared':
                self._invalidate(program, result.code or 'FAILED')
                return failure(result.code or 'FAILED', 'Selected recording preparation was not confirmed. No start was sent.')
            program.song_timeline = SongTimeline(data.get('recording'))
            if program.song_timeline.recording['song_id'] != program.song_id:
                raise ValueError('Selected song identity changed')
            program.bpm = program.song_timeline.bpm
            sent = {}
            result = await self.bus.call(program.audio.id, 'song.start', {'program_id': program.run_id},
                timeout=self.action_timeout, authorize=permitted,
                on_dispatch=lambda *_: sent.__setitem__('at', self.clock()))
            data = result.result if isinstance(result.result, dict) else {}
            if not result.ok or data.get('program_id') != program.run_id or data.get('state') not in ('playing', 'buffering'):
                self._invalidate(program, result.code or 'UNKNOWN')
                return failure(result.code or 'UNKNOWN', 'Selected recording start was not confirmed; it was not repeated.')
            program.song_timeline.observe(data, sent['at'], self.clock())
            if not self._allowed(program.owner) or not authorized():
                self._invalidate(program, 'PERMISSION')
                return failure('PERMISSION', 'Access ended during song start; owned cleanup is being recorded.')
            program.active, program.state = True, 'running'
            program.monitor_task = self._task(program, self._monitor(program))
            ready = program.song_timeline.ready(self.clock())
            return {'ok': True, 'complete': ready, **({} if ready else {'code': 'PENDING'}),
                    'result': self._status(program),
                    'message': 'Selected recording start accepted. Live playhead/beat estimate status is reported; hearing and physical light alignment remain unverified.'}
        except BaseException as exc:
            self._invalidate(program, 'UNKNOWN')
            if isinstance(exc, asyncio.CancelledError):
                raise
            return failure('UNKNOWN', 'Selected recording outcome is unknown; no start replay or substitution.')

    async def _monitor(self, program):
        metadata_guard = program.audio_metadata_guard
        next_status = self.clock() + (min(.25, program.song_timeline.ttl / 2) if program.song_id else 1)
        try:
            while program.active:
                if (not metadata_guard() or not self._allowed(program.owner)
                        or not self._connection(program.audio, program.audio_connection)):
                    self._invalidate(program, 'PERMISSION_OR_OFFLINE')
                    return
                if self.clock() >= next_status:
                    try:
                        dispatched = {}
                        def status_sent(req, _):
                            program.status_dispatch = req
                            dispatched['at'] = self.clock()
                        result = await self.bus.call(program.audio.id, 'song.status' if program.song_id else 'beat.status', {'program_id': program.run_id},
                            timeout=self.action_timeout,
                            authorize=lambda dev, cap, _: metadata_guard() and program.active and self._allowed(program.owner)
                            and dev is program.audio and self._connection(dev, program.audio_connection)
                            and self.leases.allows(program.owner.lease, dev, cap),
                            on_dispatch=status_sent)
                    finally:
                        program.status_dispatch = None
                    if not program.active:
                        return  # Settle the already-sent read before owned audio stop.
                    data = result.result if isinstance(result.result, dict) else {}
                    if not result.ok and result.code == 'TIMEOUT' and result.req is None:
                        # A read queued behind ordinary speech says nothing about
                        # the already-playing beat. No effect is retried here.
                        self.log.append('program', 'A room program status check waited for the speaker.',
                                        program_id=program.id, status='UNSENT_QUEUE_TIMEOUT')
                        next_status = self.clock() + .25
                        await self.sleep(.05)
                        continue
                    if program.song_id and result.ok and data.get('program_id') == program.run_id:
                        try:
                            program.song_timeline.observe(data, dispatched['at'], self.clock())
                        except (ValueError, KeyError):
                            self._invalidate(program, 'INVALID_SONG_CLOCK')
                            return
                        if data.get('state') in ('paused', 'ended'):
                            self._invalidate(program, 'SONG_' + data['state'].upper())
                            return
                        next_status = self.clock() + min(.25, program.song_timeline.ttl / 2)
                        continue
                    if not result.ok or data.get('program_id') != program.run_id or data.get('state') != 'launched':
                        self._invalidate(program, result.code or 'AUDIO_STOPPED')
                        return
                    next_status = self.clock() + 1
                await self.sleep(.05)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._invalidate(program, 'UNKNOWN')

    async def _song_edge(self, program, dev, connection, on, due, deadline, beat_number, discontinuity, metadata_guard):
        timeline = program.song_timeline
        dispatched = {}
        def permitted(current, cap, _):
            allowed = (metadata_guard() and program.active and self._allowed(program.owner) and dev.id not in program.detached
                       and self.clock() < deadline and current is dev and self._connection(dev, connection)
                       and self._light_owners.get(dev.id) is program
                       and self.leases.allows(program.owner.lease, current, cap)
                       and (not on or timeline.ready(self.clock()) and timeline.discontinuity == discontinuity))
            if allowed:
                dispatched['at'] = self.clock()
            return allowed
        try:
            result = await self.bus.call(dev.id, 'light', {'on': on},
                timeout=min(self.action_timeout, max(.001, deadline - self.clock())), authorize=permitted,
                on_dispatch=lambda req, _: program.light_dispatches.__setitem__(dev.id, req))
        finally:
            program.light_dispatches.pop(dev.id, None)
        record = {'device_id': dev.id, 'on': on, 'song_id': program.song_id,
                  'song_beat_number': beat_number, 'song_time_seconds': timeline.beat_time(beat_number),
                  'target_monotonic_ms': round(due * 1000, 3),
                  'dispatch_monotonic_ms': round(dispatched['at'] * 1000, 3) if 'at' in dispatched else None,
                  'ack_monotonic_ms': round(self.clock() * 1000, 3),
                  'playhead_uncertainty_ms': round(timeline.sample['uncertainty'] * 1000, 3),
                  'ack_code': 'OK' if result.ok else result.code, 'req': result.req}
        program.timings.append(record)
        del program.timings[:-1000]
        self.log.append('program', 'A selected recording light timing was recorded.', program_id=program.id, **record)
        confirmed = result.ok and isinstance(result.result, dict) and result.result.get('on') is on
        if not confirmed:
            if on and result.req is None and result.code in ('TIMEOUT', 'PERMISSION'):
                program.missed_ticks += 1
                return False  # known unsent: wait for a fresh future beat, never catch up
            self._invalidate(program, result.code or 'UNKNOWN', dev.id)
            return False
        program.last_on[dev.id] = on
        if program.active and dev.id not in program.detached:
            participant = program.participants[dev.id]
            cycle = participant['first_cycle']
            if on:
                cycle['on_ack'] = True
            elif cycle['on_ack']:
                cycle['off_ack'] = True
                participant['participant_state'] = 'following'
                future = program.first_cycles[dev.id]
                if not future.done():
                    future.set_result({'ok': True})
        return True

    async def _song_light_loop(self, program, dev, connection, metadata_guard):
        timeline = program.song_timeline
        cadence = program.light_cadences.get(dev.id, 1)
        try:
            while program.active and dev.id not in program.detached:
                if not metadata_guard() or not self._allowed(program.owner):
                    self._invalidate(program, 'PERMISSION')
                    return
                if not timeline.ready(self.clock()):
                    await self.sleep(.05)
                    continue
                cycle = timeline.next_cycle(self.clock(), cadence)
                number = cycle * 2 * cadence
                targets = [timeline.due(number + offset * cadence) for offset in (0, 1, 2)]
                if any(value is None for value in targets):
                    # The song may have a trailing section without detected beats.
                    # Stop only this phone; do not fabricate a constant-BPM tail.
                    self._task(program, self._detach(program, dev.id))
                    return
                discontinuity = timeline.discontinuity
                while self.clock() < targets[0]:
                    await self.sleep(min(.05, targets[0] - self.clock()))
                    if not metadata_guard():
                        self._invalidate(program, 'PERMISSION')
                        return
                    if not program.active or dev.id in program.detached:
                        return
                    if not timeline.ready(self.clock()) or timeline.discontinuity != discontinuity:
                        break
                    targets = [timeline.due(number + offset * cadence) for offset in (0, 1, 2)]
                if not timeline.ready(self.clock()) or timeline.discontinuity != discontinuity:
                    continue
                if self.clock() >= targets[1]:
                    program.missed_ticks += 1
                    continue
                if not await self._song_edge(program, dev, connection, True, targets[0], targets[1], number, discontinuity, metadata_guard):
                    await self.sleep(.01)
                    continue
                # OFF stays available even if the clock becomes stale/seeked.
                while self.clock() < targets[1] and timeline.discontinuity == discontinuity:
                    await self.sleep(min(.05, targets[1] - self.clock()))
                    if not metadata_guard():
                        self._invalidate(program, 'PERMISSION')
                        return
                    if not program.active or dev.id in program.detached:
                        return
                if not program.active or dev.id in program.detached:
                    return
                due = min(targets[1], self.clock())
                if not await self._song_edge(program, dev, connection, False, due,
                    max(targets[2], self.clock() + self.action_timeout), number + cadence, discontinuity, metadata_guard):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            self._invalidate(program, 'UNKNOWN', dev.id)

    async def _light_loop(self, program, dev, connection):
        # Captured synchronously when this participant/run was installed. A
        # revoke followed by re-enable never resumes an old pulse sequence.
        audio_guard = program.audio_metadata_guard
        light_guard = program.light_metadata_guards[dev.id]
        metadata_guard = lambda: audio_guard() and light_guard()
        if program.song_id:
            return await self._song_light_loop(program, dev, connection, metadata_guard)
        audio_period = 60 / program.bpm
        # The existing boolean bridge has measured ACKs up to 197 ms. A 90 BPM
        # quarter pulse allowed only 166.7 ms. The controlled 60 BPM baseline now
        # provides 500 ms ON and OFF windows; this is not an optical sync claim.
        pulse = audio_period * program.light_cadences.get(dev.id, .5)
        period = 2 * pulse  # ON every other audio beat when beats_per_state=1.
        beat = next_beat_index(program.phase, self.clock(), period)
        try:
            while program.active and dev.id not in program.detached:
                target = program.phase + beat * period
                for on, due, deadline in ((True, target, target + pulse), (False, target + pulse, target + period)):
                    await self.sleep(max(0, due - self.clock()))
                    if dev.id in program.detached:
                        return
                    if not metadata_guard() or not program.active or not self._allowed(program.owner):
                        self._invalidate(program, 'PERMISSION')
                        return
                    if self.clock() >= deadline:
                        if on:
                            next_beat = max(beat + 1, next_beat_index(program.phase, self.clock(), period))
                            program.missed_ticks += next_beat - beat
                            beat = next_beat
                            break  # Skip an unsent stale ON; never catch up a backlog.
                        self._invalidate(program, 'MISSED_OFF_TICK', dev.id)
                        return
                    sent = self.clock()
                    dispatch_time = {}
                    def permitted(current, cap, _):
                        allowed = (metadata_guard() and program.active and self._allowed(program.owner)
                                   and dev.id not in program.detached
                                   and self.clock() < deadline and current is dev
                                   and self._connection(current, connection)
                                   and self._light_owners.get(dev.id) is program
                                   and self.leases.allows(program.owner.lease, current, cap))
                        if allowed:
                            dispatch_time['at'] = self.clock()
                        return allowed
                    try:
                        result = await self.bus.call(dev.id, 'light', {'on': on},
                            timeout=min(self.action_timeout, max(.001, deadline - self.clock())),
                            authorize=permitted,
                            on_dispatch=lambda req, _: program.light_dispatches.__setitem__(dev.id, req))
                    finally:
                        program.light_dispatches.pop(dev.id, None)
                    ack = self.clock()
                    record = {'device_id': dev.id, 'on': on, 'target_monotonic_ms': round(due * 1000, 3),
                              'bus_call_monotonic_ms': round(sent * 1000, 3), 'ack_monotonic_ms': round(ack * 1000, 3),
                              'dispatch_monotonic_ms': round(dispatch_time['at'] * 1000, 3) if 'at' in dispatch_time else None,
                              'ack_code': 'OK' if result.ok else result.code, 'req': result.req}
                    program.timings.append(record)
                    del program.timings[:-1000]
                    self.log.append('program', 'A room program timing was recorded.', program_id=program.id, **record)
                    if not result.ok or not isinstance(result.result, dict) or result.result.get('on') is not on:
                        if (on and dispatch_time.get('at') is None and result.code in ('TIMEOUT', 'PERMISSION')
                                and self.clock() >= deadline and self._allowed(program.owner)
                                and self._connection(dev, connection)):
                            next_beat = max(beat + 1, next_beat_index(program.phase, self.clock(), period))
                            program.missed_ticks += next_beat - beat
                            beat = next_beat
                            break
                        self._invalidate(program, result.code or 'UNKNOWN', dev.id)
                        return
                    program.last_on[dev.id] = on
                    if not program.active or dev.id in program.detached:
                        return  # An already-sent edge settled; no next edge is authorized.
                    participant = program.participants[dev.id]
                    cycle = participant['first_cycle']
                    if on:
                        cycle['on_ack'] = True
                    elif cycle['on_ack']:
                        cycle['off_ack'] = True
                        participant['participant_state'] = 'following'
                        ready = program.first_cycles[dev.id]
                        if not ready.done():
                            ready.set_result({'ok': True})
                else:
                    beat += 1  # Never catch up missed beats or replay a previous edge.
        except asyncio.CancelledError:
            raise
        except Exception:
            self._invalidate(program, 'UNKNOWN', dev.id)

    def _invalidate(self, program, reason, device_id=None):
        if program.cleanup_task is not None:
            return
        if device_id is not None and reason == 'UNKNOWN':
            program.failure_devices.add(device_id)
        program.active, program.state, program.reason = False, 'stopping', reason
        intentional = reason in ('requested_stop', 'ACCESS_ENDED', 'PERMISSION', 'SHUTDOWN', 'CANCELLED', 'tempo_change')
        for participant_id, participant in program.participants.items():
            participant['participant_state'] = 'detached' if intentional else 'unknown'
            ready = program.first_cycles[participant_id]
            if not ready.done():
                ready.set_result({'ok': False, 'code': reason})
        for task in tuple(program.tasks):
            dispatched = any(program.light_tasks.get(device_id) is task for device_id in program.light_dispatches)
            dispatched = dispatched or (task is program.monitor_task and program.status_dispatch is not None)
            if task is not asyncio.current_task() and not dispatched:
                task.cancel()
        # Create phone workers synchronously: a later fresh OFF can settle just
        # its phone, independently of an audio stop waiting behind narration.
        program.cleanup_workers = {'audio': asyncio.create_task(self._stop_audio_after_status(program))}
        for dev, connection in program.lights.values():
            if program.cleanup.get(dev.id) != 'unknown':
                program.cleanup_workers[dev.id] = asyncio.create_task(self._stop_phone_after_steps(program, dev, connection))
        program.cleanup_task = asyncio.create_task(self._cleanup(program))

    async def _cleanup(self, program):
        # This authority can only stop effects already owned by this exact job;
        # it never borrows a host credential or authorizes a new ON/start effect.
        await asyncio.gather(*program.cleanup_workers.values())
        keep_for_restart = (program.reason == 'tempo_change' and program.restart_pending
                            and self._allowed(program.owner) and program.restart_allowed()
                            and all(v == 'confirmed' for v in program.cleanup.values()))
        if not keep_for_restart:
            self._release_clean_lights(program)
        program.state = 'stopped' if all(v == 'confirmed' for v in program.cleanup.values()) else 'unknown'
        self.log.append('program', 'Future room program steps stopped; cleanup status was recorded.',
                        program_id=program.id, reason=program.reason, cleanup=dict(program.cleanup))

    def _release_clean_lights(self, program):
        for device_id in program.lights:
            self._release_clean_light(program, device_id)

    def _release_clean_light(self, program, device_id):
        if (self._light_owners.get(device_id) is program
                and program.cleanup.get(device_id) == 'confirmed'):
            self._light_owners.pop(device_id, None)
            lock = program.light_locks.pop(device_id, None)
            if lock is not None:
                lock.release()

    async def _stop_phone_after_steps(self, program, dev, connection):
        task = program.light_tasks.get(dev.id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await self._stop_output(program, dev, connection, 'light', {'on': False}, dev.id,
                                lambda data: data.get('on') is False)

    async def _stop_audio_after_status(self, program):
        if program.monitor_task is not None:
            await asyncio.gather(program.monitor_task, return_exceptions=True)
        await self._stop_output(program, program.audio, program.audio_connection, 'song.stop' if program.song_id else 'beat.stop', {'program_id': program.run_id},
                                'audio', lambda data: data.get('program_id') == program.run_id and data.get('stopped') is True)

    async def _stop_output(self, program, dev, connection, cap, args, name, confirmed):
        key = (cap, dev.id, program.run_id)
        task = program.output_cleanup.get(key)
        if task is None:
            task = asyncio.create_task(self._stop_once(program, dev, connection, cap, args, name, confirmed))
            program.output_cleanup[key] = task
        await asyncio.shield(task)

    async def _stop_once(self, program, dev, connection, cap, args, name, confirmed):
        try:
            result = await self.bus.call(dev.id, cap, args,
                timeout=self.audio_queue_timeout if cap in ('beat.stop', 'song.stop') else self.action_timeout,
                authorize=lambda current, *_: self.programs.get(program.id) is program
                and (not program.active or dev.id in program.detached)
                and current is dev and self._connection(current, connection)
                and (cap in ('beat.stop', 'song.stop') or self._light_owners.get(dev.id) is program))
            data = result.result if isinstance(result.result, dict) else {}
            program.cleanup[name] = 'confirmed' if result.ok and confirmed(data) else 'unknown'
        except (Exception, asyncio.CancelledError):
            program.cleanup[name] = 'unknown'

    async def _detach(self, program, device_id):
        if not isinstance(device_id, str) or device_id not in program.lights:
            return failure('INVALID', 'That phone is not a participant in this program.')
        if device_id in program.detached:
            return failure('UNKNOWN', 'Phone detach cleanup is already unconfirmed; it was not retried.')
        self._end_phone_steps(program, device_id)
        task = asyncio.create_task(self._detach_once(program, device_id))
        program.detach_tasks[device_id] = task
        return await asyncio.shield(task)

    def _end_phone_steps(self, program, device_id):
        program.detached.add(device_id)  # Synchronous: queued/future ON authorization ends now.
        participant = program.participants[device_id]
        participant['participant_state'] = 'detached'
        ready = program.first_cycles[device_id]
        if not ready.done():
            ready.set_result({'ok': False, 'code': 'STOPPED'})
        task = program.light_tasks.get(device_id)
        if task is not None and device_id not in program.light_dispatches:
            task.cancel()  # Unsent sleep/queue work; dispatched calls retain their own bounded deadline.

    async def _detach_once(self, program, device_id):
        task = program.light_tasks.get(device_id)
        if task is not None:
            if device_id not in program.light_dispatches:
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if program.light_tasks.get(device_id) is task:
                program.light_tasks.pop(device_id, None)
        dev, connection = program.lights[device_id]
        await self._stop_output(program, dev, connection, 'light', {'on': False}, device_id,
                                lambda data: data.get('on') is False)
        if program.cleanup.get(device_id) != 'confirmed':
            program.participants[device_id]['participant_state'] = 'unknown'
            return dict(failure('UNKNOWN', 'Phone cleanup is unconfirmed; music continues, but this phone stays reserved. Do not retry automatically.'),
                        result=self._status(program))
        self._release_clean_lights(program)
        program.lights.pop(device_id)
        program.light_cadences.pop(device_id, None)
        program.detached.discard(device_id)
        return {'ok': True, 'result': self._status(program),
                'message': ('Phone left the beat and confirmed OFF. Music continues; a new ordinary phone action is now permitted.'
                            if program.active else 'Phone cleanup was confirmed; its room program also stopped.')}

    async def explicit_off(self, grant, device_id, *, authorized=lambda: True, timeout=5):
        """One newly requested guest OFF, never a retry of an earlier effect.

        Retire that phone's future steps and settle prior possible sends first.
        Bus uncertainty is never cleared here; only its actual receipt can do so.
        This route uses the current guest's light permission, including when an
        inactive earlier job still reserves the phone. It cannot adopt that job.
        """
        owner = ProgramOwner.from_grant(grant)
        dev = self.registry.devices.get(device_id) if isinstance(device_id, str) else None
        connection = getattr(dev, 'ws', None)
        loop = asyncio.get_running_loop()
        remaining = min(timeout, max(0, grant.lease.expires_at - self.leases.clock()))
        deadline = min(getattr(grant, 'deadline', loop.time() + remaining), loop.time() + remaining)
        def allowed():
            return (self._allowed(owner) and authorized() and loop.time() < deadline
                    and dev is not None and self._connection(dev, connection)
                    and 'light' in dev.caps and self.leases.allows(grant.lease, dev, 'light'))
        if dev is None or not self._connection(dev, connection):
            return failure('OFFLINE', 'That exact phone bridge is unavailable; no command was sent.')
        if not allowed():
            return failure('PERMISSION', 'This guest cannot turn off that exact connected phone.')
        claim, acquired, held, req = None, None, False, None
        def capture(request_id):
            nonlocal req
            req = request_id
        try:
            async with asyncio.timeout_at(deadline):
                async with self._off_locks[device_id]:
                    if not allowed():
                        return failure('PERMISSION', 'Access or the exact phone connection changed before OFF.')
                    claim = self._light_owners.get(device_id)
                    if claim is not None:
                        participant = claim.lights.get(device_id)
                        if participant is None or participant[0] is not dev or participant[1] is not connection:
                            return failure('OFFLINE', 'The reserved phone bridge changed. Disconnect and release its camera locally; no command was sent.')
                        self._end_phone_steps(claim, device_id)
                        tasks = {task for task in (claim.light_tasks.get(device_id), claim.detach_tasks.get(device_id),
                                                  claim.cleanup_workers.get(device_id)) if task is not None and not task.done()}
                        tasks.update(task for (_, target, _), task in claim.output_cleanup.items()
                                     if target == device_id and not task.done())
                        if tasks:
                            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
                        current_claim = self._light_owners.get(device_id)
                        if current_claim is not claim:
                            if current_claim is None and claim.cleanup.get(device_id) == 'confirmed':
                                claim = None  # The earlier owned cleanup already released its claim.
                            else:
                                return failure('CONFLICT', 'Phone ownership changed while OFF was waiting. Nothing was sent.')
                    if claim is None:
                        acquired = self.device_locks[device_id]
                        await acquired.acquire()
                        held = True
                    while any(current is dev for current in self.bus.uncertain.values()):
                        if not self._connection(dev, connection):
                            return failure('OFFLINE', 'The exact phone bridge changed while OFF was waiting; no command was sent.')
                        if not allowed():
                            return failure('PERMISSION', 'Access or the exact phone connection changed while waiting for the previous action.')
                        await asyncio.sleep(min(.01, max(0, deadline - loop.time())))
                    if not self._connection(dev, connection):
                        return failure('OFFLINE', 'The exact phone bridge changed while OFF was waiting; no command was sent.')
                    def permitted(current, *_):
                        return (allowed() and current is dev
                                and self._light_owners.get(device_id) is claim
                                and (claim is None or device_id in claim.detached))
                    result = await self.bus.call(device_id, 'light', {'on': False},
                        timeout=max(.001, deadline - loop.time()), authorize=permitted,
                        on_dispatch=lambda request_id, _: capture(request_id))
                    data = result.result if isinstance(result.result, dict) else {}
                    confirmed = result.ok and data.get('on') is False
                    if not confirmed:
                        if claim is not None and self._light_owners.get(device_id) is claim:
                            claim.cleanup[device_id] = 'unknown'
                            claim.participants[device_id]['participant_state'] = 'unknown'
                        return dict(failure(result.code or 'UNKNOWN', 'The newly requested OFF was not confirmed. Do not retry automatically; disconnect and release the phone camera locally if needed.'),
                                    status='unknown' if req else 'unsent', req=req,
                                    unknown_device_ids=[device_id])
                    if claim is not None and self._light_owners.get(device_id) is claim:
                        claim.cleanup[device_id] = 'confirmed'
                        claim.recovery[device_id] = {'source': 'guest explicit OFF acknowledgment', 'req': result.req}
                        claim.participants[device_id]['participant_state'] = 'detached'
                        self._release_clean_light(claim, device_id)
                        if claim.active:
                            claim.lights.pop(device_id, None)
                            claim.light_cadences.pop(device_id, None)
                            claim.detached.discard(device_id)
                        elif (claim.cleanup_task is not None and claim.cleanup_task.done()
                              and all(value == 'confirmed' for value in claim.cleanup.values())):
                            claim.state = 'stopped'
                    return {'ok': True, 'status': 'confirmed', 'result': {'on': False}, 'req': result.req,
                            'message': 'The phone acknowledged the newly requested OFF. Its future program light steps are stopped.'}
        except (TimeoutError, asyncio.CancelledError):
            if claim is not None and self._light_owners.get(device_id) is claim:
                claim.cleanup[device_id] = 'unknown'
                claim.participants[device_id]['participant_state'] = 'unknown'
            return dict(failure('UNKNOWN' if req or any(current is dev for current in self.bus.uncertain.values()) else 'TIMEOUT',
                        'OFF could not be confirmed within this request. No automatic retry was sent. Disconnect and release the phone camera locally if needed.'),
                        status='unknown' if req else 'unsent', req=req, unknown_device_ids=[device_id])
        finally:
            if held:
                acquired.release()

    def access_ended(self, guest_id):
        for program in self.programs.values():
            if program.owner.guest_id == guest_id and program.state in ('starting', 'running'):
                self._invalidate(program, 'ACCESS_ENDED')
            elif program.owner.guest_id == guest_id and not self._allowed(program.owner):
                self._release_clean_lights(program)

    async def quiesce(self):
        """Settle ended jobs before the already-authorized host reset cleans devices."""
        for program in self.programs.values():
            if program.active and not self._allowed(program.owner):
                self._invalidate(program, 'ACCESS_ENDED')
        tasks = {task for program in self.programs.values() if not program.active for task in program.tasks}
        tasks.update(program.cleanup_task for program in self.programs.values()
                     if not program.active and program.cleanup_task is not None)
        tasks.update(task for program in self.programs.values() if not program.active for task in program.detach_tasks.values())
        tasks.update(task for program in self.programs.values() if not program.active for task in program.output_cleanup.values())
        tasks.update(task for program in self.programs.values() if not program.active for task in program.cleanup_workers.values())
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                # Output cleanup is shielded from individual caller cancellation,
                # but a timed-out reset must settle its own work, not orphan it.
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                output = {task for p in self.programs.values() if not p.active for task in p.output_cleanup.values()}
                for task in output:
                    task.cancel()
                await asyncio.gather(*output, return_exceptions=True)
                raise
        return self.cleanup_confirmed()

    def cleanup_confirmed(self):
        return all(not program.active and program.state == 'stopped' and bool(program.cleanup)
                   and all(value == 'confirmed' for value in program.cleanup.values())
                   for program in self.programs.values())

    def confirm_host_off(self, device, connection, result):
        """Consume an existing exact-bridge host-reset OFF receipt; send nothing.

        This is an internal callback after reset quiescence, never a guest route.
        A reconnect, intention, or unresolved earlier action cannot clear a claim.
        """
        program = self._light_owners.get(device.id)
        data = result.result if isinstance(result.result, dict) else {}
        participant = program.lights.get(device.id) if program is not None else None
        if (program is None or program.active or participant is None
                or participant[0] is not device or participant[1] is not connection
                or not self._connection(device, connection) or not result.ok or not result.req
                or data.get('on') is not False or any(owner is device for owner in self.bus.uncertain.values())
                or any(not task.done() for task in program.tasks)
                or any(not task.done() for task in program.detach_tasks.values())
                or any(not task.done() for task in program.output_cleanup.values())
                or any(not task.done() for task in program.cleanup_workers.values())
                or program.cleanup_task is None or not program.cleanup_task.done()):
            return False
        program.cleanup[device.id] = 'confirmed'
        program.recovery[device.id] = {'source': 'host-reset OFF acknowledgment', 'req': result.req}
        self._release_clean_lights(program)
        if all(value == 'confirmed' for value in program.cleanup.values()):
            program.state = 'stopped'
        return True

    async def close(self):
        self._closed = True
        for program in self.programs.values():
            if program.state in ('starting', 'running'):
                self._invalidate(program, 'SHUTDOWN')
            else:
                self._release_clean_lights(program)
        await self.quiesce()
