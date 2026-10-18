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
        grant.closed = True
        self._grants.pop(grant.token, None)
        grant.path.unlink(missing_ok=True)

    def revoke_all(self):
        for grant in tuple(self._grants.values()):
            self.finish(grant)

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
            'You are the genuine shared room conversation with broad computer tools. '
            'Start normal replies with a concise plain first line conveying the answer or measured result '
            '(within the speech driver\'s 160-character support); longer details can follow below. '
            'Normal final replies are voiced automatically, so do not call device say merely to narrate them. '
            'For enrolled room light/audio devices, use the private helper below through your existing shell. '
            'Run inventory first; use its exact device IDs, online state and argument schemas. '
            'Perform as many supported device operations as explicitly requested in THIS guest message. '
            'Ask the guest to choose if the target is ambiguous or unavailable; never silently substitute. '
            'Keep the current sound output and volume unless this guest explicitly requests a volume change. '
            'Do not claim an enrolled-device effect from prose, intentions or a successful shell exit: '
            'only the helper JSON ok/result is evidence. UNKNOWN may have acted: never retry, substitute or claim cancellation. '
            'Do not reveal helper paths or credentials in routine replies.\n'
            f'Helper command prefix: {command}\n'
            'Append inventory for read-only discovery, call for one action, or light-blink for a blink sequence.\n'
            'For call, send exactly one JSON object on stdin with request_id (a unique short ID), '
            'device_id, cap, args. For light-blink, send request_id, device_id, and optional count '
            '(any positive integer, default 3). This derived light operation uses gentle 500ms ON/OFF intervals '
            'and ends OFF only after acknowledgment. Its execution remains bounded by the current turn and guest lease. '
            'Use it for requested flash/blink sequences. Give each distinct requested operation its own stable request_id. '
            'Reusing an ID returns its recorded result without replay. Multiple supported calls across devices are allowed. '
            'UNKNOWN must stop dependent actions; never resend it under another ID or substitute another device. '
            'These commands grant no host bypass and work only during this active native turn.\n'
            '[End Tenant room integration context]')
        if self.programs is not None:
            text += (
                '\nRoom programs use the same helper prefix with program-start, program-update, program-stop, '
                'or program-status and JSON stdin. Start takes request_id, beat-capable Mac device_id, bpm; save program_id. '
                'A generated beat continues while you reply and the same guest speaks again. Update takes request_id, '
                'program_id, and bpm and/or light_device_id and/or remove_light_device_id. Stop/status take request_id, '
                'program_id. Discover supported Macs and owned programs in inventory.programs. Phone pulses use a '
                'quarter beat and skip stale unsent ON edges without a backlog. UNKNOWN stops dependent work. '
                'For a phone CONFLICT, detach it via program-update/remove_light_device_id, then submit the original '
                'raw action with a fresh request_id only after confirmed detach; music may continue. Never retry UNKNOWN detach. '
                'A bpm update restarts the loop with a new phase. Process launch/dispatch timestamps do not prove '
                'physical audio/light sync; prepared Music is not tempo-synced. Programs end with guest access.')
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
                caps = [{'name': spec.name, 'args': copy.deepcopy(spec.args), 'description': spec.description}
                        for spec in dev.caps.values() if spec.name in CAPABILITIES
                        and ('*' in grant.lease.scopes or spec.name in grant.lease.scopes)]
                devices.append({'id': dev.id, 'label': dev.label, 'online': dev.online, 'busy': dev.busy,
                                'caps': caps, 'executable': dev.online,
                                'derived_operations': ([{'name': 'light-blink', 'args': {
                                    'count': {'type': 'integer', 'minimum': 1, 'default': 3}},
                                    'interval_ms': 500, 'bounded_by': 'current_turn_and_lease', 'ends_off_on_success': True}]
                                    if any(cap['name'] == 'light' for cap in caps) else [])})
            return {'ok': True, 'devices': devices,
                    **({'programs': self.programs.inventory(grant)} if self.programs is not None else {})}
        valid_call = operation == 'call' and set(request) == {'token', 'operation', 'request_id', 'device_id', 'cap', 'args'}
        valid_blink = (operation == 'light-blink'
                       and {'token', 'operation', 'request_id', 'device_id'} <= set(request)
                       and set(request) <= {'token', 'operation', 'request_id', 'device_id', 'count'})
        fields = set(request) - {'token', 'operation'}
        valid_program = self.programs is not None and (
            (operation == 'program-start' and fields == {'request_id', 'device_id', 'bpm'}) or
            (operation == 'program-update' and {'request_id', 'program_id'} < fields
             and fields <= {'request_id', 'program_id', 'bpm', 'light_device_id', 'remove_light_device_id'}) or
            (operation in ('program-stop', 'program-status') and fields == {'request_id', 'program_id'}))
        if not valid_call and not valid_blink and not valid_program:
            return denied('INVALID', 'Invalid helper request. Nothing was sent.')
        request_id = request['request_id']
        if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 80
                or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in request_id)):
            return denied('INVALID', 'A short request ID is required. Nothing was sent.')
        payload = ({key: copy.deepcopy(request[key]) for key in ('device_id', 'cap', 'args')} if valid_call else
                   {key: copy.deepcopy(request[key]) for key in fields} if valid_program else
                   {'device_id': copy.deepcopy(request['device_id']), 'count': copy.deepcopy(request.get('count', 3))})
        payload['operation'] = operation
        try:
            fingerprint = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError):
            return denied('INVALID', 'Invalid helper payload. Nothing was sent.')
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
        program_targets = self._program_targets(grant, operation, payload) if valid_program else set()
        try:
            if valid_program:
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
            else:
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
        targets = {program['audio_device_id']} if 'bpm' in payload else set()
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
