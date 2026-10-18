"""Private still-photo transport. Installing this router is an explicit core step."""
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from brain.core.photos import PhotoError


JSON_LIMIT = 4096
IMAGE_LIMIT = 5 * 1024 * 1024
VIEWER_COOKIE = 'tenant_photo_viewer'
VIEWER_HTML = Path(__file__).resolve().parents[2] / 'agent' / 'photo_viewer.html'
VIEWER_SCRIPT = Path(__file__).resolve().parents[2] / 'agent' / 'photo_viewer.js'
VIEWER_CSP = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; "
    "img-src 'self' blob:; style-src 'unsafe-inline'; "
    "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'"
)


class PhotoRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_response(request):
            try:
                response = await handler(request)
            except PhotoError as error:
                response = JSONResponse({'ok': False, 'code': error.code,
                                         'message': error.message}, status_code=error.status)
            except HTTPException as error:
                response = JSONResponse({'detail': error.detail}, status_code=error.status_code,
                                        headers=error.headers)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            return response

        return private_response


router = APIRouter(route_class=PhotoRoute)


def _fail(code='INVALID_REQUEST', message='Invalid photo request', status=400):
    raise PhotoError(status, code, message)


def _id(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not all(c.isascii() and (c.isalnum() or c in '_-.') for c in value)):
        _fail()
    return value


def _query(request, allowed=()):
    if (set(request.query_params) != set(allowed)
            or any(len(request.query_params.getlist(key)) != 1 for key in allowed)):
        _fail()


def _no_alternate_auth(request, *, bearer=False):
    if request.headers.getlist('x-host-token') or (not bearer and request.headers.getlist('authorization')):
        _fail('PHOTO_AUTH_REQUIRED', 'Photo authorization required', 403)


def _bearer(request):
    _no_alternate_auth(request, bearer=True)
    values = request.headers.getlist('authorization')
    if len(values) != 1:
        _fail('PHOTO_AUTH_REQUIRED', 'Photo authorization required', 403)
    value = values[0]
    if (not value.startswith('Bearer ') or not 1 <= len(value[7:]) <= 512
            or any(c.isspace() or c == ',' for c in value[7:])):
        _fail('PHOTO_AUTH_REQUIRED', 'Photo authorization required', 403)
    return value[7:]


def _cookie(request, name):
    # Starlette's cookie dictionary discards duplicate names. Never let its
    # ordering choose which private credential grants access.
    values = [part.split('=', 1)[1] for header in request.headers.getlist('cookie')
              for part in (piece.strip() for piece in header.split(';'))
              if '=' in part and part.split('=', 1)[0].strip() == name]
    if len(values) != 1 or not request.cookies.get(name):
        _fail('PHOTO_AUTH_REQUIRED', 'Photo authorization required', 403)
    return request.cookies[name]


def _host(request):
    core = request.app.state.core
    _bearer(request)
    _origin(request)
    core.require_host(request)
    return core


def _origin(request):
    if len(request.headers.getlist('origin')) != 1:
        _fail('PHOTO_ORIGIN_REQUIRED', 'Approved same-origin request required', 403)
    request.app.state.core.require_origin(request)


def _guest(request, guest_id):
    core = request.app.state.core
    _no_alternate_auth(request)
    _cookie(request, core.cookie_name(guest_id))
    if not core.authentic_guest(guest_id, request.cookies):
        _fail('PHOTO_AUTH_REQUIRED', 'Photo authorization required', 403)
    lease = core.leases.leases.get(guest_id)
    if lease is None:
        _fail('PHOTO_AUTH_REQUIRED', 'Photo authorization required', 403)
    return core, lease


def _viewer(request):
    _no_alternate_auth(request)
    return _cookie(request, VIEWER_COOKIE)


def _viewer_asset(path, media_type):
    # These are fixed empty bootstrap assets, never private photo data or a
    # caller-selected filename. State/images retain their existing cookie gate.
    try:
        body = path.read_bytes()
    except OSError:
        _fail('PHOTO_VIEWER_UNAVAILABLE', 'Photo viewer is unavailable', 503)
    return Response(body, media_type=media_type,
                    headers={'X-Content-Type-Options': 'nosniff',
                             'Content-Security-Policy': VIEWER_CSP})


