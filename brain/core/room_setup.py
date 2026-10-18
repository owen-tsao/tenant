"""Persist a host-authorized display label without changing room authority."""
from fastapi import HTTPException


def set_room_label(core, body):
    if (not isinstance(body, dict) or set(body) != {'label'} or not isinstance(body['label'], str)
            or not 1 <= len(body['label'].strip()) <= 128
            or any(ord(char) < 32 or ord(char) == 127 for char in body['label'])):
        raise HTTPException(400, 'Expected a room label of 1 to 128 characters on one line')
    label = body['label'].strip()
    private_values = (core.config.host_token, core.config.device_token,
                      *getattr(core.agent, 'private_values', ()))
    if any(isinstance(value, str) and value and value in label for value in private_values):
        raise HTTPException(400, 'Choose a room label without private credentials')
    registry, room = core.registry, core.registry.room
    if not registry.persistence_healthy:
        raise HTTPException(503, 'Room state needs recovery before naming the room')
    previous = room.label
    room.label = label
    # No await: display publication and reconnects observe only the saved label.
    if not registry.persist():
        room.label = previous
        raise HTTPException(503, 'Room name persistence is unconfirmed; room control is unavailable')
    return {'ok': True, 'room': {'code': room.code, 'label': room.label,
                               'join_url': core.config.public_url.rstrip('/') + '/j/' + room.code}}
