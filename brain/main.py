from pathlib import Path
import asyncio
from io import BytesIO
import os
import secrets
from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import qrcode
from qrcode.image.svg import SvgPathImage
from brain.config import Config
from brain.state import Room
from brain.core.registry import Registry
from brain.core.bus import Bus
from brain.core.copy import confirmed_sentence, failure_sentence
from brain.core.integration import install_core
from brain.core.persistence import RoomStateStore
from brain.core.planner import CodexPlanner
from brain.core.room_conversation import ConversationSettings
from brain.ws.devices import device_socket

WEB = Path(__file__).resolve().parent.parent / "web"

async def reset_cleanup(core):
    """Explicit host defaults: lights off and Music paused, with honest results."""
    # A just-restarted bridge has not yet re-advertised its effects/capabilities.
    # Its durable enrollment is enough to prevent a false clean-room claim.
    missing = set(core.registry.enrollments) - set(core.registry.devices)
    async def stop(dev, cap, args):
        original_connection = dev.ws
        tools = getattr(core.agent, 'device_tools', None)
        action_budget = getattr(tools, 'action_timeout', 4)
        speech_budget = getattr(getattr(core.agent, 'settings', None), 'cleanup_timeout', 0)
        # An accepted narration may already hold the Mac queue. Light OFF has
        # its independent action budget and is dispatched in parallel below.
        budget = action_budget + (speech_budget if cap == 'music.pause' else 0)
        result = await core.bus.call(dev.id, cap, args, timeout=budget,
                                     authorize=lambda current, *_: current.room_id == core.registry.room.id)
        payload = result.result if isinstance(result.result, dict) else {}
        confirmed = result.ok and (
            (cap == 'light' and payload.get('on') is False)
            or (cap == 'music.pause' and payload.get('state') in ('paused', 'stopped')))
        sentence = (confirmed_sentence(dev, cap, args, payload) if confirmed
                    else f'{dev.label} did not confirm the requested reset state.' if result.ok
                    else failure_sentence(dev, cap, args, result))
        core.log.append('ok' if confirmed else 'err', sentence,
                        actor='host.reset', device_id=dev.id, cap=cap,
                        req=result.req, ok=confirmed, ack_ok=result.ok,
                        code='UNCONFIRMED_STATE' if result.ok and not confirmed else result.code)
        programs = getattr(core.agent, 'programs', None)
        if confirmed and cap == 'light' and programs is not None:
            programs.confirm_host_off(dev, original_connection, result)
        return confirmed
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


def create_app(config=None, *, planner=None, log_path=None, state_path=None, conversation=None, photon_factory=None):
    config = config or Config.from_env()
    app = FastAPI()
    registry = (RoomStateStore(state_path).load_registry(config.room_code)
                if state_path else Registry(Room(config.room_code, "Room " + config.room_code)))
    bus = Bus(registry)
    app.state.registry, app.state.bus, app.state.config = registry, bus, config
    core = install_core(app, planner, log_path=log_path, cleanup_hook=reset_cleanup, conversation=conversation, photon_factory=photon_factory)

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

    @app.get('/')
    @app.get('/setup')
    async def host_setup():
        return page('setup.html')

    # Owen's pages also work as root-level static files. Their relative asset
    # URLs need these exact aliases when served at the agreed /j and /g routes.
    @app.get('/j/shared.js')
    @app.get('/g/shared.js')
    async def shared_script():
        return page('shared.js')

    @app.get('/j/tenant.css')
    @app.get('/g/tenant.css')
    async def shared_style():
        return page('tenant.css')

    @app.get('/qr.svg')
    async def guest_qr():
        url = config.public_url.rstrip('/') + '/j/' + registry.room.code
        rendered = qrcode.make(url, image_factory=SvgPathImage,
                               error_correction=qrcode.constants.ERROR_CORRECT_M,
                               box_size=8, border=4)
        stream = BytesIO()
        rendered.save(stream)
        return Response(stream.getvalue(), media_type='image/svg+xml',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

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

def runtime_conversation_settings():
    mode = os.getenv('TENANT_AGENT_MODE', 'planner')
    if mode == 'planner':
        return None
    if mode != 'conversation':
        raise ValueError('TENANT_AGENT_MODE must be planner or conversation')
    return ConversationSettings(
        thread_id=os.getenv('TENANT_ROOM_THREAD_ID', ''),
        anchor_turn_ids=(os.getenv('TENANT_ROOM_ANCHOR_TURN_ID', ''),),
        socket_path=os.getenv('TENANT_APP_SERVER_SOCKET') or None)


def runtime_photon_factory(conversation):
    # Keys alone never enable a second channel or network work during imports.
    if os.getenv('TENANT_PHOTON_ENABLED') != '1':
        return None
    if conversation is None:
        raise ValueError('Photon requires TENANT_AGENT_MODE=conversation')
    from brain.channels.photon import PhotonChannel, PhotonClient
    project_id, api_key = os.getenv('PHOTON_PROJECT_ID', ''), os.getenv('PHOTON_API_KEY', '')
    store_path = os.getenv('TENANT_PHOTON_STATE_PATH', '.venv/tenant-runtime/photon.sqlite3')
    return lambda core: PhotonChannel(core, PhotonClient(project_id, api_key), store_path)


_runtime_conversation = runtime_conversation_settings()
app = create_app(planner=None if _runtime_conversation else CodexPlanner(), log_path='log/events.jsonl',
                 state_path=os.getenv('TENANT_STATE_PATH'), conversation=_runtime_conversation,
                 photon_factory=runtime_photon_factory(_runtime_conversation))
