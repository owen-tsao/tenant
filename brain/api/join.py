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
    if body.get('phone'):
        return JSONResponse({'error': 'Text-message access is unavailable; choose Chat here'}, status_code=503)
    lease = core.leases.create()
    secret = core.issue_credential(lease.guest_id)
    response = JSONResponse({'guest_id': lease.guest_id, 'guest_token': secret,
                             'chat_url': '/g/' + lease.guest_id + '?room=' + core.registry.room.code + '#t=' + secret})
    response.set_cookie(core.cookie_name(lease.guest_id), secret, httponly=True, samesite='strict',
                        secure=core.config.public_url.startswith('https://'), max_age=720, path='/')
    response.headers['Cache-Control'] = 'no-store'
    core.log.append('guest.join', lease.display_name + ' joined the room.', guest_id=lease.guest_id)
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
