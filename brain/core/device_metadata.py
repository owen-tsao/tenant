"""Evidence for existing authenticated enrollments; no discovery grants authority.

Only host assertions and the adapter's last label are durable. Connections,
schemas, consent and capability readiness must be observed again after restart.
"""
import copy
import math
import time

from fastapi import HTTPException


HOST_FIELDS = frozenset({'label', 'role', 'location', 'output_description', 'allowed'})
MAX_AGE = 10.0  # Same two-heartbeat bound as the existing device socket.


def plain(value, limit=128):
    return (isinstance(value, str) and 1 <= len(value.strip()) <= limit
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_records(records, enrollments):
    """Strict persistence boundary; never load bindings or permission from a hello."""
    if not isinstance(records, dict) or not records.keys() <= enrollments.keys():
        raise ValueError('Invalid device metadata identities')
    for device_id, record in records.items():
        if (not isinstance(record, dict) or set(record) != {'revision', 'host', 'adapter_label'}
                or type(record['revision']) is not int or not 0 <= record['revision'] < 2**63
                or not isinstance(record['host'], dict) or not record['host'].keys() <= HOST_FIELDS):
            raise ValueError('Invalid device metadata')
        adapter = record['adapter_label']
        if (not isinstance(adapter, dict) or set(adapter) != {'value', 'at'}
                or not isinstance(adapter['value'], str) or not 1 <= len(adapter['value']) <= 128
                or not timestamp(adapter['at'])):
            raise ValueError('Invalid adapter label evidence')
        for field, assertion in record['host'].items():
            if (not isinstance(assertion, dict) or set(assertion) != {'value', 'at'}
                    or not timestamp(assertion['at'])):
                raise ValueError('Invalid host assertion')
            value = assertion['value']
            if ((field == 'allowed' and type(value) is not bool)
                    or (field != 'allowed' and value is not None and not plain(value))
                    or (field == 'label' and value is None)):
                raise ValueError('Invalid host assertion value')
    return records


class DeviceMetadata:
    def __init__(self, registry, *, clock=time.time, monotonic=time.monotonic):
        self.registry, self.clock, self.monotonic = registry, clock, monotonic
        self.records = {}
        self.observed_at = {}
        self.private_values = ()
        # Only the explicitly installed photo owner can supply current consent/
        # viewer readiness. Raw discovery and host role strings cannot open it.
        self.camera_ready = lambda _device: False

    def safe_text(self, value):
        for secret in self.private_values:
            if isinstance(secret, str) and secret:
                value = value.replace(secret, '[private value]')
        return ' '.join(''.join(' ' if ord(char) < 32 or ord(char) == 127 else char
                               for char in value).split())[:128] or 'Enrolled device'

    def configure_private_values(self, values):
        self.private_values = tuple(value for value in values if isinstance(value, str) and value)
        for record in self.records.values():
            record['adapter_label']['value'] = self.safe_text(record['adapter_label']['value'])

    def export(self):
        return copy.deepcopy({key: value for key, value in self.records.items()
                              if key in self.registry.enrollments})

    def observe_label(self, device_id, label, *, new_identity=False):
        # Re-enrollment after retirement is a fresh identity, even for the same ID.
        if new_identity or device_id not in self.records:
            self.records[device_id] = {'revision': 0, 'host': {}, 'adapter_label': {}}
        now = self.clock()
        self.records[device_id]['adapter_label'] = {'value': self.safe_text(label), 'at': now}
        self.observed_at[device_id] = now

    def value(self, device_id, field, default=None):
        record = self.records.get(device_id, {})
        assertion = record.get('host', {}).get(field)
        return assertion['value'] if assertion is not None else default

    def label(self, device_id, fallback='Enrolled device'):
        record = self.records.get(device_id, {})
        return self.safe_text(self.value(device_id, 'label', record.get('adapter_label', {}).get('value', fallback)))

    def revision(self, device_id):
        return self.records.get(device_id, {}).get('revision', 0)

    def guard(self, device_ids):
        """Capture target identities/revisions before the earliest logical wait.

        This fence is deliberately separate from current guest/consent/feature
        authority and must travel with an operation through all its queue waits.
        """
        before = {key: (self.registry.devices.get(key), self.revision(key))
                  for key in device_ids if isinstance(key, str)}
        return lambda: all(self.registry.devices.get(key) is device and self.revision(key) == revision
                           for key, (device, revision) in before.items())

    def binding(self, device_id):
        """Current exact live binding, not a guest grant or a physical identity claim."""
        registry = self.registry
        dev = registry.devices.get(device_id)
        if (not registry.persistence_healthy or device_id not in registry.enrollments
                or dev is None or dev.room_id != registry.room.id or not dev.online
                or not 0 <= self.monotonic() - dev.last_seen < MAX_AGE):
            return None
        return dev

    def role_devices(self, role):
        """Explicit host-role matches only. Caller must check scopes/consent/gates."""
        if not plain(role):
            return ()
        return tuple({'device_id': key, 'metadata_revision': self.revision(key)} for key in self.registry.enrollments
                     if self.value(key, 'role') == role and self.value(key, 'allowed', True)
                     and self.binding(key) is not None)

    def blocked_reason(self, dev, capability):
        registry = self.registry
        if (dev is None or registry.devices.get(dev.id) is not dev
                or dev.id not in registry.enrollments or dev.room_id != registry.room.id):
            return 'The device binding has changed.'
        if not registry.persistence_healthy:
            return 'Room identity storage needs recovery.'
        if not dev.online:
            return 'The device is disconnected.'
        if self.binding(dev.id) is not dev:
            return 'The device connection needs a fresh heartbeat.'
        if not self.value(dev.id, 'allowed', True):
            return 'Room use is disabled by the host.'
        if capability not in dev.caps:
            return 'The current adapter does not advertise this capability.'
        if capability == 'camera.capture':
            try:
                if not self.camera_ready(dev):
                    return 'Room photos are not enabled; separate camera consent is required.'
            except Exception:
                return 'Room photo readiness could not be confirmed.'
        return None

    def available(self, dev, capability):
        """Necessary binding/host-policy conditions; never replaces guest authority."""
        return self.blocked_reason(dev, capability) is None

    def described(self, dev, capability):
        """Retain offline descriptions as non-executable facts for existing clients."""
        return self.blocked_reason(dev, capability) in (
            None, 'The device is disconnected.', 'The device connection needs a fresh heartbeat.')

    def public_devices(self):
        """Detached, safe facts for the existing display, including offline identities."""
        rows = []
        for device_id in self.registry.enrollments:
            dev = self.registry.devices.get(device_id)
            if dev is not None and dev.room_id != self.registry.room.id:
                continue
            live = self.binding(device_id) is not None
            connection = ('online' if live else 'offline' if dev is not None and not dev.online else 'unknown')
            record = self.records.get(device_id, {})
            provenance = {'identity': {'source': 'authenticated_enrollment'},
                          'capabilities': {'source': 'adapter_reported', 'at': self.observed_at.get(device_id)}}
            for field in ('label', 'role', 'location', 'output_description', 'allowed'):
                assertion = record.get('host', {}).get(field)
                if assertion is not None:
                    provenance[field] = {'source': 'host_specified', 'at': assertion['at']}
                elif field == 'label' and record.get('adapter_label'):
                    provenance[field] = {'source': 'adapter_reported', 'at': record['adapter_label']['at']}
                else:
                    provenance[field] = {'source': 'existing_enrollment_policy' if field == 'allowed' else 'unknown'}
            statuses = []
            for cap in dev.caps if dev is not None else ():
                if self.safe_text(cap) != cap:
                    continue
                reason = self.blocked_reason(dev, cap)
                statuses.append({'name': cap, 'status': 'blocked' if reason else 'available',
                                 'reason': reason, 'provenance': 'adapter_reported',
                                 'observed_at': self.observed_at.get(device_id)})
            rows.append({'id': device_id, 'label': self.label(device_id, dev.label if dev else 'Enrolled device'),
                         'caps': [row['name'] for row in statuses if row['status'] == 'available'],
                         'online': live, 'busy': bool(live and dev.busy), 'connection_state': connection,
                         'role': self._public_value(device_id, 'role'), 'location': self._public_value(device_id, 'location'),
                         'output_description': self._public_value(device_id, 'output_description'),
                         'allowed': self.value(device_id, 'allowed', True),
                         'metadata_revision': self.revision(device_id),
                         'provenance': provenance, 'capability_status': statuses})
        return copy.deepcopy(rows)

    def _public_value(self, device_id, field):
        value = self.value(device_id, field)
        return self.safe_text(value) if isinstance(value, str) else value


def update_metadata(core, device_id, body):
    """Synchronous host-only transaction; no effects, scope grants or implicit consent."""
    if (not isinstance(body, dict) or not body or not body.keys() <= HOST_FIELDS
            or any((type(value) is not bool if field == 'allowed' else
                    value is not None and not plain(value)) or (field == 'label' and value is None)
                   for field, value in body.items())):
        raise HTTPException(400, 'Expected bounded label, role, location, output_description or allowed')
    private = (core.config.host_token, core.config.device_token, *getattr(core.agent, 'private_values', ()))
    if any(isinstance(value, str) and isinstance(secret, str) and secret and secret in value
           for value in body.values() for secret in private):
        raise HTTPException(400, 'Device metadata must not contain private credentials')
    registry = core.registry
    if not registry.persistence_healthy:
        raise HTTPException(503, 'Room identity storage needs recovery')
    if device_id not in registry.enrollments:
        raise HTTPException(404, 'An authenticated device enrollment is required')
    current = registry.devices.get(device_id)
    if current is not None and current.room_id != registry.room.id:
        raise HTTPException(404, 'A current-room device enrollment is required')
    metadata = registry.metadata
    previous = copy.deepcopy(metadata.records.get(device_id))
    if previous is None:
        # Older v1 enrollment files have no retained adapter label.
        metadata.records[device_id] = {'revision': 0, 'host': {},
                                       'adapter_label': {'value': 'Enrolled device', 'at': metadata.clock()}}
    record = metadata.records[device_id]
    if record['revision'] >= 2**63 - 1:
        raise HTTPException(409, 'Device metadata revision limit reached')
    record['revision'] += 1
    for field, value in body.items():
        record['host'][field] = {'value': value.strip() if isinstance(value, str) else value, 'at': metadata.clock()}
    if not registry.persist():
        if previous is None:
            metadata.records.pop(device_id, None)
        else:
            metadata.records[device_id] = previous
        # A post-replacement failure can leave the new durable value. Fail closed;
        # memory rollback is not a durable rollback claim or an automatic retry.
        raise HTTPException(503, 'Device metadata persistence is unconfirmed; control is unavailable')
    dev = registry.devices.get(device_id)
    if dev is not None:
        dev.label = metadata.label(device_id, dev.label)
    return {'ok': True, 'device': next(row for row in metadata.public_devices() if row['id'] == device_id)}
