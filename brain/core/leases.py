"""In-memory, immediate authority transitions; effect cleanup is a separate concern."""
import secrets
import time
import uuid
from brain.state import Lease, Session


class Leases:
    def __init__(self, room, *, clock=time.time, active_ttl=600, joining_ttl=120, on_change=None, healthy=lambda: True):
        self.room = room
        self.on_change = on_change
        self.healthy = healthy
        self.clock = clock
        self.active_ttl = active_ttl
        self.joining_ttl = joining_ttl
        self.leases: dict[str, Lease] = {}
        self.sessions: dict[str, Session] = {}

    def create(self, *, scopes=None, channel='webchat'):
        now = self.clock()
        guest_id = str(uuid.uuid4())
        lease = Lease(guest_id, self.room.code, 'joining', set(scopes if scopes is not None else {'*'}),
                      now + self.active_ttl, channel, None, f'Guest {len(self.leases) + 1}',
                      room_id=self.room.id, joining_until=now + self.joining_ttl,
                      access_total=self.active_ttl, joining_total=min(self.active_ttl, self.joining_ttl))
        self.leases[guest_id] = lease
        self.sessions[guest_id] = Session(guest_id, last_active=now)
        return lease

    def current(self, guest_id, *, activate=False):
        lease = self.leases.get(guest_id)
        if not self.healthy() or not lease or lease.state not in ('joining', 'active') or lease.room_id != self.room.id:
            return None
        now = self.clock()
        if now >= lease.expires_at or (lease.state == 'joining' and now >= lease.joining_until):
            self.revoke(guest_id, expired=True)
            return None
        if activate and lease.state == 'joining':
            lease.state = 'active'
        return lease

    def allows(self, lease, device, cap):
        # Check the exact live object, not a stale scope/lease snapshot.
        return (self.current(lease.guest_id) is lease and lease.state == 'active'
                and device.room_id == self.room.id and (cap in lease.scopes or '*' in lease.scopes))

    def record_public(self, lease, role, text, *, publication=None):
        """Append only live, explicitly selected public text; never inspect history."""
        if (self.current(lease.guest_id) is not lease or role not in ('guest', 'room')
                or not isinstance(text, str) or not text.strip()):
            return
        session = self.sessions[lease.guest_id]
        if publication is not None:
            if publication in session.published_turns:
                return
            session.published_turns.add(publication)
        session.transcript.append({'role': role, 'text': text, 't': self.clock()})
        del session.transcript[:-10]

    def revoke(self, guest_id, *, expired=False, persist=True):
        lease = self.leases.get(guest_id)
        if lease and lease.state in ('joining', 'active'):
            lease.state = 'expired' if expired else 'released'
            session = self.sessions.get(guest_id)
            if session:
                session.transcript.clear()
                session.published_turns.clear()
            self.room.epoch += 1
            if persist and self.on_change:
                self.on_change()
            return True
        return False

    def sweep(self):
        for guest_id in tuple(self.leases):
            self.current(guest_id)

    def reset(self):
        # Revoke first. Existing devices retain their stable room identity.
        revoked = sum(self.revoke(guest_id, persist=False) for guest_id in tuple(self.leases))
        self.room.epoch += 1
        old = self.room.code
        while self.room.code == old:
            self.room.code = secrets.token_hex(2).upper()
        if self.room.label == 'Room ' + old:
            self.room.label = 'Room ' + self.room.code
        if self.on_change:
            self.on_change()
        return revoked

    def denial(self, guest_id):
        lease = self.leases.get(guest_id)
        code = lease.room_code if lease else self.room.code
        return f"You're no longer in Room {code}. Scan the room code to join again."
