"""Install the small guest/access core before the app's static mount."""
import asyncio
import hashlib
import secrets
import time
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit
from fastapi import HTTPException
from brain.core.agent import Agent
from brain.core.leases import Leases
from brain.core.log import EventLog


class Core:
    def __init__(self, app, planner, *, clock=time.time, log_path=None, cleanup_hook=None):
        self.registry = app.state.registry
        self.bus = app.state.bus
        self.config = app.state.config
        self.leases = Leases(self.registry.room, clock=clock, on_change=self.registry.persist,
                             healthy=lambda: self.registry.persistence_healthy)
        self.log = EventLog(log_path, clock=clock)
        self.agent = Agent(self.registry, self.bus, self.leases, planner, self.log)
        self.credentials = {}
        self.cleanup_hook = cleanup_hook

    @staticmethod
    def cookie_name(guest_id):
        return 'tenant_guest_' + guest_id

    def issue_credential(self, guest_id):
        secret = secrets.token_urlsafe(32)
        self.credentials[guest_id] = hashlib.sha256(secret.encode()).digest()
        return secret

    def authentic_token(self, guest_id, supplied):
        if not isinstance(guest_id, str) or guest_id not in self.credentials:
            return False
        return bool(isinstance(supplied, str) and 0 < len(supplied) <= 128
                    and secrets.compare_digest(hashlib.sha256(supplied.encode()).digest(), self.credentials[guest_id]))

    def authentic_guest(self, guest_id, cookies):
        if not isinstance(guest_id, str):
            return False
        return self.authentic_token(guest_id, cookies.get(self.cookie_name(guest_id), ''))

    def origin_allowed(self, origin):
        if not origin:
            return False
        try:
            actual, expected = urlsplit(origin), urlsplit(self.config.public_url)
            return (actual.scheme in ('http', 'https') and not actual.username and not actual.password
                    and not actual.path and not actual.query and not actual.fragment
                    and actual.scheme == expected.scheme and actual.netloc.casefold() == expected.netloc.casefold())
        except (ValueError, AttributeError):
            return False

    def require_origin(self, request):
        if not self.origin_allowed(request.headers.get('origin')):
            raise HTTPException(403, 'Approved same-origin request required')

    def host_authorized(self, value):
        return bool(self.config.host_token and isinstance(value, str)
                    and secrets.compare_digest(value, 'Bearer ' + self.config.host_token))

    def require_host(self, request):
        if not self.host_authorized(request.headers.get('authorization', '')):
            raise HTTPException(403, 'Host authorization required')

    def sweep(self):
        self.leases.sweep()
        # Credentials/tombstones last through the original cookie lifetime only.
        # Old sessions cannot regain authority, and an overnight demo stays bounded.
        now = self.leases.clock()
        for guest_id, lease in list(self.leases.leases.items()):
            if lease.state in ('released', 'expired') and now >= lease.expires_at + 120:
                self.leases.leases.pop(guest_id, None)
                self.leases.sessions.pop(guest_id, None)
                self.credentials.pop(guest_id, None)
                self.agent.pending.pop(guest_id, None)
                lock = self.agent.locks.get(guest_id)
                if lock and not lock.locked():
                    self.agent.locks.pop(guest_id, None)

    def snapshot(self):
        self.sweep()
        room = self.registry.room
        return {'type': 'state',
                'room': {'code': room.code, 'label': room.label,
                         'join_url': self.config.public_url.rstrip('/') + '/j/' + room.code},
                'devices': [{'id': d.id, 'label': d.label, 'caps': list(d.caps), 'online': d.online, 'busy': d.busy}
                            for d in self.registry.devices.values() if d.room_id == room.id],
                'guests': [{'guest_id': lease.guest_id, 'display_name': lease.display_name,
                            'channel': lease.channel,
                            'expires_in': max(0, int(min(lease.expires_at, lease.joining_until)
                                                     - self.leases.clock())) if lease.state == 'joining'
                                           else max(0, int(lease.expires_at - self.leases.clock())),
                            'scopes': sorted(lease.scopes)}
                           for lease in self.leases.leases.values() if lease.state in ('joining', 'active')],
                'log': list(self.log.rows)}

    async def host_do(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('device_id'), str) or not isinstance(body.get('cap'), str):
            raise HTTPException(400, 'Expected device_id, cap, args')
        result = await self.bus.call(body['device_id'], body['cap'], body.get('args'),
                                     authorize=lambda dev, cap, args: dev.room_id == self.registry.room.id)
        req = getattr(result, 'req', None)
        self.log.append('ok' if result.ok else 'err', f'Host: {body["device_id"]}.{body["cap"]}: {"confirmed" if result.ok else result.code}' + (f' [{req}]' if req else ''))
        return result.as_dict()

    def revoke(self, guest_id):
        revoked = self.leases.revoke(guest_id)
        self.agent.pending.pop(guest_id, None)
        if revoked:
            self.log.append('guest.leave', 'Host revoked guest access; existing effects preserved')
        return revoked

    async def reset(self):
        # No await before revocation/invitation rotation. Do not cancel an already sent physical command.
        revoked = self.leases.reset()
        self.agent.pending.clear()
        self.log.clear()
        self.log.append('guest.leave', 'Host reset revoked access and rotated the invitation')
        cleanup = 'not_configured'
        if self.cleanup_hook:
            try:
                async with asyncio.timeout(5):
                    outcome = await self.cleanup_hook(self)
                # Cleanup must explicitly attest its confirmed outcome.
                cleanup = 'confirmed' if outcome is True else 'unconfirmed'
            except (Exception, TimeoutError):
                cleanup = 'unconfirmed'
            self.log.append('ok' if cleanup == 'confirmed' else 'err', 'Reset cleanup: ' + cleanup)
        return {'ok': self.registry.persistence_healthy, 'room_code': self.registry.room.code,
                'revoked': revoked, 'cleanup': cleanup,
                **({} if self.registry.persistence_healthy else {'error': 'Room state could not be saved; guest control is disabled'})}


def install_core(app, planner, *, clock=time.time, log_path=None, cleanup_hook=None):
    """Call after registry/bus/config state setup, before mounting static files.

    The caller owns an existing /host/do route; delegate its authenticated body
    to ``await app.state.core.host_do(body)`` to avoid registering two routes.
    """
    from brain.api.join import router as join_router
    from brain.api.host import router as host_router
    from brain.channels.webchat import router as guest_router
    from brain.ws.display import router as display_router
    core = Core(app, planner, clock=clock, log_path=log_path, cleanup_hook=cleanup_hook)
    app.state.core = core
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application) as state:
            async def reap():
                while True:
                    await asyncio.sleep(5)
                    core.sweep()
            task = asyncio.create_task(reap())
            try:
                yield state
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan
    for router in (join_router, host_router, guest_router, display_router):
        app.include_router(router)
    return core
