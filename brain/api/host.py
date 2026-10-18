from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from brain.api.join import json_object

router = APIRouter()


@router.post('/host/room')
async def room(request: Request):
    core = request.app.state.core
    if 'authorization' in request.headers:
        # An explicit invalid Bearer header cannot fall back to another token.
        core.require_host(request)
    else:
        # Compatibility for Owen's setup page only; never widen other host APIs.
        core.require_origin(request)
        token = request.headers.get('x-host-token', '')
        if not core.host_authorized('Bearer ' + token):
            raise HTTPException(403, 'Host authorization required')
    from brain.core.room_setup import set_room_label
    return set_room_label(core, await json_object(request))


@router.post('/host/revoke')
async def revoke(request: Request):
    core = request.app.state.core
    core.require_host(request)
    body = await json_object(request)
    if not body or not isinstance(body.get('guest_id'), str):
        return JSONResponse({'error': 'Expected guest_id'}, status_code=400)
    return {'ok': True, 'revoked': core.revoke(body['guest_id'])}


@router.post('/host/reset')
async def reset(request: Request):
    core = request.app.state.core
    core.require_host(request)
    return await core.reset()


@router.post('/host/devices/retire')
async def retire(request: Request):
    core = request.app.state.core
    core.require_host(request)
    from brain.core.retirement import retire_devices
    return retire_devices(core, await json_object(request))
