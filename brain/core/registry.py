from brain.state import Device, CapSpec
from brain.core.device_metadata import DeviceMetadata
import copy


class DeviceAlreadyConnected(ValueError):
    """A valid device must wait for its existing connection to end."""


class Registry:
    def __init__(self, room):
        self.room = room
        self.devices = {}
        self.enrollments = {}
        self.on_change = None
        self.persistence_healthy = True
        self.metadata = DeviceMetadata(self)

    def persist(self):
        # An ambiguous write may have durably saved a denial while memory was
        # rolled back. Only a trusted reload reconciles that state; a later
        # hello or unrelated save must never overwrite it and reopen control.
        if not self.persistence_healthy:
            return False
        try:
            if self.on_change is not None:
                self.on_change(self)
        except Exception:
            self.persistence_healthy = False
            return False
        self.persistence_healthy = True
        # Successful retirement removes evidence as well as old aliases.
        self.metadata.records = {key: value for key, value in self.metadata.records.items() if key in self.enrollments}
        self.metadata.observed_at = {key: value for key, value in self.metadata.observed_at.items() if key in self.enrollments}
        return True

    def register(self, frame, ws):
        if not isinstance(frame, dict) or frame.get("type") != "hello":
            raise ValueError("Invalid hello or room")
        for key in ("id", "label"):
            if not isinstance(frame.get(key), str) or not 1 <= len(frame[key]) <= 128:
                raise ValueError("Invalid device identity")
        if not isinstance(frame.get('room'), str):
            raise ValueError('Invalid room')
        previous = self.devices.get(frame["id"])
        # A previously authenticated device may reconnect with its enrollment alias
        # after invitation rotation. Unknown devices need the current invitation.
        enrolled = frame.get("room") in self.enrollments.get(frame["id"], set())
        if frame.get("room") != self.room.code and not enrolled:
            raise ValueError("Invalid room")
        caps = frame.get("caps")
        if not isinstance(caps, dict) or len(caps) > 32:
            raise ValueError("Invalid capabilities")
        parsed = {}
        for name, spec in caps.items():
            if not isinstance(name, str) or not isinstance(spec, dict) or not isinstance(spec.get("args"), dict) or not isinstance(spec.get("description"), str):
                raise ValueError("Invalid capability")
            for arg, schema in spec["args"].items():
                if not isinstance(schema, dict) or schema.get("type") not in ("boolean", "string", "number", "integer"):
                    raise ValueError("Unsupported argument schema")
            if name == "light" and spec["args"] != {"on": {"type": "boolean"}}:
                raise ValueError("light requires boolean on")
            for schema in spec["args"].values():
                if "enum" in schema and not isinstance(schema["enum"], list):
                    raise ValueError("Invalid enum")
                for bound in ("minimum", "maximum"):
                    if bound in schema and (schema["type"] not in ("number", "integer") or type(schema[bound]) not in (int, float)):
                        raise ValueError("Invalid numeric bound")
            parsed[name] = CapSpec(name, spec["args"], spec["description"])
        if previous and previous.online:
            raise DeviceAlreadyConnected("Device already connected")
        saved_aliases = self.enrollments.get(frame['id'])
        saved_record = copy.deepcopy(self.metadata.records.get(frame['id']))
        saved_observation = self.metadata.observed_at.get(frame['id'])
        self.enrollments[frame['id']] = set(saved_aliases or ()) | {frame['room'], self.room.code}
        self.metadata.observe_label(frame['id'], frame['label'], new_identity=saved_aliases is None)
        if not self.persist():
            if saved_aliases is None:
                self.enrollments.pop(frame['id'], None)
            else:
                self.enrollments[frame['id']] = saved_aliases
            if saved_record is None:
                self.metadata.records.pop(frame['id'], None)
            else:
                self.metadata.records[frame['id']] = saved_record
            if saved_observation is None:
                self.metadata.observed_at.pop(frame['id'], None)
            else:
                self.metadata.observed_at[frame['id']] = saved_observation
            raise ValueError('Room persistence unavailable')
        dev = Device(frame["id"], self.metadata.label(frame['id']), self.room.code, parsed, ws, room_id=self.room.id)
        self.devices[dev.id] = dev
        self.room.device_ids.add(dev.id)
        return dev

    def online_in(self, room):
        room_id = room.id if hasattr(room, "id") else (self.room.id if room == self.room.code else None)
        return [d for d in self.devices.values() if d.online and room_id is not None and d.room_id == room_id]

    def offline(self, dev):
        dev.online = False
