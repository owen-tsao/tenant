"""Optional atomic persistence of room identity, epoch and enrolled aliases only.

Guests, credentials, messages, capabilities and live device state are never saved.
An invalid existing file is an error, never an invitation to reset authority.
"""
import json
import os
from pathlib import Path
import re
import tempfile
from brain.state import Room
from brain.core.registry import Registry


class RoomStateError(RuntimeError):
    pass


def valid_code(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Z0-9]{4,16}', value) is not None


def validate(data):
    if not isinstance(data, dict) or set(data) != {'version', 'room', 'enrollments'} or type(data['version']) is not int or data['version'] != 1:
        raise RoomStateError('Unsupported room state')
    room, enrollments = data['room'], data['enrollments']
    if not isinstance(room, dict) or set(room) != {'id', 'code', 'label', 'epoch'}:
        raise RoomStateError('Invalid room identity')
    if not isinstance(room['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', room['id']):
        raise RoomStateError('Invalid stable room ID')
    if not valid_code(room['code']) or not isinstance(room['label'], str) or not 1 <= len(room['label']) <= 128:
        raise RoomStateError('Invalid room invitation')
    if type(room['epoch']) is not int or not 0 <= room['epoch'] < 2**63:
        raise RoomStateError('Invalid room epoch')
    if not isinstance(enrollments, dict) or len(enrollments) > 512:
        raise RoomStateError('Invalid enrollment state')
    for device_id, aliases in enrollments.items():
        if not isinstance(device_id, str) or not 1 <= len(device_id) <= 128:
            raise RoomStateError('Invalid enrolled device ID')
        if not isinstance(aliases, list) or not 1 <= len(aliases) <= 512 or not all(valid_code(a) for a in aliases):
            raise RoomStateError('Invalid enrollment aliases')
    return data


class RoomStateStore:
    def __init__(self, path):
        self.path = Path(path)

    def load_registry(self, default_code, label=None):
        if self.path.exists():
            try:
                # A small room-state file should never approach this limit.
                if self.path.stat().st_size > 1_000_000:
                    raise RoomStateError('Room state exceeds the size limit')
                data = validate(json.loads(self.path.read_text(encoding='utf-8')))
            except (OSError, ValueError, UnicodeError) as exc:
                raise RoomStateError('Existing room state could not be safely loaded') from exc
            room_data = data['room']
            room = Room(room_data['code'], room_data['label'], epoch=room_data['epoch'], id=room_data['id'])
            registry = Registry(room)
            registry.enrollments = {device_id: set(aliases) for device_id, aliases in data['enrollments'].items()}
        else:
            if not valid_code(default_code):
                raise RoomStateError('Invalid initial room code')
            registry = Registry(Room(default_code, label or 'Room ' + default_code))
        registry.on_change = self.save_registry
        if not registry.persist():
            raise RoomStateError('Room state is not writable; refusing to start control')
        return registry

    def save_registry(self, registry):
        room = registry.room
        data = validate({'version': 1, 'room': {'id': room.id, 'code': room.code, 'label': room.label, 'epoch': room.epoch},
                         'enrollments': {device_id: sorted(aliases) for device_id, aliases in registry.enrollments.items()}})
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.' + self.path.name + '-', dir=self.path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(data, handle, sort_keys=True)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            # Ensure the replacement directory entry is durable before returning.
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
