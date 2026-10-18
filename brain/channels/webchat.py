import asyncio
from contextlib import suppress
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from brain.core.guest_view import GuestPublisher

router = APIRouter()
PUBLISH_INTERVAL = 1.0


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
    publisher = GuestPublisher(core, guest_id, ws, interval=PUBLISH_INTERVAL)
    tasks = []
    try:
        # Initial metadata precedes conversation and does not activate the lease.
        await publisher.publish()

        async def receive():
            while True:
                frame = await ws.receive_json()
                if not isinstance(frame, dict) or frame.get('type') != 'user':
                    await publisher.send_batch([{'type': 'assistant', 'text': 'Please send a text request.'}])
                    continue
                frames = await core.agent.turn(guest_id, frame.get('text'))
                await publisher.send_batch(frames)
                if core.speech is not None:
                    # The real final text is already delivered. Audio is optional,
                    # once per native turn, with dispatch-time authority checks.
                    await core.speech.speak_reply(frames)

        tasks = [asyncio.create_task(receive()), asyncio.create_task(publisher.run())]
        # A send failure must also stop a receiver/model task waiting on this socket.
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, ValueError, asyncio.CancelledError):
        return
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            # ASGI may cancel the handler as soon as the browser disconnects.
            # Both workers are explicitly cancelled even in that teardown path.
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(WebSocketDisconnect, OSError, RuntimeError, asyncio.CancelledError):
            await ws.close(code=1001)
