"""Private VDO.Ninja setup only: no network, camera, browser or OBS operations.

URLs and QR images grant access to the feeds. Keep the returned objects private;
their repr deliberately omits URLs. Physical camera identity/liveness is unproven.
"""
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import string
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parents[1] / '.venv/tenant-runtime/film-crew'
SOURCE_NAMES = {'wide': 'Tenant Film Wide', 'detail': 'Tenant Film Detail'}
ROLES = tuple(SOURCE_NAMES)
PUSH_OPTIONS = {'webcam': '', 'vdo': 'back', 'audiodevice': '0',
                'width': '1280', 'height': '720', 'maxframerate': '30'}
VIEW_OPTIONS = {'noaudio': '', 'retry': '10', 'retrytimeout': '5000'}
VIEW_CODECS = frozenset({'h264', 'vp8'})
_TOKEN = re.compile(r'[A-Za-z0-9]{24,40}\Z')


class CameraManifestError(ValueError):
    """Messages never include private URLs, passwords or input content."""


@dataclass(frozen=True)
class CameraFeed:
    role: str
    source_name: str
    push_url: str = field(repr=False)
    view_url: str = field(repr=False)

    def to_private_dict(self):
        return {'role': self.role, 'source_name': self.source_name,
                'push_url': self.push_url, 'view_url': self.view_url}


@dataclass(frozen=True)
class CameraManifest:
    feeds: tuple[CameraFeed, ...]

    def feed(self, role):
        for item in self.feeds:
            if item.role == role:
                return item
        raise CameraManifestError('Unknown camera role.')

    def to_private_dict(self):
        return {'schema_version': 1, 'feeds': [feed.to_private_dict() for feed in self.feeds]}


def _url(options):
    return 'https://vdo.ninja/?' + urlencode(options)


def _parse_url(value, direction, options):
    try:
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError
        url = urlsplit(value)
        if url.scheme != 'https' or url.netloc != 'vdo.ninja' or url.path != '/' or url.fragment:
            raise ValueError
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        params = dict(pairs)
        expected = {direction, 'password', *options}
        if direction == 'view' and 'codec' in params:
            if params['codec'] not in VIEW_CODECS:
                raise ValueError
            expected.add('codec')
        if direction == 'view' and 'forceviewerlandscape' in params:
            if params['forceviewerlandscape'] not in {'90', '270'}:
                raise ValueError
            expected.add('forceviewerlandscape')
        if len(params) != len(pairs) or set(params) != expected:
            raise ValueError
        if any(params[key] != value for key, value in options.items()):
            raise ValueError
        if not _TOKEN.fullmatch(params[direction]) or not _TOKEN.fullmatch(params['password']):
            raise ValueError
        return params[direction], params['password']
    except (ValueError, TypeError):
        raise CameraManifestError('Invalid private camera URL or options.') from None


def validate_manifest(value):
    """Validate exact two-feed setup without returning credentials in errors."""
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'feeds'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or not isinstance(value['feeds'], list) or len(value['feeds']) != 2):
        raise CameraManifestError('Expected a version-one two-camera manifest.')
    feeds, stream_ids, passwords, roles = [], set(), set(), set()
    for item in value['feeds']:
        if not isinstance(item, dict) or set(item) != {'role', 'source_name', 'push_url', 'view_url'}:
            raise CameraManifestError('Invalid camera entry.')
        role = item['role']
        if not isinstance(role, str) or role not in SOURCE_NAMES or role in roles:
            raise CameraManifestError('Camera roles must be distinct wide and detail.')
        if item['source_name'] != SOURCE_NAMES[role]:
            raise CameraManifestError('Unexpected OBS camera source name.')
        push = _parse_url(item['push_url'], 'push', PUSH_OPTIONS)
        view = _parse_url(item['view_url'], 'view', VIEW_OPTIONS)
        if push != view or push[0] in stream_ids or push[1] in passwords:
            raise CameraManifestError('Camera identities must match per feed and differ across feeds.')
        stream_ids.add(push[0])
        passwords.add(push[1])
        roles.add(role)
        feeds.append(CameraFeed(**item))
    return CameraManifest(tuple(sorted(feeds, key=lambda feed: ROLES.index(feed.role))))


def _private_read(path):
    """Do not follow symlinks or load publicly readable credential files."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 16384:
                raise CameraManifestError('Camera manifest must be a small private regular file.')
            return source.read(16385)
    except OSError:
        raise CameraManifestError('Cannot read private camera manifest.') from None


def load_manifest(path=DEFAULT_RUNTIME_DIR / 'cameras.json'):
    """Load only; no QR generation, source activation or live-status claim."""
    data = _private_read(Path(path))
    try:
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        value = json.loads(data, object_pairs_hook=unique_keys)
    except (ValueError, UnicodeError):
        raise CameraManifestError('Invalid camera manifest JSON.') from None
    return validate_manifest(value)


def _write_private(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.camera-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as destination:
            destination.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _qr_bytes(url):
    # Existing Tenant development dependency; never use a hosted QR service.
    import qrcode
    image = qrcode.make(url, box_size=8, border=4)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def prepare_manifest(runtime_dir=DEFAULT_RUNTIME_DIR):
    """Create/reuse private identities and local QR PNGs; never contact VDO.Ninja.

    Run once during preparation, not concurrently. Existing invalid manifests
    fail closed rather than silently rotating links already handed to phones.
    """
    runtime = Path(runtime_dir)
    if runtime.is_symlink():
        raise CameraManifestError('Camera runtime directory cannot be a symlink.')
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not runtime.is_dir():
        raise CameraManifestError('Camera runtime directory is unavailable.')
    runtime.chmod(0o700)
    path = runtime / 'cameras.json'
    if path.exists() or path.is_symlink():
        manifest = load_manifest(path)
    else:
        def token(length):
            return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
        entries = []
        for role in ROLES:
            stream_id, password = token(24), token(32)
            entries.append({'role': role, 'source_name': SOURCE_NAMES[role],
                'push_url': _url({'push': stream_id, 'password': password, **PUSH_OPTIONS}),
                'view_url': _url({'view': stream_id, 'password': password, **VIEW_OPTIONS})})
        manifest = validate_manifest({'schema_version': 1, 'feeds': entries})
    # Render before publishing the manifest. All artifacts stay local and private.
    for feed in manifest.feeds:
        _write_private(runtime / (feed.role + '-phone-qr.png'), _qr_bytes(feed.push_url))
    if not path.exists():
        _write_private(path, (json.dumps(manifest.to_private_dict(), indent=2) + '\n').encode())
    return manifest
