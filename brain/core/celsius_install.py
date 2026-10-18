"""Dormant host-only scene controls. Registration starts no workers or devices."""
import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, Request

from agent.room_session import RoomSessionError
from brain.core.celsius import CelsiusBridge


def lab_source(lab_root, session_id):
    modules = []
    for name in ('reader', 'control'):
        path = lab_root / (name + '.py')
        spec = importlib.util.spec_from_file_location('tenant_celsius_' + name, path)
        if spec is None or spec.loader is None:
            raise ValueError('Source interface unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    reader_module, control = modules
    state, folder = control.current(lab_root / 'state')
    if state.get('session_id') != session_id or state.get('running') is not True:
        raise ValueError('The explicit source session is not running')
    latest = json.loads((folder / 'latest.json').read_text())
    if (latest.get('session_id') != session_id or latest.get('command_protocol') != 2
            or not {'say', 'present_label', 'stop'} <= set(latest.get('commands', []))):
        raise ValueError('The native source must support session-bound lifecycle cleanup')
    return reader_module.SessionReader(lab_root / 'state', session_id), control


def status(bridge):
    if bridge is None:
        return {'armed': False, 'phase': 'idle', 'cleanup': 'no_owned_source'}
    return {'armed': bridge.active, 'phase': bridge.phase, 'cleanup': bridge.cleanup,
            'error': bridge.last_error, 'timings': bridge.timings[-20:]}


def install_celsius(app, core, *, lab_root=None, source_factory=lab_source, bridge_factory=CelsiusBridge):
    lab_root = Path(lab_root or Path(__file__).resolve().parents[3] / 'tenant-celsius-lab').resolve()
    core.celsius = None
    lock = asyncio.Lock()

    @app.get('/host/celsius')
    async def scene_status(request: Request):
        core.require_host(request)
        return status(core.celsius)

    @app.post('/host/celsius/arm')
    async def arm(request: Request):
        core.require_host(request)
        core.require_origin(request)
        if getattr(core.agent, 'agent_mode', None) != 'conversation':
            raise HTTPException(503, 'The existing room conversation is not enabled')
        try:
            body = await request.json()
            if (not isinstance(body, dict) or set(body) - {'guest_id', 'session_id', 'model', 'effects'}
                    or not all(isinstance(body.get(k), str) and 0 < len(body[k]) <= 128
                               for k in ('guest_id', 'session_id', 'model'))
                    or not isinstance(body.get('effects', []), list)
                    or not all(isinstance(v, str) for v in body.get('effects', []))
                    or not set(body.get('effects', [])) <= {'say', 'present_label'}):
                raise ValueError()
            UUID(body['session_id'])
        except (ValueError, TypeError):
            raise HTTPException(400, 'Expected a current lease, capture session, supported model and explicit effects') from None
        async with lock:
            if core.celsius is not None and core.celsius.active:
                raise HTTPException(409, 'A scene is already armed; no duplicate start')
            if core.leases.current(body['guest_id']) is None:
                raise HTTPException(403, 'Current room access is required')
            try:
                reader, control = source_factory(lab_root, body['session_id'])
                bridge = bridge_factory(core, reader, control, model=body['model'], effects=body.get('effects', []))
                await bridge.start(body['guest_id'])
            except (OSError, ValueError, RuntimeError, RoomSessionError):
                raise HTTPException(409, 'The source, controller or supported scene model is not ready; nothing was retried') from None
            core.celsius = bridge
            return status(bridge)

    @app.post('/host/celsius/stop')
    async def stop(request: Request):
        core.require_host(request)
        core.require_origin(request)
        async with lock:
            if core.celsius is not None:
                await core.celsius.close(reason='host_stop')
            return status(core.celsius)
