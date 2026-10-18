import asyncio
import contextlib
import secrets
import time
from fastapi import WebSocketDisconnect
from brain.core.registry import DeviceAlreadyConnected

async def device_socket(ws, config, registry, bus, heartbeat=5.0, *, photos=None):
    supplied = ws.query_params.get("t", "")
    if not config.device_token or not secrets.compare_digest(supplied, config.device_token):
        await ws.close(code=1008)
        return
    await ws.accept()
    dev = None
    task = None
    async def pulse():
        try:
            await pulse_loop()
        except Exception:
            bus.disconnect(dev)
            with contextlib.suppress(Exception): await ws.close(code=1001)

    async def pulse_loop():
        while True:
            await asyncio.sleep(heartbeat)
            if time.monotonic() - dev.last_seen >= heartbeat * 2:
                bus.disconnect(dev)
                await ws.close(code=1001)
                return
            await ws.send_json({"type":"ping"})
    try:
        frame = await asyncio.wait_for(ws.receive_json(), 5)
        dev = registry.register(frame, ws)
        await ws.send_json({"type":"welcome", "server_time":time.time(), "room":registry.room.code})
        task = asyncio.create_task(pulse())
        while True:
            frame = await ws.receive_json()
            if not isinstance(frame, dict): raise ValueError("Invalid frame")
            if frame.get("type") == "pong": dev.last_seen = time.monotonic()
            elif frame.get("type") in ("ok", "err"): bus.receive(dev, frame)
            elif frame.get("type") == "photo.consent" and photos is not None:
                from brain.core.photos import PhotoError
                try:
                    result = photos.device_event(dev, frame)
                except PhotoError as error:
                    result = {"type": "photo.consent", "ok": False, "code": error.code, "message": error.message}
                await ws.send_json(result)
            else: raise ValueError("Unexpected frame")
    except DeviceAlreadyConnected:
        with contextlib.suppress(Exception):
            await ws.close(code=1013, reason="This device is already connected. Wait for its previous connection to close.")
    except (WebSocketDisconnect, ValueError, TimeoutError):
        with contextlib.suppress(Exception): await ws.close(code=1008)
    finally:
        if dev: bus.disconnect(dev)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception): await task
