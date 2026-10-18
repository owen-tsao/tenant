import asyncio
from contextlib import suppress
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket('/ws/display')
async def display_socket(ws: WebSocket):
    core = ws.app.state.core
    if not core.origin_allowed(ws.headers.get('origin')):
        await ws.close(code=1008)
        return
    await ws.accept()
    send_lock = asyncio.Lock()

    async def publish():
        previous = None
        while True:
            current = core.snapshot()
            if current != previous:
                async with send_lock:
                    await ws.send_json(current)
                previous = current
            await asyncio.sleep(.05)

    publisher = asyncio.create_task(publish())
    try:
        while True:
            frame = await ws.receive_json()
            if not isinstance(frame, dict):
                continue
            kind = frame.get('type', '')
            if not kind.startswith('host.'):
                continue
            # The token is never copied to logs or public state.
            token = frame.get('token', '')
            if not core.host_authorized('Bearer ' + token if isinstance(token, str) else ''):
                continue
            if kind == 'host.reset':
                await core.reset()
            elif kind == 'host.revoke' and isinstance(frame.get('guest_id'), str):
                core.revoke(frame['guest_id'])
            elif kind == 'host.do' and isinstance(frame.get('device_id'), str) and isinstance(frame.get('cap'), str):
                await core.host_do(frame)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        publisher.cancel()
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await publisher
