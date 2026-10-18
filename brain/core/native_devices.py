"""Turn-scoped local access to the existing device Bus, never host authority.

The native agent already has broad shell access. This private helper restores
enrolled light/audio controls; it is not OS isolation for that broader shell.
"""
from __future__ import annotations

import asyncio
import copy
from collections import defaultdict
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import tempfile

from brain.core.bus import Bus
from brain.core.copy import confirmed_sentence, failure_sentence, requested_sentence

MAX_REQUEST = 16_384
CAPABILITIES = frozenset({'light', 'volume', 'say', 'music.play', 'music.pause'})
BLINK_INTERVAL = .5


@dataclass
class TurnGrant:
    guest_id: str
    generation: int
    lease: object = field(repr=False)
    thread_id: str
    room_id: str
    epoch: int
    path: Path
    token: str = field(repr=False)
    turn_id: str | None = None
    closed: bool = False
    deadline: float | None = None
    explicit_speech_attempted: bool = False
    calls: dict = field(default_factory=dict, repr=False)
    unknown_devices: set = field(default_factory=set, repr=False)
    off_unknown_devices: set = field(default_factory=set, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def denied(code='PERMISSION', message='This turn has no current device authority. Nothing was sent.'):
    return {'ok': False, 'code': code, 'message': message}


class NativeDevices:
    def __init__(self, registry, bus, leases, log, current, *, action_timeout=5, read_timeout=2,
                 turn_timeout=120, speech_timeout=15):
        self.registry, self.bus, self.leases, self.log = registry, bus, leases, log
        self.current = current
        self.action_timeout, self.read_timeout = action_timeout, read_timeout
        self.turn_timeout = turn_timeout
        self.speech_timeout = speech_timeout
        self._directory = None
        self._server = None
        self._grants = {}
        self._clients = set()
        self._closed = False
        self._blink_sleep = asyncio.sleep
        self.device_locks = defaultdict(asyncio.Lock)
        self.programs = None
        self.reply_voice = None
        self.photos = None
        from brain.core.demo_photo import DemoPhotos
        self.demo_photos = DemoPhotos(self)
        from brain.core.prepared_qa import PreparedQA
        self.prepared_qa = PreparedQA(self)

    async def prepare(self, guest_id, generation, lease, thread_id):
        if self._closed:
            raise RuntimeError('Device helper is closed')
        if self._server is None:
            self._directory = tempfile.TemporaryDirectory(prefix='tenant-t-')
            directory = Path(self._directory.name)
            os.chmod(directory, 0o700)
            socket = directory / 'bus.sock'
            self._server = await asyncio.start_unix_server(self._handle, path=socket, limit=MAX_REQUEST + 1)
            os.chmod(socket, 0o600)
        token = secrets.token_urlsafe(32)
        path = Path(self._directory.name) / (secrets.token_hex(8) + '.json')
        grant = TurnGrant(guest_id, generation, lease, thread_id, self.registry.room.id,
                          self.registry.room.epoch, path, token)
        # Only the local helper reads this secret. No credential appears in the
        # model prompt, shell arguments, public frames or audit metadata.
        with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump({'socket': str(path.parent / 'bus.sock'), 'token': token,
                       'long_timeout': self.turn_timeout + 2, 'speech_timeout': self.speech_timeout + 2}, stream)
        self._grants[token] = grant
        return grant

    def activate(self, grant, turn_id):
        if not grant.closed:
            grant.turn_id = turn_id
            grant.deadline = asyncio.get_running_loop().time() + self.turn_timeout

    def finish(self, grant):
        if grant is None:
            return
        self.demo_photos.finish(grant)
        self.prepared_qa.finish(grant)
        grant.closed = True
        self._grants.pop(grant.token, None)
        grant.path.unlink(missing_ok=True)

    def revoke_all(self):
        for grant in tuple(self._grants.values()):
            self.finish(grant)
        self.demo_photos.invalidate()
        self.prepared_qa.invalidate()

    def redact(self, text):
        for grant in self._grants.values():
            text = text.replace(grant.token, '[private turn grant]').replace(str(grant.path), '[private helper]')
        if self._directory is not None:
            text = text.replace(self._directory.name, '[private helper]')
        return text

    def permitted(self, grant):
        return (not grant.closed and grant.turn_id is not None and grant.deadline is not None
                and asyncio.get_running_loop().time() < grant.deadline
                and self._grants.get(grant.token) is grant
                and self.registry.room.id == grant.room_id and self.registry.room.epoch == grant.epoch
                and self.leases.current(grant.guest_id) is grant.lease
                and self.current(grant))

    def context(self, grant):
        helper = Path(__file__).resolve().parents[2] / 'agent' / 'tenant_device.py'
        command = shlex.join([sys.executable, str(helper), '--context', str(grant.path)])
        text = (
            '[Tenant room integration context]\n'
            'LIVE room agent with broad computer tools: fulfill guest coding/artifact/app requests, '
            'not unrequested Tenant tests/rehearsals. Fulfill THIS request only. '
            'Mac apps/browser remain available beyond helper inventory; discover them for other media/tasks. '
            'Keep requested performances running after replying; change tempo/stop only on request. '
            'Backend ends access and handles faults. '
            'Start replies with a concise plain result within 160 characters; details can follow. '
            'Use this private helper for enrolled-device commands: inventory first, exact IDs/online state/schemas; '
            'multiple explicitly requested operations/devices are allowed. '
            'Ask for a choice on ambiguous/unavailable targets; never substitute. Preserve output/volume '
            'unless explicitly asked. Helper JSON confirms bridge actions; verify native apps/browser '
            'with fresh state, not shell exit/prose. '
            'UNKNOWN may have acted: stop dependent actions; never retry under another ID or claim cancellation. '
            'Keep helper paths/credentials out of routine replies.\n'
            f'Helper command prefix: {command}\n'
            'Use inventory (read-only), call, or light-blink with JSON stdin: '
            'call takes request_id,device_id,cap,args; light-blink takes request_id,device_id,count '
            '(any positive integer, default 3; 500ms ON/OFF intervals). Blink ends OFF only after ACK. '
            'Unique request_id per operation; duplicate IDs return recorded results without replay. '
            'Calls require this active turn/lease; no host bypass. '
            'New OFF: call light args {on:false}; it fences future ON, waits boundedly, then sends fresh OFF. '
            'Never replay ON. On unresolved/BUSY use phone page Disconnect/release camera; '
            'do not claim OFF or retry uncertain OFF under another ID this turn.\n'
            '[End Tenant room integration context]')
        if self.programs is not None:
            text += (
                '\nRoom programs: program-start, program-update, program-stop, program-status with JSON stdin. '
                'Start takes request_id,device_id and EITHER bpm for a generated beat OR exact song_id from '
                'inventory.programs.audio_devices[].songs for a real selected recording. Save program_id. '
                'Never substitute generated audio for requested music or invent a song/BPM. '
                'A song uses its analyzed beats plus live playhead; song_clock pending means timing unready, not synced. '
                'Catalog IDs limit managed beat-sync only; native apps/browser can play other media. '
                'Check playback first; never duplicate active music. Native app effects may persist after access ends. '
                'Audio continues through conversation. '
                'Update takes request_id,program_id plus bpm (generated only), light_device_id, remove_light_device_id, '
                'and/or light_beats_per_state with light_device_id. Cadence means beats per ON and OFF '
                '(generated default0.5; song default1; 1 means 2s each at30BPM). Omission preserves cadence. '
                'Stop/status take request_id,program_id. Attach PENDING/complete:false is accepted only; '
                'following/first_cycle ACKs confirm ON+OFF, never visible pulses or physical sync. '
                'Stale unsent ON is skipped; UNKNOWN stops dependent work. '
                'For non-OFF phone CONFLICT, detach with program-update/remove_light_device_id, '
                'then the original raw action with fresh request_id after confirmed detach; music may continue. '
                'Never retry UNKNOWN detach. BPM update restarts generated phase; song tempo edits unavailable. '
                'For a later request to show/hide the orb while a selected song already plays, check '
                'program.visual.update_available and audio_devices[].song_visual; use program-update with only '
                'request_id,program_id,visual (boolean). This toggles existing live visuals without reprepare/restart '
                'or light changes; no visual/timing mixed request. Do not start music again. Visual ACK does not '
                'prove physical rendering. Missing capability is UNSUPPORTED; UNKNOWN is no retry. '
                'Programs end with access; process/ACK timing never proves physical sync.')
        if self.reply_voice is not None:
            text += ('\nReply voice context: '
                     + json.dumps(self.reply_voice.context(grant), separators=(',', ':'))
                     + '. Text is default. Mention only a flagged enrolled-bridge offer once in chat. '
                     'Enable brief future voice only on explicit request; discovery never enables or substitutes. '
                     'One-off say never enables it; use say only for requested speech, not final narration. '
                     'Append reply-voice with JSON request_id,enabled:false; '
                     'or request_id,enabled:true,device_id,speaker_ref from inventory.reply_voice.')
        if self.photos is not None and self.photos.enabled:
            text += ('\nPhotos: use inventory.photos. photo-capture takes request_id,source_device_id; '
                     'photo-status takes request_id,capture_request_id. No raw camera calls or retries. '
                     'Captured/stored are not displayed; only a matching viewer receipt confirms rendering.')
        text += self.demo_photos.context(grant)
        text += self.prepared_qa.context(grant)
        demo_guide = Path(__file__).resolve().parents[2] / 'notes' / 'live-demo-agent.md'
        if demo_guide.is_file():
            text += ('\nPrepared local demos (drawing / sunset album, Photo Booth, fast judge Q&A): when requested, '
                     f'read {demo_guide} for current entry points and limitations. '
                     'iPad drawing input is not connected; current drawing input is Mac mouse/replay. '
                     'Use the real agent tools and visible controls; do not invent an input connection '
                     'or launch an unrequested rehearsal.')
        return text

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self._clients.add(task)
        try:
            if self._closed:
                return
            async with asyncio.timeout(self.read_timeout):
                line = await reader.readline()
            if not line.endswith(b'\n') or len(line) > MAX_REQUEST:
                response = denied('INVALID', 'Invalid helper request. Nothing was sent.')
            else:
                request = json.loads(line)
                response = await self._dispatch_connected(request, reader)
            if response is None:
                return
            writer.write(json.dumps(response, separators=(',', ':')).encode() + b'\n')
            async with asyncio.timeout(1):
                await writer.drain()
        except (Exception, asyncio.CancelledError):
            # No raw payload, token, device error or filesystem path is logged.
            pass
        finally:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (Exception, asyncio.CancelledError):
                pass
            self._clients.discard(task)

    async def _dispatch_connected(self, request, reader):
        disconnected = asyncio.create_task(reader.read(1))
        connected = lambda: not disconnected.done() and not reader.at_eof()
        operation = asyncio.create_task(self.dispatch(request, connected=connected))
        try:
            done, _ = await asyncio.wait((operation, disconnected), return_when=asyncio.FIRST_COMPLETED)
            # This protocol accepts exactly one request per connection. EOF or
            # extra input stops a sequence; it never schedules later ON edges.
            if disconnected in done:
                if not operation.done():
                    operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                return None
            return await operation
        finally:
            for task in (operation, disconnected):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, disconnected, return_exceptions=True)

    async def dispatch(self, request, *, connected=lambda: True):
        if not isinstance(request, dict) or not isinstance(request.get('token'), str):
            return denied()
        grant = self._grants.get(request['token'])
        if grant is None or not self.permitted(grant) or not connected():
            return denied()
        operation = request.get('operation')
        if operation == 'inventory' and set(request) == {'token', 'operation'}:
            devices = []
            for dev in self.registry.devices.values():
                if dev.room_id != grant.room_id:
                    continue
                caps = [{'name': spec.name, 'args': copy.deepcopy(spec.args), 'description': spec.description,
                         'available': self.registry.metadata.available(dev, spec.name)}
                        for spec in dev.caps.values() if spec.name in CAPABILITIES
                        and self.registry.metadata.described(dev, spec.name)
                        and ('*' in grant.lease.scopes or spec.name in grant.lease.scopes)]
                devices.append({'id': dev.id, 'label': dev.label, 'online': self.registry.metadata.binding(dev.id) is dev, 'busy': dev.busy,
                                'caps': caps, 'executable': any(cap['available'] for cap in caps),
                                'derived_operations': ([{'name': 'light-blink', 'args': {
                                    'count': {'type': 'integer', 'minimum': 1, 'default': 3}},
                                    'interval_ms': 500, 'bounded_by': 'current_turn_and_lease', 'ends_off_on_success': True}]
                                    if any(cap['name'] == 'light' and cap['available'] for cap in caps) else [])})
            return {'ok': True, 'devices': devices,
                    **({'programs': self.programs.inventory(grant)} if self.programs is not None else {}),
                    **({'reply_voice': self.reply_voice.inventory(grant)} if self.reply_voice is not None else {}),
                    **({'photos': self.photos.inventory(grant.lease, generation=grant.generation)}
                       if self.photos is not None else {})}
        valid_call = operation == 'call' and set(request) == {'token', 'operation', 'request_id', 'device_id', 'cap', 'args'}
        valid_blink = (operation == 'light-blink'
                       and {'token', 'operation', 'request_id', 'device_id'} <= set(request)
                       and set(request) <= {'token', 'operation', 'request_id', 'device_id', 'count'})
        fields = set(request) - {'token', 'operation'}
        valid_program = self.programs is not None and (
            (operation == 'program-start' and fields in ({'request_id', 'device_id', 'bpm'}, {'request_id', 'device_id', 'song_id'})) or
            (operation == 'program-update' and fields == {'request_id', 'program_id', 'visual'}
             and type(request.get('visual')) is bool) or
            (operation == 'program-update' and {'request_id', 'program_id'} < fields
             and fields <= {'request_id', 'program_id', 'bpm', 'light_device_id', 'remove_light_device_id', 'light_beats_per_state'}
             and ('light_beats_per_state' not in fields or 'light_device_id' in fields)) or
            (operation in ('program-stop', 'program-status') and fields == {'request_id', 'program_id'}))
        valid_voice = (self.reply_voice is not None and operation == 'reply-voice'
                       and type(request.get('enabled')) is bool
                       and ((request['enabled'] is False and fields == {'request_id', 'enabled'})
                            or (request['enabled'] is True
                                and fields == {'request_id', 'enabled', 'device_id', 'speaker_ref'}
                                and isinstance(request['device_id'], str)
                                and isinstance(request['speaker_ref'], str))))
        valid_photo = self.photos is not None and (
            (operation == 'photo-capture' and fields == {'request_id', 'source_device_id'}) or
            (operation == 'photo-status' and fields == {'request_id', 'capture_request_id'}))
        valid_demo_photo = (
            operation in ('demo-photo-prepare', 'demo-photo-status') and fields == {'request_id'}
            or operation in ('demo-photo-capture', 'demo-photo-cancel') and fields == {'request_id', 'photo_id'}
            and isinstance(request.get('photo_id'), str))
        valid_qa = operation in ('question-answer', 'question-answer-stop') and fields == {'request_id'}
        if not valid_call and not valid_blink and not valid_program and not valid_voice and not valid_photo and not valid_demo_photo and not valid_qa:
            return denied('INVALID', 'Invalid helper request. Nothing was sent.')
        request_id = request['request_id']
        if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 80
                or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in request_id)):
            return denied('INVALID', 'A short request ID is required. Nothing was sent.')
        payload = ({key: copy.deepcopy(request[key]) for key in ('device_id', 'cap', 'args')} if valid_call else
                   {key: copy.deepcopy(request[key]) for key in fields} if valid_program or valid_voice or valid_photo or valid_demo_photo or valid_qa else
                   {'device_id': copy.deepcopy(request['device_id']), 'count': copy.deepcopy(request.get('count', 3))})
        payload['operation'] = operation
        try:
            fingerprint = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError):
            return denied('INVALID', 'Invalid helper payload. Nothing was sent.')
        # Snapshot before any logical queue. Duplicate readers still receive the
        # original result even when later metadata has changed.
        program_targets = self._program_targets(grant, operation, payload) if valid_program else set()
        targets = program_targets if valid_program else ({payload['device_id']}
                  if isinstance(payload.get('device_id'), str) else set())
        if valid_photo and operation == 'photo-capture' and isinstance(payload.get('source_device_id'), str):
            targets.add(payload['source_device_id'])
        metadata_guard = self.registry.metadata.guard(targets)
        async with grant.lock:
            if not self.permitted(grant) or not connected():
                return denied()
            previous = grant.calls.get(request_id)
            if previous is not None:
                if previous[0] != fingerprint:
                    return denied('INVALID', 'Request ID changed. Nothing was sent.')
                future, owner = previous[1], False
            else:
                future, owner = asyncio.get_running_loop().create_future(), True
                grant.calls[request_id] = (fingerprint, future)
        if not owner:
            # Disconnecting a duplicate caller cannot cancel the original action.
            return copy.deepcopy(await asyncio.shield(future))
        caller_connected = connected
        connected = lambda: caller_connected() and metadata_guard()
        try:
            if valid_qa:
                if operation == 'question-answer':
                    grant.explicit_speech_attempted = True
                response = await self.prepared_qa.dispatch(grant, operation,
                    {key: value for key, value in payload.items() if key != 'operation'},
                    authorized=lambda: self.permitted(grant) and connected())
            elif valid_demo_photo:
                if operation in ('demo-photo-prepare', 'demo-photo-capture'):
                    grant.explicit_speech_attempted = True
                response = await self.demo_photos.dispatch(grant, operation,
                    {key: value for key, value in payload.items() if key != 'operation'},
                    authorized=lambda: self.permitted(grant) and connected())
            elif valid_photo:
                from brain.core.photos import PhotoError
                try:
                    if operation == 'photo-status':
                        response = self.photos.status(grant.lease, payload['capture_request_id'])
                    elif payload['source_device_id'] in grant.unknown_devices:
                        response = denied('UNKNOWN', 'That phone has an uncertain earlier action. Nothing was resent.')
                    else:
                        response = await self.photos.capture(grant.lease, payload['request_id'],
                            payload['source_device_id'], generation=grant.generation,
                            dispatch_allowed=lambda: self.permitted(grant) and connected()
                            and payload['source_device_id'] not in grant.unknown_devices)
                except PhotoError as error:
                    response = denied(error.code, error.message)
            elif valid_voice:
                response = self.reply_voice.set_voice(grant,
                    {key: value for key, value in payload.items() if key != 'operation'},
                    authorized=lambda: self.permitted(grant) and connected())
            elif valid_program:
                if program_targets & grant.unknown_devices:
                    response = denied('UNKNOWN', 'An affected device has an unknown earlier result. Nothing was resent; '
                                      'status, stop and detach-only cleanup remain available.')
                else:
                    async with asyncio.timeout_at(grant.deadline):
                        response = await self.programs.dispatch(grant, operation,
                            {key: value for key, value in payload.items() if key != 'operation'},
                            authorized=lambda: self.permitted(grant) and connected()
                            and not (program_targets & grant.unknown_devices))
            else:
                response = await self._execute(grant, payload, blink=valid_blink, connected=connected)
        except (Exception, asyncio.CancelledError):
            response = denied('UNKNOWN', 'The operation outcome is unknown. Do not retry or substitute.')
        if response.get('code') == 'UNKNOWN':
            if valid_program:
                ids = response.get('unknown_device_ids', program_targets)
                if isinstance(ids, (list, set, tuple)):
                    grant.unknown_devices.update(device_id for device_id in ids if isinstance(device_id, str))
            elif valid_photo:
                device_id = payload.get('source_device_id')
                if isinstance(device_id, str):
                    grant.unknown_devices.add(device_id)
            elif not valid_voice:
                device_id = payload.get('device_id')
                if isinstance(device_id, str):
                    grant.unknown_devices.add(device_id)
        future.set_result(copy.deepcopy(response))
        return response

    def _program_targets(self, grant, operation, payload):
        # Read-only status and explicit owned cleanup must remain available even
        # when prior physical outcomes are unknown. They never authorize replay.
        if operation == 'program-start':
            return {payload['device_id']} if isinstance(payload.get('device_id'), str) else set()
        if operation != 'program-update':
            return set()
        program = next((row for row in self.programs.inventory(grant).get('programs', [])
                        if row['program_id'] == payload.get('program_id')), None)
        if program is None:
            return set()
        targets = {program['audio_device_id']} if 'bpm' in payload or 'visual' in payload else set()
        if isinstance(payload.get('light_device_id'), str):
            targets.add(payload['light_device_id'])
        return targets

    def _program_conflict(self, device_id, grant=None):
        program_id = self.programs.device_busy(device_id) if self.programs is not None else None
        if program_id is None:
            return None
        if grant is not None and not any(program['program_id'] == program_id
                for program in self.programs.inventory(grant).get('programs', [])):
            return {'ok': False, 'code': 'CONFLICT', 'status': 'unsent', 'recovery': 'host_reset',
                    'message': 'This phone remains reserved by a previous program. Ask the host to reset or verify '
                               'the bridge; this guest cannot adopt that program. No action was sent.'}
        return {'ok': False, 'code': 'CONFLICT', 'status': 'unsent', 'program_id': program_id,
                'detach_operation': 'program-update', 'remove_light_device_id': device_id,
                'requires_new_request_id_after_confirmed_detach': True,
                'message': 'This phone follows a room program. Detach it with program-update/remove_light_device_id, '
                           'then submit the original action with a fresh request ID only after confirmed detach. Do not retry UNKNOWN cleanup.'}

    async def _execute(self, grant, payload, *, blink, connected):
        device_id = payload.get('device_id')
        if not isinstance(device_id, str):
            return denied('INVALID', 'A device ID is required. Nothing was sent.')
        if (not blink and self.programs is not None and payload.get('cap') == 'light'
                and isinstance(payload.get('args'), dict) and set(payload['args']) == {'on'}
                and payload['args']['on'] is False):
            return await self._explicit_off(grant, payload, connected)
        conflict = self._program_conflict(device_id, grant)
        if conflict is not None:
            return conflict
        original = self.registry.devices.get(device_id)
        connection = getattr(original, 'ws', None)
        deadline = min(grant.deadline, asyncio.get_running_loop().time()
                       + max(0, grant.lease.expires_at - self.leases.clock()))
        if not blink:
            budget = self.speech_timeout if payload.get('cap') == 'say' else self.action_timeout
            deadline = min(deadline, asyncio.get_running_loop().time() + budget)
        executing = False
        try:
            async with asyncio.timeout_at(deadline):
                # Preserve the whole logical sequence on one device. Other
                # devices remain concurrent, including a phone and laptop.
                async with self.device_locks[device_id]:
                    if not self.permitted(grant) or not connected():
                        return denied()
                    conflict = self._program_conflict(device_id, grant)
                    if conflict is not None:
                        return conflict
                    if (self.registry.devices.get(device_id) is not original
                            or getattr(original, 'ws', None) is not connection):
                        return denied('OFFLINE', 'The device connection changed. Nothing was sent.')
                    executing = True
                    return await (self._blink(grant, payload, connected=connected) if blink else
                                  self._call(grant, payload, connected=connected))
        except (Exception, asyncio.CancelledError) as error:
            if not executing:
                code = 'TIMEOUT' if isinstance(error, TimeoutError) else 'CANCELLED'
                return {**denied(code, 'The operation ended while waiting. Nothing was sent.'), 'status': 'unsent'}
            return {**denied('UNKNOWN', 'The operation outcome is unknown. Do not retry or substitute.'), 'status': 'unknown'}

    async def _explicit_off(self, grant, payload, connected):
        device_id = payload['device_id']
        if device_id in grant.off_unknown_devices:
            return denied('UNKNOWN', 'An earlier OFF outcome is unknown. Do not retry; use the phone device page Disconnect to release its camera.')
        device = self.registry.devices.get(device_id)
        connection = getattr(device, 'ws', None)
        if device is None or not device.online or device.room_id != grant.room_id or 'light' not in device.caps:
            return denied('OFFLINE', 'That exact phone is unavailable. Use its device page Disconnect to release the camera.')
        def authorized():
            return (device_id not in grant.off_unknown_devices and self.permitted(grant) and connected()
                    and self.registry.devices.get(device_id) is device
                    and device.ws is connection and self.leases.allows(grant.lease, device, 'light'))
        if not authorized():
            return denied()
        self.log.append('cmd', requested_sentence(grant.lease.display_name, device, 'light', {'on': False}),
                        guest_id=grant.guest_id, generation=grant.generation, thread_id=grant.thread_id,
                        turn_id=grant.turn_id, device_id=device_id, cap='light', compensating_off=True)
        try:
            remaining = min(self.action_timeout, grant.deadline - asyncio.get_running_loop().time(),
                            grant.lease.expires_at - self.leases.clock())
            async with asyncio.timeout(max(.001, remaining)):
                response = await self.programs.explicit_off(grant, device_id, authorized=authorized, timeout=remaining)
        except (Exception, asyncio.CancelledError):
            grant.off_unknown_devices.add(device_id)
            response = {**denied('UNKNOWN', 'The OFF result is unknown. Do not retry; use the phone device page Disconnect to release its camera.'),
                        'status': 'unknown'}
        if response.get('code') == 'UNKNOWN':
            grant.off_unknown_devices.add(device_id)
        self.log.append('ok' if response.get('ok') else 'err',
                        f'{device.label} acknowledged OFF.' if response.get('ok') else
                        'Phone OFF was not confirmed. Use its device page Disconnect if the result remains unknown.',
                        guest_id=grant.guest_id, generation=grant.generation, device_id=device_id, cap='light',
                        thread_id=grant.thread_id, turn_id=grant.turn_id, req=response.get('req'),
                        ok=response.get('ok') is True, code=response.get('code'), compensating_off=True)
        return response

    async def _blink(self, grant, payload, *, connected=lambda: True):
        device_id, count = payload['device_id'], payload['count']
        if not isinstance(device_id, str) or type(count) is not int or count < 1:
            return denied('INVALID', 'Blink requires one device and a positive integer count. Nothing was sent.')
        if device_id in grant.unknown_devices:
            return denied('UNKNOWN', 'A previous result for this device is unknown. Nothing was resent.')
        dev = self.registry.devices.get(device_id)
        if dev is None or dev.room_id != grant.room_id or not dev.online:
            return denied('OFFLINE', 'The requested light is unavailable. Nothing was sent; no other device was used.')
        if 'light' not in dev.caps or not self.leases.allows(grant.lease, dev, 'light'):
            return denied('PERMISSION', 'The requested light is unsupported or not permitted. Nothing was sent.')
        connection = dev.ws
        deadline = min(grant.deadline, asyncio.get_running_loop().time()
                       + max(0, grant.lease.expires_at - self.leases.clock()))
        confirmed, acknowledged, last_on, dispatches = 0, 0, None, []

        def permitted(current):
            return (self.permitted(grant) and connected() and asyncio.get_running_loop().time() < deadline
                    and self._program_conflict(device_id, grant) is None
                    and device_id not in grant.unknown_devices
                    and self.registry.devices.get(device_id) is dev
                    and current is dev and dev.ws is connection and dev.online
                    and self.leases.allows(grant.lease, dev, 'light'))

        def stopped(code):
            status = 'unsent' if not dispatches else 'partial' if confirmed else 'unknown'
            off_confirmed = last_on is False and len(dispatches) == acknowledged
            return {'ok': False, 'code': code,
                    'message': ('The blink sequence ended before dispatch. Nothing was sent.' if not dispatches else
                                'The blink sequence stopped before completion. Its last acknowledged state was OFF.' if off_confirmed else
                                'The blink sequence stopped. Its final OFF state was not confirmed; do not retry or substitute.'),
                    'status': status,
                    'result': {'cycles_completed': confirmed // 2, 'edges_confirmed': confirmed,
                               'edges_dispatched': len(dispatches), 'edges_acknowledged': acknowledged,
                               'last_confirmed_on': last_on, 'final_off_confirmed': off_confirmed,
                               'operation_complete': False}}

        try:
            async with asyncio.timeout_at(deadline):
                for edge in range(count * 2):
                    if not permitted(dev):
                        return stopped('PERMISSION')
                    on = edge % 2 == 0
                    self.log.append('cmd', requested_sentence(grant.lease.display_name, dev, 'light', {'on': on}),
                                    guest_id=grant.guest_id, generation=grant.generation, thread_id=grant.thread_id,
                                    turn_id=grant.turn_id, device_id=device_id, cap='light', operation='light-blink', edge=edge)
                    result = await self.bus.call(device_id, 'light', {'on': on},
                        timeout=min(self.action_timeout, max(.001, deadline - asyncio.get_running_loop().time())),
                        authorize=lambda current, *_: permitted(current),
                        on_dispatch=lambda req, _dev: dispatches.append(req))
                    matches = result.ok and isinstance(result.result, dict) and result.result.get('on') is on
                    if result.ok and isinstance(result.result, dict) and type(result.result.get('on')) is bool:
                        acknowledged += 1
                        last_on = result.result['on']
                    sentence = (confirmed_sentence(dev, 'light', {'on': on}, result.result) if matches else
                                failure_sentence(dev, 'light', {'on': on}, result) if not result.ok else
                                'The phone did not confirm the requested light state. The blink sequence stopped.')
                    self.log.append('ok' if matches else 'err', sentence, guest_id=grant.guest_id,
                                    generation=grant.generation, thread_id=grant.thread_id, turn_id=grant.turn_id,
                                    device_id=device_id, cap='light', operation='light-blink', edge=edge,
                                    req=result.req, ok=matches, code=result.code if not result.ok else None)
                    if not matches:
                        return stopped(result.code if not result.ok else 'UNKNOWN')
                    confirmed += 1
                    if edge < count * 2 - 1:
                        if not permitted(dev):
                            return stopped('PERMISSION')
                        await self._blink_sleep(BLINK_INTERVAL)
                        if not permitted(dev):
                            return stopped('PERMISSION')
        except (Exception, asyncio.CancelledError) as error:
            # A deadline, disconnect or revoked turn never gets an extra OFF
            # command under host authority. Explicit host reset handles cleanup.
            expired = isinstance(error, TimeoutError) or asyncio.get_running_loop().time() >= deadline
            return stopped('UNKNOWN' if len(dispatches) > acknowledged else 'TIMEOUT' if expired else 'CANCELLED')
        return {'ok': True, 'status': 'confirmed', 'result': {'count': count, 'cycles_completed': count,
                                      'edges_dispatched': len(dispatches), 'edges_acknowledged': acknowledged,
                                      'edges_confirmed': confirmed, 'on': False, 'final_off_confirmed': True,
                                      'operation_complete': True},
                'message': f'{dev.label} blinked {count} times and confirmed its flashlight off.'}

    async def _call(self, grant, payload, *, connected=lambda: True):
        device_id, cap, args = payload['device_id'], payload['cap'], payload['args']
        if not isinstance(device_id, str) or not isinstance(cap, str) or cap not in CAPABILITIES:
            return denied('UNSUPPORTED', 'Unsupported device action. Nothing was sent.')
        if device_id in grant.unknown_devices:
            return denied('UNKNOWN', 'A previous result for this device is unknown. Nothing was resent.')
        dev = self.registry.devices.get(device_id)
        if dev is None or dev.room_id != grant.room_id:
            return denied('OFFLINE', 'The requested device is unavailable. Ask the guest to choose; nothing was sent.')
        spec = dev.caps.get(cap)
        if spec is None or not Bus.valid_args(spec, args):
            return denied('INVALID', 'The requested capability or arguments are unsupported. Nothing was sent.')
        if not self.leases.allows(grant.lease, dev, cap):
            return denied()
        self.log.append('cmd', requested_sentence(grant.lease.display_name, dev, cap, args),
                        guest_id=grant.guest_id, generation=grant.generation, thread_id=grant.thread_id,
                        turn_id=grant.turn_id, device_id=device_id, cap=cap)
        dispatches = []
        def observed(req, _device):
            dispatches.append(req)
            if cap == 'say':
                grant.explicit_speech_attempted = True
        try:
            budget = self.speech_timeout if cap == 'say' else self.action_timeout
            remaining = min(budget, grant.deadline - asyncio.get_running_loop().time(),
                            grant.lease.expires_at - self.leases.clock())
            result = await self.bus.call(device_id, cap, args, timeout=max(.001, remaining),
                                         authorize=lambda current, capability, _args: self.permitted(grant) and connected()
                                         and self._program_conflict(device_id, grant) is None
                                         and device_id not in grant.unknown_devices
                                         and current is dev and self.leases.allows(grant.lease, current, capability),
                                         on_dispatch=observed)
        except (Exception, asyncio.CancelledError):
            # Even a canceled/failed client cannot safely infer that no bytes were sent.
            return ({**denied('UNKNOWN', 'The action outcome is unknown. Do not retry or substitute.'), 'status': 'unknown'}
                    if dispatches else {**denied('CANCELLED', 'Nothing was sent.'), 'status': 'unsent'})
        sentence = (confirmed_sentence(dev, cap, args, result.result) if result.ok
                    else failure_sentence(dev, cap, args, result))
        self.log.append('ok' if result.ok else 'err', sentence, guest_id=grant.guest_id,
                        generation=grant.generation, thread_id=grant.thread_id, turn_id=grant.turn_id,
                        device_id=device_id, cap=cap, req=result.req, ok=result.ok, code=result.code)
        # Bridge messages are untrusted and can contain machine details. Give
        # the model structured actual results plus the same measured-state copy.
        return ({'ok': True, 'result': result.result, 'message': sentence, 'status': 'confirmed'} if result.ok else
                {'ok': False, 'code': result.code, 'message': sentence,
                 'status': 'unknown' if result.code == 'UNKNOWN' else 'unsent' if not dispatches else 'unconfirmed'})

    async def close(self):
        self._closed = True
        self.revoke_all()
        # Python's Server.wait_closed can wait for accepted connections too.
        # Stop accepting, then settle their Bus tasks BEFORE waiting for it.
        if self._server is not None:
            self._server.close()
        tasks = tuple(self._clients)
        for task in tasks:
            task.cancel()
        try:
            async with asyncio.timeout(3):
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if self._server is not None:
                    await self._server.wait_closed()
        finally:
            for task in tuple(self._clients):
                task.cancel()
            if self._directory is not None:
                self._directory.cleanup()
