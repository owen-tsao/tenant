from brain.state import Device, CapSpec

class Registry:
    def __init__(self, room):
        self.room = room
        self.devices = {}

    def register(self, frame, ws):
        if not isinstance(frame, dict) or frame.get("type") != "hello" or frame.get("room") != self.room.code:
            raise ValueError("Invalid hello or room")
        for key in ("id", "label"):
            if not isinstance(frame.get(key), str) or not 1 <= len(frame[key]) <= 128:
                raise ValueError("Invalid device identity")
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
        previous = self.devices.get(frame["id"])
        if previous and previous.online:
            raise ValueError("Device already connected")
        dev = Device(frame["id"], frame["label"], frame["room"], parsed, ws)
        self.devices[dev.id] = dev
        self.room.device_ids.add(dev.id)
        return dev

    def online_in(self, room):
        code = room.code if hasattr(room, "code") else room
        return [d for d in self.devices.values() if d.online and d.room_code == code]

    def offline(self, dev):
        dev.online = False
