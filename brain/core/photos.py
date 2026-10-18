"""Bounded, in-memory one-still service. No deployment, discovery or device effects on import.

The caller supplies current controller authority; all source effects use the existing Bus.
Viewer credentials and image bytes never enter safe status or public room projections.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import math
import secrets
from typing import Callable

CAPTURE_ARGS = {name: {'type': 'string'} for name in ('capture_id', 'upload_url', 'upload_token')}
MAX_BYTES = 5 * 1024 * 1024
TERMINAL = frozenset({'failed', 'unknown', 'cancelled', 'displayed'})
RESULT_CODES = frozenset({'PERMISSION', 'UNSUPPORTED', 'BUSY', 'FAILED', 'STALE', 'UNKNOWN',
                          'OFFLINE', 'INVALID', 'TIMEOUT', 'CONFLICT'})


class PhotoError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _identifier(value):
    return (isinstance(value, str) and 1 <= len(value) <= 128
            and all(c.isascii() and (c.isalnum() or c in '_-.') for c in value))


def _digest(value):
    return hashlib.sha256(value.encode()).digest()


@dataclass
class Consent:
    device: object
    socket: object
    enabled: bool
    ready: bool
    revision: int


@dataclass
class Viewer:
    id: str
    digest: bytes = field(repr=False)
    revision: int = 0
    seen: float = 0


@dataclass
class Image:
    id: str
    version: int
    data: bytes = field(repr=False)
    captured_at: float = 0
    source_label: str = ''
    viewer_id: str = ''

    def public(self):
        return {'photo_id': self.id, 'version': self.version,
                'image_url': '/photos/images/' + self.id,
                'captured_at': self.captured_at, 'source_label': self.source_label}


@dataclass
class Capture:
    request_id: str
    id: str
    lease: object = field(repr=False)
    generation: int
    room: object = field(repr=False)
    epoch: int
    source: object = field(repr=False)
    socket: object = field(repr=False)
    consent_revision: int
    role_revision: int
    viewer_revision: int
    viewer_id: str
    deadline: float
    ticket_digest: bytes = field(repr=False)
    retain_until: float
    binding_guard: Callable = field(repr=False)
    state: str = 'pending'
    code: str | None = None
    message: str = 'Waiting for the phone.'
    sent: bool = False
    captured: bool = False
    stored: bool = False
    displayed: bool = False
    ticket_used: bool = False
    uploading: bool = False
    upload_digest: bytes | None = field(default=None, repr=False)
    image: Image | None = field(default=None, repr=False)

    def status(self):
        result = {'ok': self.state not in {'failed', 'unknown', 'cancelled'},
                  'request_id': self.request_id, 'capture_id': self.id,
                  'state': self.state, 'captured': self.captured, 'stored': self.stored,
                  'displayed': self.displayed, 'sent': self.sent, 'message': self.message}
        if self.code:
            result['code'] = self.code
        return result


class PhotoService:
    def __init__(self, registry, bus, leases, *, authority: Callable,
                 clock=None, capture_timeout=30.0, viewer_ttl=15.0, capacity=256,
                 source_allowed: Callable = lambda device: True, normalizer=None):
        if not callable(authority) or not callable(source_allowed):
            raise ValueError('Explicit current authority and source policy are required')
        if (not math.isfinite(capture_timeout) or not 0 < capture_timeout <= 30
                or not math.isfinite(viewer_ttl) or not 0 < viewer_ttl <= 60
                or type(capacity) is not int or not 1 <= capacity <= 1024):
            raise ValueError('Invalid photo resource limits')
        self.registry, self.bus, self.leases = registry, bus, leases
        self.authority, self.source_allowed = authority, source_allowed
        self.clock = clock or leases.clock
        self.capture_timeout, self.viewer_ttl, self.capacity = capture_timeout, viewer_ttl, capacity
        self.normalizer = normalizer
        self.room = registry.room
        self.enabled = False
        self.source_id = self.viewer_id = None
        self.role_revision = 0
        self.viewer = None
        self.consents = {}
        self.records = {}
        self.by_capture = {}
        self.pending = None
        self.latest = None
        self.version = 0
        self.closed = False

    def configure(self, source_device_id, viewer_id, *, enabled=True):
        if not _identifier(source_device_id) or not _identifier(viewer_id) or type(enabled) is not bool:
            raise PhotoError(400, 'INVALID', 'Expected source_device_id, viewer_id and enabled.')
        source = self.registry.devices.get(source_device_id)
        if source is None or source.room_id != self.registry.room.id:
            raise PhotoError(404, 'NOT_FOUND', 'The source is not enrolled in this room.')
        self.sweep()
        changed = (source_device_id, viewer_id, enabled) != (self.source_id, self.viewer_id, self.enabled)
        if changed:
            self._cancel_pending('Photo roles or host allowance changed.')
            self.role_revision += 1
            self.source_id, self.viewer_id, self.enabled = source_device_id, viewer_id, enabled
        return {'ok': True, 'source_device_id': self.source_id, 'viewer_id': self.viewer_id,
                'enabled': self.enabled}

    def enroll_viewer(self, viewer_id):
        self.sweep()
        if not _identifier(viewer_id) or viewer_id != self.viewer_id:
            raise PhotoError(409, 'TARGET', 'The viewer is not the host-selected photo viewer.')
        self._cancel_pending('The authenticated viewer connection changed.')
        token = secrets.token_urlsafe(32)
        revision = (self.viewer.revision + 1) if self.viewer else 1
        self.viewer = Viewer(viewer_id, _digest(token), revision, self.clock())
        return token

    def _viewer(self, token, *, touch=False):
        viewer = self.viewer
        if (self.closed or viewer is None or viewer.id != self.viewer_id
                or not isinstance(token, str) or not 1 <= len(token) <= 128
                or not secrets.compare_digest(_digest(token), viewer.digest)):
            raise PhotoError(403, 'PERMISSION', 'Selected viewer authorization required.')
        if touch:
            viewer.seen = self.clock()
        return viewer

    def device_event(self, dev, frame):
        """Called ONLY with the actual authenticated device from its existing WS loop."""
        if (self.closed or not isinstance(frame, dict)
                or set(frame) != {'type', 'enabled', 'ready'} or frame.get('type') != 'photo.consent'
                or type(frame.get('enabled')) is not bool or type(frame.get('ready')) is not bool
                or (frame['ready'] and not frame['enabled'])):
            raise PhotoError(400, 'INVALID', 'Expected explicit photo consent and camera readiness.')
        if (self.registry.devices.get(dev.id) is not dev or not dev.online
                or dev.room_id != self.registry.room.id):
            raise PhotoError(403, 'PERMISSION', 'Consent must come from the current enrolled connection.')
        old = self.consents.get(dev.id)
        same = (old is not None and old.device is dev and old.socket is dev.ws
                and (old.enabled, old.ready) == (frame['enabled'], frame['ready']))
        if not same:
            revision = old.revision + 1 if old else 1
            self.consents[dev.id] = Consent(dev, dev.ws, frame['enabled'], frame['ready'], revision)
            if self.pending and self.pending.source.id == dev.id:
                self._cancel_pending('Camera consent or readiness changed.')
        consent = self.consents[dev.id]
        return {'type': 'photo.consent', 'ok': True, 'revision': consent.revision,
                'enabled': consent.enabled, 'ready': consent.ready}

    def _source_ready(self, dev):
        if (dev is None or self.registry.devices.get(dev.id) is not dev or not dev.online
                or dev.room_id != self.registry.room.id or dev.id != self.source_id):
            return False
        spec = dev.caps.get('camera.capture')
        consent = self.consents.get(dev.id)
        metadata = getattr(self.registry, 'metadata', None)
        # Metadata's generic camera gate is intentionally closed for raw calls.
        # This service adds its own consent/lease/viewer gate, while retaining
        # the metadata owner's exact live binding and host-allowance checks.
        if metadata is not None and (metadata.binding(dev.id) is not dev
                                     or not metadata.value(dev.id, 'allowed', True)):
            return False
        return bool(spec and spec.args == CAPTURE_ARGS and consent and consent.device is dev
                    and consent.socket is dev.ws and consent.enabled and consent.ready
                    and self.source_allowed(dev))

    def _authorized(self, lease, generation, source):
        return bool(not self.closed and self.enabled and source and self._source_ready(source)
                    and self.leases.current(lease.guest_id) is lease
                    and self.leases.allows(lease, source, 'camera.capture')
                    and ('*' in lease.scopes or 'photo.show' in lease.scopes)
                    and self.authority(lease, generation))

    def camera_ready(self, dev):
        """Metadata readiness hook only; dispatch still requires full guest policy.

        No recursion through metadata.available(): that method calls this hook.
        A pending capture must retain readiness while it waits on the Bus.
        """
        return bool(not self.closed and self.enabled and self._source_ready(dev)
                    and self.viewer and self.viewer.id == self.viewer_id
                    and 0 <= self.clock() - self.viewer.seen < self.viewer_ttl)

    def _valid(self, rec):
        return bool(self.pending is rec and rec.state not in TERMINAL
                    and self.registry.room is rec.room and self.registry.room.epoch == rec.epoch
                    and self.clock() < rec.deadline
                    and self._authorized(rec.lease, rec.generation, rec.source)
                    and rec.socket is rec.source.ws
                    and self.consents[rec.source.id].revision == rec.consent_revision
                    and self.role_revision == rec.role_revision
                    and rec.binding_guard()
                    and self.viewer is not None and self.viewer.id == rec.viewer_id == self.viewer_id
                    and self.viewer.revision == rec.viewer_revision
                    and 0 <= self.clock() - self.viewer.seen < self.viewer_ttl)

    def _cancel_pending(self, message, *, code='STALE'):
        rec = self.pending
        if rec is not None:
            rec.state, rec.code, rec.message = 'cancelled', code, message
            rec.image = None
            self.pending = None
            self.version += 1

    def sweep(self):
        if self.registry.room is not self.room:
            self.reset()
            self.room = self.registry.room
            self.consents.clear()
        if self.pending is not None and not self._valid(self.pending):
            self._cancel_pending('Photo access, connection or readiness ended.')
        now = self.clock()
        for key, rec in list(self.records.items()):
            if rec is not self.pending and now >= rec.retain_until:
                self.records.pop(key, None)
                self.by_capture.pop(rec.id, None)
        for key, consent in list(self.consents.items()):
            if self.registry.devices.get(key) is not consent.device or not consent.device.online:
                self.consents.pop(key, None)

    def invalidate_guest(self, guest_id):
        if self.pending is not None and self.pending.lease.guest_id == guest_id:
            self._cancel_pending('The originating guest no longer has photo authority.')

    def reset(self):
        """Explicit host reset hook: run synchronously after lease reset, before any await."""
        self._cancel_pending('The host reset the room.')
        self.latest = None
        self.version += 1
        for rec in self.records.values():
            rec.image = None
        # Keep request tombstones: reset must not replay old capture IDs.

    def close(self):
        self.reset()
        self.closed = True
        self.viewer = None
        self.consents.clear()

    def inventory(self, lease, *, generation=0):
        self.sweep()
        source = self.registry.devices.get(self.source_id)
        ready = bool(lease and self._authorized(lease, generation, source)
                     and self.viewer and self.viewer.id == self.viewer_id
                     and 0 <= self.clock() - self.viewer.seen < self.viewer_ttl
                     and self.pending is None)
        return {'ready': ready, 'source_device_id': self.source_id if ready else None,
                'source_label': source.label if ready else None,
                'message': 'Room photo capture is ready.' if ready else 'Room photo capture is unavailable.'}

    def status(self, lease, request_id):
        self.sweep()
        rec = self.records.get((lease.guest_id, request_id)) if lease is not None else None
        if rec is None or rec.lease is not lease:
            raise PhotoError(404, 'NOT_FOUND', 'Photo request not found.')
        return rec.status()

    async def capture(self, lease, request_id, source_device_id, *, generation=0,
                      dispatch_allowed=lambda: True):
        if not _identifier(request_id) or not _identifier(source_device_id) or type(generation) is not int:
            raise PhotoError(400, 'INVALID', 'Expected bounded request and source identifiers.')
        if lease is None:
            raise PhotoError(403, 'PERMISSION', 'Current guest photo authority required.')
        if not callable(dispatch_allowed):
            raise PhotoError(400, 'INVALID', 'A dispatch authority callback is required.')
        self.sweep()
        key = (lease.guest_id, request_id)
        previous = self.records.get(key)
        if previous is not None:
            if (previous.lease is not lease or previous.source.id != source_device_id
                    or previous.generation != generation):
                raise PhotoError(409, 'CONFLICT', 'That request ID is already bound to another photo request.')
            return previous.status()
        source = self.registry.devices.get(source_device_id)
        if not self._authorized(lease, generation, source):
            raise PhotoError(403, 'PERMISSION', 'Current photo permission, consent and source readiness are required.')
        if (not self.viewer or self.viewer.id != self.viewer_id
                or not 0 <= self.clock() - self.viewer.seen < self.viewer_ttl):
            raise PhotoError(409, 'VIEWER_OFFLINE', 'The selected Mac viewer is not ready.')
        if self.pending is not None:
            raise PhotoError(409, 'BUSY', 'Another photo request is still pending.')
        if len(self.records) >= self.capacity:
            raise PhotoError(503, 'CAPACITY', 'Photo request tracking is full; nothing was sent.')
        now = self.clock()
        token = secrets.token_urlsafe(32)
        metadata = getattr(self.registry, 'metadata', None)
        binding_guard = (metadata.guard({source.id}) if metadata is not None
                         else lambda: getattr(self.registry, 'metadata', None) is None)
        rec = Capture(request_id, 'p_' + secrets.token_hex(16), lease, generation,
                      self.registry.room, self.registry.room.epoch, source, source.ws,
                      self.consents[source.id].revision, self.role_revision, self.viewer.revision,
                      self.viewer.id, min(now + self.capture_timeout, lease.expires_at),
                      _digest(token), lease.expires_at + 120, binding_guard)
        self.records[key] = self.by_capture[rec.id] = rec
        self.pending = rec
        args = {'capture_id': rec.id, 'upload_url': '/photos/uploads/' + rec.id, 'upload_token': token}
        def possible_send(_req, _dev):
            rec.sent = True
        try:
            result = await self.bus.call(source.id, 'camera.capture', args,
                timeout=max(.001, rec.deadline - self.clock()),
                authorize=lambda dev, cap, supplied: dev is source and self._valid(rec) and dispatch_allowed(),
                on_dispatch=possible_send)
        except asyncio.CancelledError:
            if self.pending is rec:
                self._fail(rec, 'unknown' if rec.sent else 'failed', 'UNKNOWN' if rec.sent else 'CANCELLED',
                           'Capture outcome is uncertain; it will not be repeated.' if rec.sent else 'Nothing was sent.')
            raise
        if self.pending is not rec:
            return rec.status()
        if not result.ok:
            state = 'unknown' if rec.sent and result.code == 'UNKNOWN' else 'failed'
            self._fail(rec, state, result.code if result.code in RESULT_CODES else 'PHONE_FAILED',
                       'Capture outcome is uncertain; it will not be repeated.' if state == 'unknown'
                       else 'The phone did not confirm this photo request.')
            return rec.status()
        payload = result.result
        if (not isinstance(payload, dict) or payload.get('capture_id') != rec.id
                or payload.get('state') != 'captured'):
            self._fail(rec, 'unknown', 'UNKNOWN', 'The phone did not identify the captured still; no retry.')
            return rec.status()
        rec.captured = True
        if not self._valid(rec):
            self._cancel_pending('Photo authority ended before publication.')
            return rec.status()
        rec.state, rec.message = 'captured', 'Phone capture confirmed; waiting for the image.'
        self._publish(rec)
        return rec.status()

    def _fail(self, rec, state, code, message):
        rec.state, rec.code, rec.message = state, code, message
        rec.image = None
        if self.pending is rec:
            self.pending = None
            self.version += 1

    def _publish(self, rec):
        if rec.captured and rec.stored and rec.image is not None and self._valid(rec):
            self.version += 1
            rec.image.version = self.version
            rec.state, rec.message = 'ready', 'Photo received; Mac display is not yet confirmed.'

    async def upload(self, capture_id, token, body, content_type):
        self.sweep()
        rec = self.by_capture.get(capture_id) if isinstance(capture_id, str) else None
        if (rec is None or not isinstance(token, str) or not 1 <= len(token) <= 128
                or not secrets.compare_digest(_digest(token), rec.ticket_digest)):
            raise PhotoError(403, 'PERMISSION', 'A device-bound photo upload ticket is required.')
        if not isinstance(body, bytes) or not body or len(body) > MAX_BYTES:
            raise PhotoError(413 if isinstance(body, bytes) and len(body) > MAX_BYTES else 400,
                             'INVALID_IMAGE', 'JPEG upload exceeds its bound or is empty.')
        body_digest = hashlib.sha256(body).digest()
        if rec.ticket_used:
            if rec.uploading:
                raise PhotoError(409, 'BUSY', 'This upload is already being validated.')
            if rec.stored and rec.upload_digest == body_digest and rec.state not in {'failed', 'unknown', 'cancelled'}:
                return rec.status()
            raise PhotoError(409, 'CONFLICT', 'The upload ticket has already been used.')
        if not self._valid(rec):
            raise PhotoError(410, 'STALE', 'The photo upload is no longer authorized.')
        rec.ticket_used, rec.uploading, rec.upload_digest = True, True, body_digest
        if self.normalizer is None:
            from brain.core.photo_image import normalize_jpeg
            normalizer = normalize_jpeg
        else:
            normalizer = self.normalizer
        try:
            normalized = await asyncio.to_thread(normalizer, body, content_type)
        except ValueError:
            if self.pending is rec:
                self._fail(rec, 'failed', 'INVALID_IMAGE', 'The uploaded image could not be validated.')
            raise PhotoError(400, 'INVALID_IMAGE', 'The uploaded image could not be validated.') from None
        except asyncio.CancelledError:
            if self.pending is rec:
                self._fail(rec, 'unknown', 'UNKNOWN', 'Upload validation was interrupted; no recapture.')
            raise
        except Exception:
            if self.pending is rec:
                self._fail(rec, 'failed', 'VALIDATION_UNAVAILABLE', 'Image validation is unavailable.')
            raise
        finally:
            rec.uploading = False
        if not self._valid(rec):
            if self.pending is rec:
                self._cancel_pending('Photo authority changed during image validation.')
            raise PhotoError(410, 'STALE', 'The photo upload is no longer authorized.')
        if not isinstance(normalized, bytes) or not normalized or len(normalized) > MAX_BYTES:
            self._fail(rec, 'failed', 'INVALID_IMAGE', 'The normalized image exceeded its bound.')
            raise PhotoError(400, 'INVALID_IMAGE', 'The normalized image exceeded its bound.')
        rec.stored = True
        rec.image = Image(rec.id, 0, normalized, self.clock(), rec.source.label, rec.viewer_id)
        rec.state, rec.message = 'stored', 'Image validated; waiting for phone capture confirmation.'
        self._publish(rec)
        return rec.status()

    def viewer_state(self, token):
        self._viewer(token)  # Never let an unauthenticated poll change service state/liveness.
        self.sweep()
        viewer = self._viewer(token, touch=True)
        rec = self.pending
        candidate = rec.image if rec and rec.state == 'ready' else None
        photo = candidate or self.latest
        if photo and photo.viewer_id != viewer.id:
            photo = None
        return {'ok': True, 'version': self.version, 'photo': photo.public() if photo else None,
                'pending': candidate is not None}

    def image(self, token, photo_id):
        self._viewer(token)
        self.sweep()
        viewer = self._viewer(token)
        rec = self.pending
        for image in (rec.image if rec and rec.state == 'ready' else None, self.latest):
            if image and image.id == photo_id and image.viewer_id == viewer.id:
                return image.data
        raise PhotoError(404, 'NOT_FOUND', 'This photo is not available to this viewer.')

    def viewer_receipt(self, token, photo_id, version):
        self._viewer(token)
        self.sweep()
        viewer = self._viewer(token, touch=True)
        if not isinstance(photo_id, str) or type(version) is not int:
            raise PhotoError(400, 'INVALID', 'Expected photo_id and integer version.')
        if (self.latest and self.latest.id == photo_id and self.latest.version == version
                and self.latest.viewer_id == viewer.id):
            return {'ok': True, 'state': 'displayed', 'photo_id': photo_id, 'version': version}
        rec = self.pending
        if (not rec or rec.state != 'ready' or not rec.image or rec.image.id != photo_id
                or rec.image.version != version or not self._valid(rec)):
            raise PhotoError(409, 'STALE', 'The viewer receipt does not match the current authorized photo.')
        self.latest, rec.image = rec.image, None
        rec.displayed, rec.state, rec.message = True, 'displayed', 'The selected Mac viewer confirmed rendering.'
        self.pending = None
        return {'ok': True, 'state': 'displayed', 'photo_id': photo_id, 'version': version}
