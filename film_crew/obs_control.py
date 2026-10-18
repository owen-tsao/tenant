"""Small authenticated OBS adapter. Construction/import never connects to OBS.

Use only after the operator releases live setup. Credentials, private camera
URLs and screenshot pixels are deliberately absent from repr and error text.
"""
from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass, field
import base64
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import stat
import struct
import threading
import time
import zlib

from .cameras import CameraManifest, SOURCE_NAMES, validate_manifest


COLLECTION = 'Tenant Film Crew'
SCENES = {'wide': 'WIDE', 'detail': 'OBJECT'}
_MARKER = 'tenant_film_crew_v1'
_SDK_LOCK = threading.RLock()
_SILENT = logging.Logger('tenant.obs.private', logging.CRITICAL + 1)
_SILENT.disabled = True


class ObsError(RuntimeError):
    """Only constant public text is supplied to these exceptions."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CameraSnapshot:
    png: bytes = field(repr=False)
    observed_monotonic: float
    source: str
    request_started_monotonic: float
    source_active: bool
    source_showing: bool
    frame_freshness_verified: bool = False


@contextmanager
def _private_sdk():
    """The installed SDK logs passwords at construction and full RPC bodies.

    Disable just its logger family during synchronous calls; give each created
    client's background logger a permanently silent private Logger instance.
    Restore the application's logger configuration even when a call fails.
    """
    with _SDK_LOCK:
        names = {'obsws_python', 'obsws_python.baseclient', 'obsws_python.reqs',
                 'obsws_python.events', 'obsws_python.baseclient.ObsClient',
                 'obsws_python.reqs.ReqClient', 'obsws_python.events.EventClient'}
        names.update(name for name in logging.Logger.manager.loggerDict
                     if name.startswith('obsws_python.'))
        saved = [(logging.getLogger(name), logging.getLogger(name).disabled) for name in names]
        try:
            for logger, _ in saved:
                logger.disabled = True
            yield
        finally:
            for logger, disabled in saved:
                logger.disabled = disabled


def _quiet_client(client):
    for instance in (client, getattr(client, 'base_client', None)):
        if instance is not None:
            instance.logger = _SILENT


def _replay_unavailable(request, error):
    """Only the SDK's typed 604 response for this read means unavailable.

    An unconfigured OBS replay buffer has no output object. Do not confuse
    arbitrary exceptions, other request errors, or a connection failure with
    an idle output, and never inspect/log the potentially private comment.
    """
    if request != 'GetReplayBufferStatus':
        return False
    try:
        from obsws_python.error import OBSSDKRequestError
    except ImportError:
        return False
    return (type(error) is OBSSDKRequestError and error.req_name == request
            and type(error.code) is int and error.code == 604)


def _password(path):
    try:
        fd = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
                raise ValueError
            value = stream.read(4097).decode('utf-8').rstrip('\r\n')
        if not value or len(value) > 1024 or '\n' in value or '\r' in value:
            raise ValueError
        return value
    except (OSError, ValueError, TypeError, UnicodeError):
        raise ObsError('credentials', 'OBS needs a private local credential file.') from None


def _png(data, width, height):
    """Validate bounded, noninterlaced PNG pixels without another dependency."""
    try:
        prefix = 'data:image/png;base64,'
        if not isinstance(data, str) or not data.startswith(prefix) or len(data) > 6_000_000:
            raise ValueError
        raw = base64.b64decode(data[len(prefix):], validate=True)
        if raw[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError
        pos, header, compressed, ended = 8, None, bytearray(), False
        seen_idat, idat_ended = False, False
        while pos < len(raw):
            if pos + 12 > len(raw):
                raise ValueError
            size, = struct.unpack('>I', raw[pos:pos + 4])
            kind = raw[pos + 4:pos + 8]
            end = pos + 12 + size
            if end > len(raw):
                raise ValueError
            body = raw[pos + 8:pos + 8 + size]
            crc, = struct.unpack('>I', raw[pos + 8 + size:end])
            if zlib.crc32(kind + body) & 0xffffffff != crc:
                raise ValueError
            if header is None and kind != b'IHDR':
                raise ValueError
            if kind == b'IHDR':
                if header is not None or size != 13:
                    raise ValueError
                header = struct.unpack('>IIBBBBB', body)
                w, h, depth, color, compression, filtering, interlace = header
                if (not 1 <= w <= width or not 1 <= h <= height or depth != 8
                        or color not in (0, 2, 4, 6) or compression or filtering or interlace):
                    raise ValueError
            elif kind == b'IDAT':
                if idat_ended:
                    raise ValueError
                seen_idat = True
                compressed.extend(body)
            elif kind == b'IEND':
                if size or not seen_idat or end != len(raw):
                    raise ValueError
                ended = True
            elif kind[:1].isupper() and kind != b'PLTE':
                raise ValueError
            if seen_idat and kind != b'IDAT':
                idat_ended = True
            pos = end
        if not ended or header is None:
            raise ValueError
        w, h, _, color, *_ = header
        stride = 1 + w * {0: 1, 2: 3, 4: 2, 6: 4}[color]
        expected = stride * h
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(compressed, expected + 1)
        if (len(pixels) != expected or not decoder.eof or decoder.unused_data
                or decoder.unconsumed_tail or any(pixels[row * stride] > 4 for row in range(h))):
            raise ValueError
        return raw
    except (ValueError, TypeError, struct.error, zlib.error):
        raise ObsError('snapshot', 'OBS returned an invalid or unsupported PNG snapshot.') from None


class ObsControl:
    def __init__(self, config=None, *, password_file=None, client_factory=None,
                 event_factory=None, authorize=lambda: False, on_override=None,
                 clock=time.monotonic, host='127.0.0.1', port=4455, timeout=3,
                 label_font_size=72):
        if config is not None:
            host, port = config.host, config.port
        if (host not in ('127.0.0.1', 'localhost', '::1') or type(port) is not int
                or not 1024 <= port <= 65535 or not 0 < timeout <= 10
                or type(label_font_size) is not int or not 16 <= label_font_size <= 200):
            raise ObsError('config', 'Invalid local OBS adapter configuration.')
        self._config, self._password_file = config, password_file
        self._client_factory, self._event_factory = client_factory, event_factory
        self._authorize, self._on_override, self._clock = authorize, on_override, clock
        self._host, self._port, self._timeout = host, port, timeout
        self._font_size = label_font_size
        self._client = self._events = None
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._own_scene_events = deque()
        self._configured = False
        self._expected = None
        self._uncertain = False
        self._configuring = False
        self._cut = None
        self.override_event = threading.Event()

    @property
    def manual_override(self):
        return self.override_event.is_set()

    def _latch_override(self):
        if not self.override_event.is_set():
            self.override_event.set()
            if self._on_override:
                try:
                    self._on_override()
                except Exception:
                    pass

    def connect(self):
        with self._lock:
            if self._uncertain:
                raise ObsError('uncertain', 'An uncertain OBS write needs operator review.')
            if self._client is not None:
                return self
            secret = self._config.password if self._config is not None else _password(self._password_file)
            if not isinstance(secret, str) or not secret:
                raise ObsError('credentials', 'OBS authentication is required.')
            try:
                req, events = self._client_factory, self._event_factory
                with _private_sdk():
                    if req is None or events is None:
                        from obsws_python import ReqClient, EventClient
                        req, events = req or ReqClient, events or EventClient
                    self._client = req(host=self._host, port=self._port, password=secret,
                                       timeout=self._timeout, subs=0)
                    _quiet_client(self._client)
                    self._authenticated(self._client)
                    self._events = events(host=self._host, port=self._port, password=secret,
                                          timeout=self._timeout, subs=1 | 2 | 4)
                    _quiet_client(self._events)
                    self._authenticated(self._events)
                    for callback in (self.on_current_program_scene_changed,
                                     self.on_current_scene_collection_changing,
                                     self.on_current_scene_collection_changed,
                                     self.on_exit_started):
                        self._events.callback.register(callback)
            except Exception:
                self.close()
                raise ObsError('connection', 'Cannot establish authenticated local OBS control.') from None
            return self

    @staticmethod
    def _authenticated(client):
        auth = client.base_client.server_hello['d'].get('authentication')
        if not isinstance(auth, dict) or not auth.get('salt') or not auth.get('challenge'):
            raise ValueError

    def close(self):
        with self._lock:
            clients, self._client, self._events = (self._events, self._client), None, None
            for client in clients:
                if client is None:
                    continue
                try:
                    with _private_sdk():
                        worker = getattr(client, 'worker', None)
                        if isinstance(worker, threading.Thread):
                            client.base_client.ws.close()
                            if worker is not threading.current_thread():
                                worker.join(timeout=self._timeout)
                        else:
                            client.disconnect()
                except Exception:
                    pass

    disconnect = close

    def _event_healthy(self):
        worker = getattr(self._events, 'worker', None)
        if worker is None or not worker.is_alive():
            self._latch_override()
            raise ObsError('events', 'OBS event monitoring stopped; automatic cuts are suspended.')

    def _authority(self):
        try:
            allowed = self._authorize() is True
        except Exception:
            allowed = False
        if not allowed:
            raise ObsError('authority', 'Live OBS mutation is not currently authorized.')
        if self._uncertain or self.manual_override:
            raise ObsError('suspended', 'OBS control is suspended for operator review.')
        self._event_healthy()

    def _rpc(self, request, data=None, *, write=False, not_after=None):
        with self._lock:
            if self._client is None:
                raise ObsError('connection', 'Connect to local OBS first.')
            if write:
                self._authority()
            try:
                with _private_sdk():
                    if write:
                        self._authority()
                    if not_after is not None and self._clock() >= not_after:
                        raise ObsError('expired', 'The scene-choice evidence expired before the cut was sent.')
                    result = self._client.send(request, data, raw=True)
                if result is None:
                    result = {}
                if not isinstance(result, dict):
                    raise ValueError
                return result
            except ObsError:
                raise
            except Exception as error:
                if not write and _replay_unavailable(request, error):
                    return {'outputActive': False, 'outputUnavailable': True}
                if write:
                    self._uncertain = True
                    self._latch_override()
                self.close()
                raise ObsError('uncertain' if write else 'request',
                               'OBS write outcome is uncertain; do not replay automatically.' if write
                               else 'OBS request failed; reconnect only after operator review.') from None

    def on_current_program_scene_changed(self, data):
        scene = getattr(data, 'scene_name', None)
        with self._state_lock:
            # Event and request sockets are ordered individually, but an event
            # for cut A may arrive after the request socket has completed B.
            # Consume each outstanding acknowledgement once, in server order.
            if self._own_scene_events and scene == self._own_scene_events[0]:
                self._own_scene_events.popleft()
                return
            unexpected = self._configured and (scene != self._expected or bool(self._own_scene_events))
        if unexpected:
            self._latch_override()

    def on_current_scene_collection_changing(self, data):
        if self._configured and not self._configuring:
            self._latch_override()

    def on_current_scene_collection_changed(self, data):
        if self._configured and not self._configuring:
            self._latch_override()

    def on_exit_started(self, data):
        self._latch_override()

    def discover(self):
        with self._lock:
            collections = self._rpc('GetSceneCollectionList')
            scenes = self._rpc('GetSceneList')
            kinds = self._rpc('GetInputKindList', {'unversioned': False})
            inputs = self._rpc('GetInputList')
            return {'collection': collections.get('currentSceneCollectionName'),
                    'collections': collections.get('sceneCollections', []),
                    'scene': scenes.get('currentProgramSceneName'),
                    'scenes': [item['sceneName'] for item in scenes.get('scenes', [])],
                    'input_kinds': kinds.get('inputKinds', []),
                    'sources': [{'name': item['inputName'], 'kind': item['inputKind']}
                                for item in inputs.get('inputs', [])]}

    def _idle(self):
        for name in ('GetRecordStatus', 'GetStreamStatus', 'GetReplayBufferStatus', 'GetVirtualCamStatus'):
            if self._rpc(name).get('outputActive') is not False:
                raise ObsError('outputs', 'Finish active OBS outputs before film-crew setup.')
        if self._rpc('GetStudioModeEnabled').get('studioModeEnabled') is not False:
            raise ObsError('studio', 'Disable OBS Studio Mode before film-crew control.')

    def _no_capture(self):
        special = self._rpc('GetSpecialInputs')
        if any(special.get(key) is not None for key in ('desktop1', 'desktop2', 'mic1', 'mic2', 'mic3', 'mic4')):
            raise ObsError('audio', 'Disable OBS desktop and microphone inputs before film-crew setup.')

    def configure(self, manifest, *, adopt_empty_owned=False, adopt_verified_owned=False):
        try:
            checked = validate_manifest(manifest.to_private_dict() if isinstance(manifest, CameraManifest) else manifest)
            digest = hashlib.sha256(json.dumps(checked.to_private_dict(), sort_keys=True).encode()).hexdigest()
        except Exception:
            raise ObsError('manifest', 'A valid private two-camera manifest is required.') from None
        with self._lock:
            self._authority()
            self._idle()
            self._no_capture()
            kinds = self._rpc('GetInputKindList', {'unversioned': False}).get('inputKinds', [])
            text_kind = next((kind for kind in ('text_ft2_source_v2', 'text_ft2_source') if kind in kinds), None)
            if 'browser_source' not in kinds or text_kind is None:
                raise ObsError('sources', 'OBS needs its browser and text source plugins.')
            collections = self._rpc('GetSceneCollectionList')
            marker = self._rpc('GetPersistentData', {'realm': 'OBS_WEBSOCKET_DATA_REALM_GLOBAL',
                               'slotName': _MARKER}).get('slotValue')
            expected_marker = {'version': 1, 'collection': COLLECTION, 'manifest_sha256': digest, 'ready': True}
            exists = COLLECTION in collections.get('sceneCollections', [])
            if exists and marker is None and adopt_verified_owned is True:
                # Operator explicitly identifies this run's populated bootstrap.
                # All validation precedes the one ownership-metadata write.
                if collections.get('currentSceneCollectionName') != COLLECTION:
                    raise ObsError('ownership', 'Only the active dedicated collection can be adopted.')
                self._verify_inventory()
                self._verify(checked)
                current = self._rpc('GetCurrentProgramScene').get('currentProgramSceneName')
                if current not in SCENES.values():
                    raise ObsError('setup', 'Select a verified film-crew scene before adopting its setup.')
                self._rpc('SetPersistentData', {'realm': 'OBS_WEBSOCKET_DATA_REALM_GLOBAL',
                          'slotName': _MARKER, 'slotValue': expected_marker}, write=True)
                self._expected = current
                self._configured = True
                return self.observe_program()
            adopt = False
            if exists and marker is None and adopt_empty_owned is True:
                # Explicit operator confirmation of the fresh bootstrap collection.
                # Never adopt a populated collection or switch to inspect another.
                inputs = self._rpc('GetInputList').get('inputs', [])
                scenes = self._rpc('GetSceneList').get('scenes', [])
                adopt = (collections.get('currentSceneCollectionName') == COLLECTION
                         and not inputs and len(scenes) <= 1
                         and not any(item.get('sceneName') in SCENES.values() for item in scenes))
                if adopt:
                    adopt = all(not self._rpc('GetSceneItemList', {'sceneName': item['sceneName']}).get('sceneItems')
                                for item in scenes)
            if exists and marker != expected_marker and not adopt:
                raise ObsError('ownership', 'Existing film-crew collection needs operator ownership review.')
            self._configuring = True
            try:
                if exists and not adopt:
                    if collections.get('currentSceneCollectionName') != COLLECTION:
                        self._rpc('SetCurrentSceneCollection', {'sceneCollectionName': COLLECTION}, write=True)
                    self._no_capture()
                    self._verify(checked)
                else:
                    if not adopt:
                        self._rpc('CreateSceneCollection', {'sceneCollectionName': COLLECTION}, write=True)
                    self._no_capture()
                    self._rpc('SetPersistentData', {'realm': 'OBS_WEBSOCKET_DATA_REALM_GLOBAL',
                              'slotName': _MARKER, 'slotValue': dict(expected_marker, ready=False)}, write=True)
                    self._create(checked, text_kind)
                    self._verify(checked)
                    self._rpc('SetPersistentData', {'realm': 'OBS_WEBSOCKET_DATA_REALM_GLOBAL',
                              'slotName': _MARKER, 'slotValue': expected_marker}, write=True)
                current = self._rpc('GetCurrentProgramScene').get('currentProgramSceneName')
                if current not in SCENES.values():
                    with self._state_lock:
                        self._expected = SCENES['wide']
                        self._own_scene_events.append(self._expected)
                    self._rpc('SetCurrentProgramScene', {'sceneName': self._expected}, write=True)
                    current = self._rpc('GetCurrentProgramScene').get('currentProgramSceneName')
                if current not in SCENES.values():
                    raise ObsError('readback', 'OBS program did not match the requested film-crew scene.')
                self._expected = current
                self._configured = True
            finally:
                self._configuring = False
            return self.observe_program()

    def _create(self, manifest, text_kind):
        video = self._rpc('GetVideoSettings')
        width, height = video['baseWidth'], video['baseHeight']
        if type(width) is not int or type(height) is not int or not 8 <= width <= 8192 or not 8 <= height <= 8192:
            raise ObsError('canvas', 'Unsupported OBS canvas dimensions.')
        for scene in SCENES.values():
            self._rpc('CreateScene', {'sceneName': scene}, write=True)
        for feed in manifest.feeds:
            settings = {'url': feed.view_url, 'width': 1280, 'height': 720,
                        'shutdown': False, 'restart_when_active': False, 'reroute_audio': True,
                        'webpage_control_level': 0,
                        'css': 'body { background: black; margin: 0; overflow: hidden; }'}
            self._rpc('CreateInput', {'sceneName': SCENES['wide'], 'inputName': feed.source_name,
                      'inputKind': 'browser_source', 'inputSettings': settings, 'sceneItemEnabled': True}, write=True)
            self._rpc('CreateSceneItem', {'sceneName': SCENES['detail'], 'sourceName': feed.source_name,
                      'sceneItemEnabled': True}, write=True)
            self._rpc('SetInputMute', {'inputName': feed.source_name, 'inputMuted': True}, write=True)
            self._rpc('SetInputAudioMonitorType', {'inputName': feed.source_name,
                      'monitorType': 'OBS_MONITORING_TYPE_NONE'}, write=True)
        self._cut = self._find_cut()
        for role, scene in SCENES.items():
            items = self._rpc('GetSceneItemList', {'sceneName': scene})['sceneItems']
            for item in items:
                self._rpc('SetSceneItemTransform', {'sceneName': scene, 'sceneItemId': item['sceneItemId'],
                          'sceneItemTransform': {'positionX': 0.0, 'positionY': 0.0, 'alignment': 5,
                          'boundsType': 'OBS_BOUNDS_STRETCH', 'boundsAlignment': 5,
                          'boundsWidth': float(width), 'boundsHeight': float(height)}}, write=True)
                self._rpc('SetSceneItemIndex', {'sceneName': scene, 'sceneItemId': item['sceneItemId'],
                          'sceneItemIndex': 1 if item['sourceName'] == SOURCE_NAMES[role] else 0}, write=True)
            self._rpc('CreateInput', {'sceneName': scene, 'inputName': 'Tenant Film Label ' + scene,
                      'inputKind': text_kind, 'inputSettings': {'text': scene,
                      'font': {'face': 'Arial', 'size': self._font_size, 'flags': 1, 'style': 'Bold'},
                      'color1': 0xffffffff, 'color2': 0xffffffff, 'outline': True,
                      'drop_shadow': True}, 'sceneItemEnabled': True}, write=True)
            label = self._rpc('GetSceneItemList', {'sceneName': scene})['sceneItems']
            item = next(item for item in label if item['sourceName'] == 'Tenant Film Label ' + scene)
            self._rpc('SetSceneItemTransform', {'sceneName': scene, 'sceneItemId': item['sceneItemId'],
                      'sceneItemTransform': {'positionX': 24.0, 'positionY': 24.0, 'alignment': 5}}, write=True)
            self._rpc('SetSceneSceneTransitionOverride', {'sceneName': scene, 'transitionName': self._cut,
                      'transitionDuration': None}, write=True)

    def _find_cut(self):
        transitions = self._rpc('GetSceneTransitionList').get('transitions', [])
        cut = next((item.get('transitionName') for item in transitions if item.get('transitionKind') == 'cut_transition'), None)
        if not isinstance(cut, str) or not cut:
            raise ObsError('transition', 'OBS Cut transition is unavailable.')
        return cut

    def _verify_inventory(self):
        expected_inputs = set(SOURCE_NAMES.values()) | {'Tenant Film Label ' + scene for scene in SCENES.values()}
        inputs = self._rpc('GetInputList').get('inputs', [])
        if len(inputs) != 4 or {item.get('inputName') for item in inputs} != expected_inputs:
            raise ObsError('ownership', 'The populated collection does not match the owned input inventory.')
        scenes = self._rpc('GetSceneList').get('scenes', [])
        extras = [item for item in scenes if item.get('sceneName') not in SCENES.values()]
        if len(extras) > 1 or any(self._rpc('GetSceneItemList', {'sceneName': item['sceneName']}).get('sceneItems')
                                  for item in extras):
            raise ObsError('ownership', 'Only the film-crew scenes and one empty bootstrap scene can be adopted.')

    @staticmethod
    def _camera_position(transform, width, height):
        """Recognize a full-canvas view or its warm copy parked one canvas right.

        OBS reports source-times-scale width separately from its bounds box.
        A stretch box therefore uses boundsWidth/Height, not width/height.
        """
        try:
            keys = ('positionX', 'positionY', 'rotation', 'scaleX', 'scaleY')
            if any(type(transform[key]) not in (int, float) or not math.isfinite(transform[key]) for key in keys):
                raise ValueError
            if (transform.get('alignment') != 5 or abs(transform['positionY']) > .5
                    or abs(transform['rotation']) > .01 or transform['scaleX'] <= 0 or transform['scaleY'] <= 0
                    or any(transform.get(key) != 0 for key in ('cropLeft', 'cropRight', 'cropTop', 'cropBottom'))):
                raise ValueError
            if transform.get('boundsType') == 'OBS_BOUNDS_STRETCH':
                w, h = transform['boundsWidth'], transform['boundsHeight']
            elif transform.get('boundsType') == 'OBS_BOUNDS_NONE':
                w = transform['sourceWidth'] * transform['scaleX']
                h = transform['sourceHeight'] * transform['scaleY']
            else:
                raise ValueError
            if not math.isfinite(w) or not math.isfinite(h) or abs(w - width) > .5 or abs(h - height) > .5:
                raise ValueError
            x = transform['positionX']
            if abs(x) <= .5:
                return 'visible'
            if abs(x - width) <= .5:
                return 'parked'
            raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ObsError('setup', 'The camera scene geometry needs operator review.') from None

    def _verify(self, manifest):
        self._cut = self._find_cut()
        video = self._rpc('GetVideoSettings')
        width, height = video['baseWidth'], video['baseHeight']
        scenes = self._rpc('GetSceneList').get('scenes', [])
        if not set(SCENES.values()) <= {item['sceneName'] for item in scenes}:
            raise ObsError('setup', 'The owned film-crew scenes are incomplete.')
        for feed in manifest.feeds:
            settings = self._rpc('GetInputSettings', {'inputName': feed.source_name})
            value = settings.get('inputSettings', {})
            if (settings.get('inputKind') != 'browser_source' or value.get('url') != feed.view_url
                    or value.get('shutdown') is not False or value.get('restart_when_active') is not False
                    or value.get('reroute_audio') is not True):
                raise ObsError('setup', 'Camera source settings need operator review.')
            muted = self._rpc('GetInputMute', {'inputName': feed.source_name})
            monitor = self._rpc('GetInputAudioMonitorType', {'inputName': feed.source_name})
            if muted.get('inputMuted') is not True or monitor.get('monitorType') != 'OBS_MONITORING_TYPE_NONE':
                raise ObsError('audio', 'Film-crew camera audio settings need operator review.')
        for role, scene in SCENES.items():
            items = self._rpc('GetSceneItemList', {'sceneName': scene}).get('sceneItems', [])
            camera_items = [item for item in items if item.get('sourceName') in SOURCE_NAMES.values()]
            if len(camera_items) != 2 or {item['sourceName'] for item in camera_items} != set(SOURCE_NAMES.values()):
                raise ObsError('setup', 'Both warm camera sources are required in each scene.')
            positions = {item['sourceName']: self._camera_position(self._rpc('GetSceneItemTransform',
                         {'sceneName': scene, 'sceneItemId': item['sceneItemId']})['sceneItemTransform'], width, height)
                         for item in camera_items}
            selected = next(item for item in camera_items if item['sourceName'] == SOURCE_NAMES[role])
            visible = [item for item in camera_items if positions[item['sourceName']] == 'visible']
            top_camera = max(visible, key=lambda item: item['sceneItemIndex']) if visible else None
            if positions[selected['sourceName']] != 'visible' or top_camera is None or top_camera != selected:
                raise ObsError('setup', 'The camera scene stacking order changed; operator review is required.')
            labels = [item for item in items if item.get('sourceName') == 'Tenant Film Label ' + scene]
            if (len(items) != 3 or len(labels) != 1 or labels[0]['sceneItemIndex'] <= top_camera['sceneItemIndex']
                    or self._rpc('GetSceneItemEnabled', {'sceneName': scene,
                        'sceneItemId': labels[0]['sceneItemId']}).get('sceneItemEnabled') is not True):
                raise ObsError('setup', 'The visible film-crew scene label needs operator review.')
            label = self._rpc('GetInputSettings', {'inputName': 'Tenant Film Label ' + scene})
            if (label.get('inputSettings', {}).get('text') != scene
                    or label.get('inputKind') not in ('text_ft2_source', 'text_ft2_source_v2')):
                raise ObsError('setup', 'The film-crew scene label text changed; operator review is required.')
            for item in camera_items:
                enabled = self._rpc('GetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': item['sceneItemId']})
                if enabled.get('sceneItemEnabled') is not True:
                    raise ObsError('setup', 'Both camera sources must remain enabled.')
            override = self._rpc('GetSceneSceneTransitionOverride', {'sceneName': scene})
            if override.get('transitionName') != self._cut:
                raise ObsError('transition', 'Film-crew scenes require an OBS Cut override.')

    def observe_program(self):
        with self._lock:
            collection = self._rpc('GetSceneCollectionList').get('currentSceneCollectionName')
            scene = self._rpc('GetCurrentProgramScene').get('currentProgramSceneName')
            if self._configured and (collection != COLLECTION or scene != self._expected):
                self._latch_override()
            self._event_healthy()
            return {'collection': collection, 'scene': scene, 'expected_scene': self._expected,
                    'override_detected': self.manual_override, 'observed_monotonic': self._clock()}

    status = observe_program

    def switch(self, role, *, not_after=None):
        if not isinstance(role, str) or role not in SCENES:
            raise ObsError('role', 'Unknown camera role.')
        if not_after is not None and (type(not_after) not in (int, float) or not math.isfinite(not_after)):
            raise ObsError('deadline', 'Use a finite monotonic evidence deadline.')
        if not_after is not None and self._clock() >= not_after:
            raise ObsError('expired', 'The scene-choice evidence expired before the cut was sent.')
        with self._lock:
            if not self._configured:
                raise ObsError('setup', 'Configure the owned film-crew scenes first.')
            self.observe_program()
            self._authority()
            if self._rpc('GetStudioModeEnabled').get('studioModeEnabled') is not False:
                self._latch_override()
                raise ObsError('studio', 'OBS Studio Mode changed; automatic cuts are suspended.')
            override = self._rpc('GetSceneSceneTransitionOverride', {'sceneName': SCENES[role]})
            if override.get('transitionName') != self._cut:
                self._latch_override()
                raise ObsError('transition', 'The scene Cut override changed; automatic cuts are suspended.')
            started = self._clock()
            if self._expected == SCENES[role]:
                result = self.observe_program()
                result.update(role=role, request_started_monotonic=started)
                return result
            with self._state_lock:
                previous = self._expected
                self._expected = SCENES[role]
                self._own_scene_events.append(self._expected)
            try:
                self._rpc('SetCurrentProgramScene', {'sceneName': self._expected}, write=True, not_after=not_after)
            except ObsError as error:
                if error.code != 'uncertain':
                    with self._state_lock:
                        if self._own_scene_events and self._own_scene_events[-1] == self._expected:
                            self._own_scene_events.pop()
                        self._expected = previous
                raise
            result = self.observe_program()
            if result['override_detected']:
                raise ObsError('readback', 'OBS program changed during the cut; automatic cuts are suspended.')
            result.update(role=role, request_started_monotonic=started)
            return result

    def snapshot(self, role, width=320, height=180):
        if (not isinstance(role, str) or role not in SOURCE_NAMES or type(width) is not int or type(height) is not int
                or not 8 <= width <= 1024 or not 8 <= height <= 1024):
            raise ObsError('snapshot', 'Use a known camera role and bounded snapshot dimensions.')
        with self._lock:
            if not self._configured:
                raise ObsError('setup', 'Configure the owned film-crew scenes first.')
            collection = self._rpc('GetSceneCollectionList').get('currentSceneCollectionName')
            if collection != COLLECTION:
                self._latch_override()
                raise ObsError('collection', 'The film-crew collection is no longer active.')
            source = SOURCE_NAMES[role]
            active = self._rpc('GetSourceActive', {'sourceName': source})
            started = self._clock()
            result = self._rpc('GetSourceScreenshot', {'sourceName': source, 'imageFormat': 'png',
                               'imageWidth': width, 'imageHeight': height})
            observed = self._clock()
            png = _png(result.get('imageData'), width, height)
            return CameraSnapshot(png, observed, source, started,
                                  active.get('videoActive') is True, active.get('videoShowing') is True)
