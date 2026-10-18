"""Minimal host metadata seam; device discovery never supplies host assertions."""
from fastapi import APIRouter, Request
from brain.api.join import json_object
from brain.core.device_metadata import update_metadata

router = APIRouter()


@router.patch('/host/devices/{device_id}/metadata')
async def metadata(device_id: str, request: Request):
    core = request.app.state.core
    core.require_host(request)
    return update_metadata(core, device_id, await json_object(request))
