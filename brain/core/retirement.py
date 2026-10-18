"""Host-attested retirement of disconnected enrollment aliases; no device actions."""
from uuid import uuid4

from fastapi import HTTPException


def retire_devices(core, body):
    """Run without awaits after host authentication and JSON parsing.

    Registry enrollment/reconnect is synchronous too: either it is already
    online and rejected here, or its old alias is removed before it can enroll.
    A fresh current invitation can still enroll that ID; this is not an ID ban.
    """
    if (not isinstance(body, dict) or set(body) != {'device_ids', 'reason', 'physical_off_confirmed'}
            or body.get('physical_off_confirmed') is not True
            or not isinstance(body.get('reason'), str) or not 1 <= len(body['reason'].strip()) <= 200
            or not isinstance(body.get('device_ids'), list) or not body['device_ids']
            or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in body['device_ids'])
            or len(set(body['device_ids'])) != len(body['device_ids'])):
        raise HTTPException(400, 'Expected unique device_ids, a short reason, and physical_off_confirmed: true')
    registry, bus = core.registry, core.bus
    if not registry.persistence_healthy:
        raise HTTPException(503, 'Room state needs recovery before device retirement')
    ids = set(body['device_ids'])
    if not ids <= registry.enrollments.keys():
        raise HTTPException(404, 'Every requested device must have a known enrollment; nothing was retired')
    programs = getattr(core.agent, 'programs', None)
    tools = getattr(core.agent, 'device_tools', None)
    for device_id in ids:
        device = registry.devices.get(device_id)
        locked = (bus.locks.get(device_id), getattr(tools, 'device_locks', {}).get(device_id))
        if ((device is not None and (device.online or device.busy))
                or any(lock is not None and lock.locked() for lock in locked)
                or any(owner.id == device_id for owner, _ in bus.pending.values())
                or any(owner.id == device_id for owner in bus.uncertain.values())
                or (programs is not None and programs.retirement_blocked(device_id))):
            raise HTTPException(409, 'A requested device is connected, busy, uncertain, or still claimed by a program; nothing was retired')

    # The public sentence contains no IDs or host-supplied text. Private reason
    # text uses the same known-literal boundary as the conversation, not a claim
    # of general secret detection or computer isolation.
    reason = body['reason'].strip()
    private_values = (core.config.host_token, core.config.device_token,
                      *getattr(core.agent, 'private_values', ()))
    for value in private_values:
        if isinstance(value, str) and value:
            reason = reason.replace(value, '[redacted]')
    ordered = sorted(ids)
    audit = {'actor': 'host', 'operation_id': uuid4().hex, 'device_ids': ordered,
             'reason': reason, 'physical_off_confirmed': True, 'evidence': 'host_observation_not_device_ack'}
    try:
        core.log.append('host.retire', 'The host requested retirement of obsolete disconnected devices.',
                        **audit, outcome='requested')
    except Exception:
        registry.persistence_healthy = False
        raise HTTPException(503, 'Retirement audit could not be saved; nothing was retired') from None

    previous = registry.enrollments
    registry.enrollments = {device_id: aliases for device_id, aliases in previous.items() if device_id not in ids}
    if not registry.persist():
        registry.enrollments = previous
        # A failure after atomic replacement can have persisted the change.
        # persistence_healthy stays false; no automatic retry or disk rollback.
        try:
            core.log.append('host.retire', 'Device retirement persistence could not be confirmed; room control is disabled.',
                            **audit, outcome='persistence_unconfirmed')
        except Exception:
            pass
        raise HTTPException(503, 'Retirement persistence is unconfirmed; room control is disabled')
    for device_id in ids:
        registry.devices.pop(device_id, None)
        registry.room.device_ids.discard(device_id)
    try:
        core.log.append('host.retire', 'The host retired obsolete disconnected device enrollments. A fresh reset is still required.',
                        **audit, outcome='persisted')
    except Exception:
        registry.persistence_healthy = False
        raise HTTPException(503, {'error': 'Retirement was saved but its completion audit is unconfirmed; room control is disabled',
                                  'retired': ordered}) from None
    return {'ok': True, 'retired': ordered}
