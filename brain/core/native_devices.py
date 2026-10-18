"""Turn-scoped local access to the existing device Bus, never host authority.

The native agent already has broad shell access. This private helper restores
enrolled light/audio controls; it is not OS isolation for that broader shell.
"""
from __future__ import annotations

import asyncio
import copy
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
    attempted: bool = False
    calls: dict = field(default_factory=dict, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def denied(code='PERMISSION', message='This turn has no current device authority. Nothing was sent.'):
    return {'ok': False, 'code': code, 'message': message}


class NativeDevices:
    def __init__(self, registry, bus, leases, log, current, *, action_timeout=5, read_timeout=2):
        self.registry, self.bus, self.leases, self.log = registry, bus, leases, log
        self.current = current
        self.action_timeout, self.read_timeout = action_timeout, read_timeout
        self._directory = None
        self._server = None
        self._grants = {}
        self._clients = set()
        self._closed = False

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
            json.dump({'socket': str(path.parent / 'bus.sock'), 'token': token}, stream)
        self._grants[token] = grant
        return grant

    def activate(self, grant, turn_id):
        if not grant.closed:
            grant.turn_id = turn_id

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
        return (not grant.closed and grant.turn_id is not None
                and self._grants.get(grant.token) is grant
                and self.registry.room.id == grant.room_id and self.registry.room.epoch == grant.epoch
                and self.leases.current(grant.guest_id) is grant.lease
                and self.current(grant))

    def context(self, grant):
        helper = Path(__file__).resolve().parents[2] / 'agent' / 'tenant_device.py'
        command = shlex.join([sys.executable, str(helper), '--context', str(grant.path)])
        return (
            '[Tenant room integration context]\n'
            'You are the genuine shared room conversation with broad computer tools. '
            'Start normal replies with a short plain sentence conveying the answer or measured result '
            '(at most 12 words and 100 characters); longer details can follow below. '
            'Normal final replies are voiced automatically, so do not call device say merely to narrate them. '
            'For enrolled room light/audio devices, use the private helper below through your existing shell. '
            'Run inventory first; use its exact device IDs, online state and argument schemas. '
            'Only perform one device action explicitly requested in THIS guest message. '
            'Ask the guest to choose if the target is ambiguous or unavailable; never silently substitute. '
            'Keep the current sound output and volume unless this guest explicitly requests a volume change. '
            'Do not claim an enrolled-device effect from prose, intentions or a successful shell exit: '
            'only the helper JSON ok/result is evidence. UNKNOWN may have acted: never retry, substitute or claim cancellation. '
            'Do not reveal helper paths or credentials in routine replies.\n'
            f'Inventory command: {command} inventory\n'
            f'Action command: {command} call\n'
            'For call, send exactly one JSON object on stdin with request_id (a unique short ID), '
            'device_id, cap, args. Reusing an ID returns its recorded result; a second action is refused. '
            'These commands grant no host bypass and work only during this active native turn.\n'
            '[End Tenant room integration context]')

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
                response = await self.dispatch(request)
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

    async def dispatch(self, request):
        if not isinstance(request, dict) or not isinstance(request.get('token'), str):
            return denied()
        grant = self._grants.get(request['token'])
        if grant is None or not self.permitted(grant):
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
                                'caps': caps, 'executable': dev.online})
            return {'ok': True, 'devices': devices}
        if operation != 'call' or set(request) != {'token', 'operation', 'request_id', 'device_id', 'cap', 'args'}:
            return denied('INVALID', 'Invalid helper request. Nothing was sent.')
        request_id = request['request_id']
        if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 80
                or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in request_id)):
            return denied('INVALID', 'A short request ID is required. Nothing was sent.')
        payload = {key: copy.deepcopy(request[key]) for key in ('device_id', 'cap', 'args')}
        async with grant.lock:
            if not self.permitted(grant):
                return denied()
            previous = grant.calls.get(request_id)
            if previous is not None:
                return copy.deepcopy(previous[1]) if previous[0] == payload else denied('INVALID', 'Request ID changed. Nothing was sent.')
            if grant.attempted:
                return denied('LIMIT', 'This turn already attempted one device action. Nothing else was sent.')
            grant.attempted = True  # Consume before awaits; failures/UNKNOWN never authorize another action.
            response = await self._call(grant, payload)
            grant.calls[request_id] = (payload, copy.deepcopy(response))
            return response

    async def _call(self, grant, payload):
        device_id, cap, args = payload['device_id'], payload['cap'], payload['args']
        if not isinstance(device_id, str) or not isinstance(cap, str) or cap not in CAPABILITIES:
            return denied('UNSUPPORTED', 'Unsupported device action. Nothing was sent.')
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
        try:
            result = await self.bus.call(device_id, cap, args, timeout=self.action_timeout,
                                         authorize=lambda current, capability, _args: self.permitted(grant)
                                         and current is dev and self.leases.allows(grant.lease, current, capability))
        except (Exception, asyncio.CancelledError):
            # Even a canceled/failed client cannot safely infer that no bytes were sent.
            return denied('UNKNOWN', 'The action outcome is unknown. Do not retry or substitute.')
        sentence = (confirmed_sentence(dev, cap, args, result.result) if result.ok
                    else failure_sentence(dev, cap, args, result))
        self.log.append('ok' if result.ok else 'err', sentence, guest_id=grant.guest_id,
                        generation=grant.generation, thread_id=grant.thread_id, turn_id=grant.turn_id,
                        device_id=device_id, cap=cap, req=result.req, ok=result.ok, code=result.code)
        # Bridge messages are untrusted and can contain machine details. Give
        # the model structured actual results plus the same measured-state copy.
        return ({'ok': True, 'result': result.result, 'message': sentence} if result.ok else
                {'ok': False, 'code': result.code, 'message': sentence})

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
