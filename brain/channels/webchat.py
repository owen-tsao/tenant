import asyncio
from contextlib import suppress
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from brain.core.guest_view import GuestPublisher

router = APIRouter()
PUBLISH_INTERVAL = 1.0
MAX_TURN_WORKERS = 8


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
    workers = set()
    settling = set()
    completed = asyncio.Queue()
    conversation = getattr(core.agent, 'agent_mode', None) == 'conversation'
    lease = core.leases.leases.get(guest_id)
    ended = False

    def cancel_ended_workers(*, exclude=None):
        nonlocal ended
        # Native work belongs to the exact lease that opened this socket. Never
        # carry queued text into a replacement lease or a recovered connection.
        # The legacy planner retains its truthful, already-dispatched ACK path.
        if conversation and (ended or core.leases.current(guest_id) is not lease or lease is None):
            ended = True
            for worker in workers:
                if worker is not exclude and worker not in settling and not worker.done() and not worker.cancelling():
                    worker.cancel()
        return ended

    async def respond(text):
        current = asyncio.current_task()
        if cancel_ended_workers(exclude=current):
            settling.add(current)
            frames = [{'type': 'assistant', 'text': core.leases.denial(guest_id)}]
        else:
            frames = await core.agent.turn(guest_id, text)
            if cancel_ended_workers(exclude=current):
                settling.add(current)
                if not is_leave(text):
                    frames = [{'type': 'assistant', 'text': core.leases.denial(guest_id)}]
        await publisher.send_batch(frames)
        if core.speech is not None:
            # Speech accepts only genuine ReplyFrames receipts; action-only
            # steering acknowledgments cannot trigger audio or a second final.
            core.speech.schedule_reply(frames)

    def is_leave(text):
        return isinstance(text, str) and text.strip().casefold() in ('leave', 'goodbye', 'done')

    try:
        # Initial metadata precedes conversation and does not activate the lease.
        await publisher.publish()

        async def receive():
            while True:
                try:
                    frame = await ws.receive_json()
                except ValueError:
                    return  # Malformed JSON closes this socket, not a model error.
                if not isinstance(frame, dict) or frame.get('type') != 'user':
                    await publisher.send_batch([{'type': 'assistant', 'text': 'Please send a text request.'}])
                    continue
                if cancel_ended_workers():
                    await publisher.send_batch([{'type': 'assistant', 'text': core.leases.denial(guest_id)}])
                    continue
                text = frame.get('text')
                # Reject overload rather than keeping an unbounded text queue.
                # One reserved worker lets native Leave revoke a saturated turn.
                limit = MAX_TURN_WORKERS + int(conversation and is_leave(text))
                if sum(not worker.done() for worker in workers) >= limit:
                    await publisher.send_batch([{'type': 'action', 'text':
                        'Too many pending requests. Wait for a response before sending more.'}])
                    continue
                worker = asyncio.create_task(respond(text))
                workers.add(worker)
                worker.add_done_callback(completed.put_nowait)

        tasks = [asyncio.create_task(receive()), asyncio.create_task(publisher.run())]
        for task in tasks:
            task.add_done_callback(completed.put_nowait)
        while True:
            try:
                task = await asyncio.wait_for(completed.get(), PUBLISH_INTERVAL)
            except TimeoutError:
                cancel_ended_workers()
                continue
            if task in workers:
                workers.remove(task)
                settling.discard(task)
                if not task.cancelled():
                    # Worker model/send failures reach the handler immediately.
                    task.result()
                cancel_ended_workers()
                continue
            task.result()
            break
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        tasks.extend(workers)
        for task in tasks:
            task.cancel()
        if tasks:
            # ASGI may cancel the handler as soon as the browser disconnects.
            # Every receiver, publisher and response worker is joined here.
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(WebSocketDisconnect, OSError, RuntimeError, asyncio.CancelledError):
            await ws.close(code=1001)
