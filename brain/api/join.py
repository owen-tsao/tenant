from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


async def json_object(request):
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None


@router.post('/join')
async def join(request: Request):
    core = request.app.state.core
    core.require_origin(request)
    if not core.registry.persistence_healthy:
        return JSONResponse({'error': 'Room control is unavailable until its state can be saved'}, status_code=503)
    body = await json_object(request)
    if not body or not isinstance(body.get('room_code'), str):
        return JSONResponse({'error': 'Expected room_code'}, status_code=400)
    if body['room_code'] != core.registry.room.code:
        return JSONResponse({'error': 'Room invitation is invalid or expired'}, status_code=404)
    new_guest, secret = True, None
    phone = body.get('phone')
    if phone is not None:
        if core.photon is None:
            return JSONResponse({'error': 'Text-message access is unavailable; choose Chat here'}, status_code=503)
        from brain.channels.photon import PhotonError
        existing_guest = body.get('guest_id')
        admission_room, admission_epoch = core.registry.room, core.registry.room.epoch
        try:
            if existing_guest is None:
                # The existing phone form omits guest_id on retry/refresh. Only
                # its exact bound guest credential may recover that same lease.
                bound_guest = core.photon.bound_guest(phone)
                candidate = body.get('guest_token')
                if candidate is None and bound_guest is not None:
                    candidate = request.cookies.get(core.cookie_name(bound_guest), '')
                if bound_guest is not None and core.authentic_token(bound_guest, candidate):
                    existing_guest, secret = bound_guest, candidate
            if existing_guest is not None:
                # A phone number or public guest ID is never proof of access.
                secret = body.get('guest_token') if body.get('guest_token') is not None else secret
                if secret is None:
                    secret = request.cookies.get(core.cookie_name(existing_guest), '') if isinstance(existing_guest, str) else ''
                if not core.authentic_token(existing_guest, secret):
                    return JSONResponse({'error': 'Guest authorization required'}, status_code=403)
            enrollment = await core.photon.enroll(
                phone, guest_id=existing_guest,
                authorize=lambda: (core.registry.persistence_healthy
                                   and core.registry.room is admission_room
                                   and core.registry.room.epoch == admission_epoch
                                   and core.registry.room.code == body['room_code']))
        except PhotonError as error:
            core.log.append('photon', 'Room text setup needs attention.',
                            photon_status='JOIN_REJECTED', code=error.code, http_status=error.status)
            return JSONResponse({'error': str(error), 'code': error.code}, status_code=error.status,
                                headers={'Cache-Control': 'no-store'})
        lease, new_guest = enrollment.lease, enrollment.new_guest
        phone_fields = {'imessage_number': enrollment.imessage_number, 'sms_link': enrollment.sms_link}
    else:
        lease, phone_fields = core.leases.create(), {}
    if new_guest:
        secret = core.issue_credential(lease.guest_id)
    response = JSONResponse({'guest_id': lease.guest_id, 'guest_token': secret,
                             'chat_url': '/g/' + lease.guest_id + '?room=' + core.registry.room.code + '#t=' + secret,
                             **phone_fields})
    response.set_cookie(core.cookie_name(lease.guest_id), secret, httponly=True, samesite='strict',
                        secure=core.config.public_url.startswith('https://'), max_age=720, path='/')
    response.headers['Cache-Control'] = 'no-store'
    core.log.append('guest.join' if new_guest else 'guest.link',
                    lease.display_name + (' joined the room.' if new_guest else ' linked the room text channel.'),
                    guest_id=lease.guest_id)
    return response


@router.post('/leave')
async def leave(request: Request):
    core = request.app.state.core
    core.require_origin(request)
    body = await json_object(request)
    guest_id = body.get('guest_id') if body else None
    if not core.authentic_guest(guest_id, request.cookies):
        return JSONResponse({'error': 'Guest authorization required'}, status_code=403)
    core.revoke(guest_id, actor='guest')
    return {'ok': True}