async def _body(request, limit):
    lengths = request.headers.getlist('content-length')
    if lengths:
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            _fail()
        if len(lengths[0]) > 10 or int(lengths[0]) > limit:
            _fail('PHOTO_TOO_LARGE', 'Photo request is too large', 413)
    result = bytearray()
    async for chunk in request.stream():
        if len(result) + len(chunk) > limit:
            _fail('PHOTO_TOO_LARGE', 'Photo request is too large', 413)
        result.extend(chunk)
    return bytes(result)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-finite JSON number')


async def _json(request, fields):
    types = request.headers.getlist('content-type')
    if len(types) != 1 or types[0].split(';', 1)[0].strip().lower() != 'application/json':
        _fail('PHOTO_MEDIA_TYPE', 'Expected application/json', 415)
    raw = await _body(request, JSON_LIMIT)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        _fail()
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail()
    return value


@router.get('/host/photos/config')
async def configuration(request: Request):
    core = _host(request)
    _query(request)
    return core.photos.configuration()


@router.post('/host/photos/config')
async def configure(request: Request):
    core = _host(request)
    _query(request)
    body = await _json(request, ('source_device_id', 'viewer_id', 'enabled'))
    if type(body['enabled']) is not bool:
        _fail()
    return core.photos.configure(_id(body['source_device_id']), _id(body['viewer_id']),
                                 enabled=body['enabled'])


@router.post('/host/photos/viewer')
async def enroll_viewer(request: Request):
    core = _host(request)
    _query(request)
    body = await _json(request, ('viewer_id',))
    viewer_id = _id(body['viewer_id'])
    token = core.photos.enroll_viewer(viewer_id)
    response = JSONResponse({'ok': True, 'viewer_id': viewer_id})
    response.set_cookie(VIEWER_COOKIE, token, httponly=True, samesite='strict',
                        secure=core.config.public_url.startswith('https://'), path='/photos')
    return response


@router.post('/photos/captures')
async def capture(request: Request):
    core = request.app.state.core
    _origin(request)
    _query(request)
    body = await _json(request, ('guest_id', 'request_id', 'source_device_id'))
    guest_id, request_id, source_id = (_id(body[key]) for key in ('guest_id', 'request_id', 'source_device_id'))
    core, lease = _guest(request, guest_id)
    return await core.photos.capture(lease, request_id, source_id,
                                     generation=getattr(core.agent, '_generation', 0))


@router.get('/photos/captures/{request_id}')
async def capture_status(request_id: str, request: Request):
    _query(request, ('guest_id',))
    core, lease = _guest(request, _id(request.query_params['guest_id']))
    return core.photos.status(lease, _id(request_id))


@router.get('/photos/viewer/state')
async def viewer_state(request: Request):
    _query(request)
    return request.app.state.core.photos.viewer_state(_viewer(request))


@router.get('/photos/viewer')
async def viewer_page(request: Request):
    _query(request)
    return _viewer_asset(VIEWER_HTML, 'text/html')


@router.get('/photos/viewer.js')
async def viewer_script(request: Request):
    _query(request)
    return _viewer_asset(VIEWER_SCRIPT, 'text/javascript')


@router.get('/photos/images/{photo_id}')
async def image(photo_id: str, request: Request):
    _query(request)
    body = request.app.state.core.photos.image(_viewer(request), _id(photo_id))
    return Response(body, media_type='image/jpeg', headers={'X-Content-Type-Options': 'nosniff'})


@router.post('/photos/viewer/receipt')
async def viewer_receipt(request: Request):
    core = request.app.state.core
    _origin(request)
    _query(request)
    token = _viewer(request)
    body = await _json(request, ('photo_id', 'version'))
    version = body['version']
    if type(version) is not int or not 0 <= version <= 2 ** 53 - 1:
        _fail()
    return core.photos.viewer_receipt(token, _id(body['photo_id']), version)


@router.post('/photos/uploads/{capture_id}')
async def upload(capture_id: str, request: Request):
    core = request.app.state.core
    _origin(request)
    _query(request)
    token = _bearer(request)
    capture_id = _id(capture_id)
    types = request.headers.getlist('content-type')
    if len(types) != 1:
        _fail('PHOTO_MEDIA_TYPE', 'Expected image/jpeg', 415)
    body = await _body(request, IMAGE_LIMIT)
    return await core.photos.upload(capture_id, token, body, types[0])
