"""Private, advisory guest metadata; never activates or renews authority."""
import asyncio
import math
from starlette.websockets import WebSocketDisconnect

from brain.core.copy import device_label
from brain.core.planner import ALLOWED_CAPS


def ended_frame(reason):
    return {'type': 'lease', 'state': 'released', 'reason': reason,
            'expires_in': 0, 'access_expires_in': 0, 'controls': []}


def lease_frame(core, guest_id):
    """Inspect only this guest. Execution still rechecks the authoritative lease."""
    try:
        current = core.leases.current(guest_id)  # No activation; expires at the real deadline.
    except Exception:
        return ended_frame('unavailable')
    if current is None:
        lease = core.leases.leases.get(guest_id)
        if lease and lease.state == 'expired':
            return ended_frame('expired')
        if not lease or lease.state == 'released':
            return ended_frame('ended')
        return ended_frame('unavailable')
    now = core.leases.clock()
    effective_deadline = (min(current.expires_at, current.joining_until)
                          if current.state == 'joining' else current.expires_at)
    controls = []
    for device in core.registry.devices.values():
        if device.room_id != current.room_id or not device.online or core.agent.label_is_ambiguous(device):
            continue
        caps = sorted(cap for cap in device.caps if cap in ALLOWED_CAPS
                      and ('*' in current.scopes or cap in current.scopes))
        if caps:
            controls.append({'label': device_label(device), 'caps': caps})
    # Stable ordering avoids updates solely because a device reconnected.
    controls.sort(key=lambda item: item['label'].casefold())
    return {'type': 'lease', 'state': current.state,
            'expires_in': max(0, math.ceil(effective_deadline - now)),
            'access_expires_in': max(0, math.ceil(current.expires_at - now)),
            'controls': controls}


class GuestPublisher:
    """Serialize metadata and complete conversation batches on one socket."""
    def __init__(self, core, guest_id, socket, *, interval=1.0):
        self.core, self.guest_id, self.socket = core, guest_id, socket
        self.interval = interval
        self.send_lock = asyncio.Lock()
        self.previous = None

    async def _send(self, frame):
        try:
            await self.socket.send_json(frame)
        except (OSError, RuntimeError):
            # Only normalize transport-close failures at the send boundary;
            # application/model exceptions are not swallowed by this policy.
            raise WebSocketDisconnect(code=1006) from None

    async def publish(self):
        async with self.send_lock:
            frame = lease_frame(self.core, self.guest_id)
            if frame != self.previous:
                await self._send(frame)
                self.previous = frame

    async def send_batch(self, frames):
        async with self.send_lock:
            for frame in frames:
                await self._send(frame)

    async def run(self):
        while True:
            await asyncio.sleep(self.interval)
            await self.publish()
