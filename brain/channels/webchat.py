from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket('/ws/guest')
async def guest_socket(ws: WebSocket):
    core = ws.app.state.core
    guest_id = ws.query_params.get('guest_id')
    if not core.origin_allowed(ws.headers.get('origin')):
        await ws.close(code=1008)
        return
    # Explicit token is the agreed UI contract; a cookie alone cannot open chat.
    if not core.authentic_token(guest_id, ws.query_params.get('token')):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            frame = await ws.receive_json()
            if not isinstance(frame, dict) or frame.get('type') != 'user':
                await ws.send_json({'type': 'assistant', 'text': 'Please send a text request.'})
                continue
            for result in await core.agent.turn(guest_id, frame.get('text')):
                await ws.send_json(result)
    except (WebSocketDisconnect, ValueError):
        return
