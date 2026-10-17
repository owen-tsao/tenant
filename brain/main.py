from pathlib import Path
import asyncio
import os
import secrets
from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from brain.config import Config
from brain.state import Room
from brain.core.registry import Registry
from brain.core.bus import Bus
from brain.core.integration import install_core
from brain.core.persistence import RoomStateStore
from brain.core.planner import CodexPlanner
from brain.ws.devices import device_socket

WEB = Path(__file__).resolve().parent.parent / "web"

async def reset_cleanup(core):
    """Explicit host defaults: lights off and Music paused, with honest results."""
    # A just-restarted bridge has not yet re-advertised its effects/capabilities.
    # Its durable enrollment is enough to prevent a false clean-room claim.
    missing = set(core.registry.enrollments) - set(core.registry.devices)
    async def stop(dev, cap, args):
        result = await core.bus.call(dev.id, cap, args, timeout=4,
                                     authorize=lambda current, *_: current.room_id == core.registry.room.id)
        core.log.append('ok' if result.ok else 'err',
                        f'Reset: {dev.label}.{cap}: ' + ('confirmed' if result.ok else result.code)
                        + (f' [{result.req}]' if result.req else ''))
        return result.ok
    tasks = []
    for dev in core.registry.devices.values():
        if dev.room_id != core.registry.room.id:
            continue
        if 'light' in dev.caps:
            tasks.append(stop(dev, 'light', {'on': False}))
        if 'music.pause' in dev.caps:
            tasks.append(stop(dev, 'music.pause', {}))
    outcomes = await asyncio.gather(*tasks)
    return not missing and all(outcomes)


def create_app(config=None, *, planner=None, log_path=None, state_path=None):
    config = config or Config.from_env()
    app = FastAPI()
    registry = (RoomStateStore(state_path).load_registry(config.room_code)
                if state_path else Registry(Room(config.room_code, "Room " + config.room_code)))
    bus = Bus(registry)
    app.state.registry, app.state.bus, app.state.config = registry, bus, config
    core = install_core(app, planner, log_path=log_path, cleanup_hook=reset_cleanup)

    @app.websocket("/ws/device")
    async def devices(ws: WebSocket):
        await device_socket(ws, config, registry, bus)

    @app.post("/host/do")
    async def host_do(request: Request):
        supplied = request.headers.get("authorization", "")
        if not config.host_token or not secrets.compare_digest(supplied, "Bearer " + config.host_token):
            raise HTTPException(403, "Host authorization required")
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("device_id"), str) or not isinstance(body.get("cap"), str):
                raise ValueError()
            if body["cap"] not in {'light', 'volume', 'say', 'music.play', 'music.pause'}: raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "Expected device_id, supported cap, args")
        return await core.host_do(body)

    def page(name):
        path = WEB / name
        if not path.is_file():
            raise HTTPException(503, 'Guest interface is being connected. Please try again shortly.')
        return FileResponse(path, headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer"})

    @app.get('/j/{code}')
    async def join_page(code: str):
        return page('join.html')

    @app.get('/g/{guest_id}')
    async def guest_page(guest_id: str):
        return page('guest.html')

    @app.get('/display')
    async def display_page():
        return page('display.html')

    @app.get("/d/{device_id}")
    async def device_page(device_id: str):
        return FileResponse(WEB / "device.html", headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer"})

    @app.get("/health")
    async def health(): return {"ok":True}

    app.mount("/", StaticFiles(directory=WEB, check_dir=False), name="web")
    return app

app = create_app(planner=CodexPlanner(), log_path='log/events.jsonl',
                 state_path=os.getenv('TENANT_STATE_PATH'))
