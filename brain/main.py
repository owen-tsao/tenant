from pathlib import Path
import secrets
from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from brain.config import Config
from brain.state import Room
from brain.core.registry import Registry
from brain.core.bus import Bus
from brain.ws.devices import device_socket

WEB = Path(__file__).resolve().parent.parent / "web"

def create_app(config=None):
    config = config or Config.from_env()
    app = FastAPI()
    registry = Registry(Room(config.room_code, "Room " + config.room_code))
    bus = Bus(registry)
    app.state.registry, app.state.bus, app.state.config = registry, bus, config

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
            if body["cap"] != "light": raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "Expected device_id, cap=light, args")
        result = await bus.call(body["device_id"], body["cap"], body.get("args"),
                                authorize=lambda dev, cap, args: dev.room_code == registry.room.code)
        return result.as_dict()

    @app.get("/d/{device_id}")
    async def device_page(device_id: str):
        return FileResponse(WEB / "device.html", headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer"})

    @app.get("/health")
    async def health(): return {"ok":True}

    app.mount("/", StaticFiles(directory=WEB, check_dir=False), name="web")
    return app

app = create_app()
