"""Build a live inventory and validate untrusted planner requests locally."""
import re
from brain.core.bus import Bus


def slug(value):
    return re.sub(r'[^a-zA-Z0-9_]', '_', value)


def inventory_for(registry, leases, lease):
    out = []
    for dev in registry.devices.values():
        if dev.room_id != registry.room.id:
            continue
        caps = []
        for cap in dev.caps.values():
            if registry.metadata.described(dev, cap.name) and ('*' in lease.scopes or cap.name in lease.scopes):
                caps.append({'name': cap.name, 'args': cap.args, 'description': cap.description,
                             'tool': f'{slug(dev.id)}__{slug(cap.name)}' if registry.metadata.available(dev, cap.name) else None})
        out.append({'id': dev.id, 'label': dev.label, 'online': registry.metadata.binding(dev.id) is dev,
                    'busy': dev.busy, 'caps': caps})
    return out


def valid_action(registry, lease, plan):
    if not isinstance(plan, dict) or not isinstance(plan.get('device_id'), str) or not isinstance(plan.get('cap'), str):
        return None
    dev = registry.devices.get(plan['device_id'])
    if not dev or dev.room_id != registry.room.id:
        return None
    cap = plan['cap']
    spec = dev.caps.get(cap)
    if not spec or not ('*' in lease.scopes or cap in lease.scopes) or not Bus.valid_args(spec, plan.get('args')):
        return None
    return dev


def alternatives_for(registry, lease, source_id, cap, args):
    return [dev for dev in registry.devices.values()
            if dev.id != source_id and dev.online and dev.room_id == registry.room.id
            and ('*' in lease.scopes or cap in lease.scopes)
            and registry.metadata.available(dev, cap) and Bus.valid_args(dev.caps[cap], args)]
