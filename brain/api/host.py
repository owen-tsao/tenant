from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from brain.api.join import json_object

router = APIRouter()


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
