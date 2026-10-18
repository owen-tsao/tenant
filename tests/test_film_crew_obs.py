"""Offline OBS protocol tests. Never connect to OBS or access camera devices."""
import base64
import copy
from contextlib import contextmanager
import io
import json
import logging
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch
import zlib

from film_crew.obs_control import ObsControl, ObsError
import film_crew.obs_control as obs_module


PASSWORD = 'PRIVATE-OBS-PASSWORD-NEVER-LOG'
PRIVATE = 'PRIVATECAMERATOKENNEVERLOG0001'


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)


def png(width=2, height=2):
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x80\x40\x20' * width) * height)) + chunk(b'IEND', b''))


def manifest():
    return {'schema_version': 1, 'feeds': [
        {'role': role, 'source_name': 'Tenant Film ' + ('Wide' if role == 'wide' else 'Detail'),
         'push_url': f'https://vdo.ninja/?push={PRIVATE}{index}&password={PRIVATE}{index}p&webcam=&vdo=back&audiodevice=0&width=1280&height=720&maxframerate=30',
         'view_url': f'https://vdo.ninja/?view={PRIVATE}{index}&password={PRIVATE}{index}p&noaudio=&retry=10&retrytimeout=5000'}
        for index, role in enumerate(('wide', 'detail'))]}


class FakeEvents:
    def __init__(self):
        self.base_client = SimpleNamespace(server_hello={'d': {'authentication': {'challenge': 'c', 'salt': 's'}}})
        self.callbacks = []
        self.callback = SimpleNamespace(register=lambda fn: self.callbacks.extend(fn if isinstance(fn, list) else [fn]))
        self.worker = SimpleNamespace(is_alive=lambda: True)
        self.closed = 0

    def disconnect(self):
        self.closed += 1

    def emit(self, callback_name, **data):
        for fn in self.callbacks:
            if fn.__name__ == callback_name:
                fn(SimpleNamespace(**data))


class FakeObs:
    """Stateful raw obs-websocket request/response fake, with no network."""
    def __init__(self):
        self.base_client = SimpleNamespace(server_hello={'d': {'authentication': {'challenge': 'c', 'salt': 's'}}})
        self.calls = []
        self.collections = {'Unrelated': {'scenes': {'Unrelated scene': []}, 'inputs': {}, 'program': 'Unrelated scene'}}
        self.collection = 'Unrelated'
        self.persistent = {}
        self.closed = 0
        self.fail = None
        self.fail_after = None
        self.after_request = None
        self.request_errors = {}
        self.kinds = ['browser_source', 'text_ft2_source_v2']
        self.outputs = dict(record=False, stream=False, replay=False, virtual=False)
        self.screenshot = 'data:image/png;base64,' + base64.b64encode(png()).decode()
        self.active, self.showing = True, True
        self.transitions = {}
        self.special_inputs = {'desktop1': None, 'desktop2': None, 'mic1': None, 'mic2': None, 'mic3': None, 'mic4': None}

    @property
    def state(self):
        return self.collections[self.collection]

    def disconnect(self):
        self.closed += 1

    def send(self, request, data=None, raw=True):
        if not raw:
            raise AssertionError('adapter must use raw protocol responses')
        data = copy.deepcopy(data or {})
        self.calls.append((request, data))
        if request in self.request_errors:
            error = self.request_errors[request]
            logging.getLogger('obsws_python.reqs').error('private request error: %s', error)
            raise error
        if self.fail == request:
            logging.getLogger('obsws_python.reqs').error('private failed request %s %s', PASSWORD, PRIVATE)
            raise RuntimeError(PASSWORD + PRIVATE)
        result = self._dispatch(request, data)
        if self.after_request:
            self.after_request(request, data)
        if self.fail_after == request:
            raise TimeoutError('uncertain response ' + PASSWORD + PRIVATE)
        return result

    def _dispatch(self, request, data):
        if request == 'GetSpecialInputs':
            return copy.deepcopy(self.special_inputs)
        if request == 'GetSceneTransitionList':
            return {'currentSceneTransitionName': 'Cut', 'transitions': [{'transitionName': 'Cut', 'transitionKind': 'cut_transition', 'transitionConfigurable': False}]}
        if request == 'SetSceneSceneTransitionOverride':
            self.transitions[data['sceneName']] = data['transitionName']
            return {}
        if request == 'GetSceneSceneTransitionOverride':
            return {'transitionName': self.transitions.get(data['sceneName'], ''), 'transitionDuration': -1}
        if request == 'GetVersion':
            return {'obsVersion': '32.2.2', 'obsWebSocketVersion': '5.6.3', 'rpcVersion': 1,
                    'availableRequests': []}
        if request == 'GetSceneCollectionList':
            return {'currentSceneCollectionName': self.collection, 'sceneCollections': list(self.collections)}
        if request == 'GetSceneList':
            return {'currentProgramSceneName': self.state['program'], 'scenes': [
                {'sceneName': name, 'sceneIndex': i} for i, name in enumerate(self.state['scenes'])]}
        if request == 'GetInputList':
            return {'inputs': [{'inputName': name, 'inputKind': item['kind'], 'unversionedInputKind': item['kind']}
                               for name, item in self.state['inputs'].items()]}
        if request == 'GetInputKindList':
            return {'inputKinds': list(self.kinds)}
        if request == 'GetPersistentData':
            return {'slotValue': copy.deepcopy(self.persistent.get((data['realm'], data['slotName'])))}
        if request == 'SetPersistentData':
            self.persistent[(data['realm'], data['slotName'])] = copy.deepcopy(data['slotValue'])
            return {}
        if request == 'CreateSceneCollection':
            name = data['sceneCollectionName']
            if name in self.collections:
                raise AssertionError('duplicate collection')
            self.collections[name] = {'scenes': {}, 'inputs': {}, 'program': None}
            self.collection = name
            return {}
        if request == 'SetCurrentSceneCollection':
            self.collection = data['sceneCollectionName']
            return {}
        if request == 'GetCurrentSceneCollection':
            return {'sceneCollectionName': self.collection}
        if request == 'GetCurrentProgramScene':
            return {'currentProgramSceneName': self.state['program']}
        if request == 'SetCurrentProgramScene':
            self.state['program'] = data['sceneName']
            return {}
        if request == 'CreateScene':
            self.state['scenes'][data['sceneName']] = []
            if self.state['program'] is None:
                self.state['program'] = data['sceneName']
            return {}
        if request == 'CreateInput':
            name = data['inputName']
            if name in self.state['inputs']:
                raise AssertionError('duplicate source')
            self.state['inputs'][name] = {'kind': data['inputKind'], 'settings': data['inputSettings'],
                                          'muted': False, 'monitor': None}
            return self.add_item(data['sceneName'], name, data.get('sceneItemEnabled', True))
        if request == 'CreateSceneItem':
            return self.add_item(data['sceneName'], data['sourceName'], data.get('sceneItemEnabled', True))
        if request == 'GetSceneItemList':
            return {'sceneItems': copy.deepcopy(self.state['scenes'][data['sceneName']])}
        if request == 'GetSceneItemEnabled':
            item = self.item(data)
            return {'sceneItemEnabled': item['sceneItemEnabled']}
        if request == 'SetSceneItemEnabled':
            self.item(data)['sceneItemEnabled'] = data['sceneItemEnabled']
            return {}
        if request == 'SetSceneItemIndex':
            items = self.state['scenes'][data['sceneName']]
            item = self.item(data)
            items.remove(item)
            items.insert(data['sceneItemIndex'], item)
            for index, entry in enumerate(items):
                entry['sceneItemIndex'] = index
            return {}
        if request == 'GetSceneItemTransform':
            return {'sceneItemTransform': copy.deepcopy(self.item(data)['transform'])}
        if request == 'SetSceneItemTransform':
            transform = self.item(data)['transform']
            transform.update(data['sceneItemTransform'])
            transform['width'] = transform['sourceWidth'] * transform['scaleX']
            transform['height'] = transform['sourceHeight'] * transform['scaleY']
            return {}
        if request == 'GetInputSettings':
            item = self.state['inputs'][data['inputName']]
            return {'inputSettings': copy.deepcopy(item['settings']), 'inputKind': item['kind']}
        if request == 'SetInputSettings':
            self.state['inputs'][data['inputName']]['settings'].update(data['inputSettings'])
            return {}
        if request == 'GetInputMute':
            return {'inputMuted': self.state['inputs'][data['inputName']]['muted']}
        if request == 'GetInputAudioMonitorType':
            return {'monitorType': self.state['inputs'][data['inputName']]['monitor']}
        if request == 'SetInputMute':
            self.state['inputs'][data['inputName']]['muted'] = data['inputMuted']
            return {}
        if request == 'SetInputAudioMonitorType':
            self.state['inputs'][data['inputName']]['monitor'] = data['monitorType']
            return {}
        if request == 'GetSourceActive':
            return {'videoActive': self.active, 'videoShowing': self.showing}
        if request == 'GetSourceScreenshot':
            return {'imageData': self.screenshot}
        if request == 'GetVideoSettings':
            return {'baseWidth': 1920, 'baseHeight': 1080, 'outputWidth': 1920, 'outputHeight': 1080}
        if request == 'GetRecordStatus':
            return {'outputActive': self.outputs['record'], 'outputPaused': False}
        if request == 'GetStreamStatus':
            return {'outputActive': self.outputs['stream']}
        if request == 'GetReplayBufferStatus':
            return {'outputActive': self.outputs['replay']}
        if request == 'GetVirtualCamStatus':
            return {'outputActive': self.outputs['virtual']}
        if request in ('SetCurrentSceneTransition', 'SetCurrentSceneTransitionDuration'):
            return {}
        if request == 'GetStudioModeEnabled':
            return {'studioModeEnabled': False}
        raise AssertionError('Unsupported fake request: ' + request)

    def add_item(self, scene, name, enabled):
        items = self.state['scenes'][scene]
        next_id = max([item['sceneItemId'] for item in items] + [0]) + 1
        is_label = self.state['inputs'][name]['kind'].startswith('text_ft2_source')
        width, height = (400, 100) if is_label else (1280, 720)
        items.append({'sceneItemId': next_id, 'sourceName': name, 'sceneItemEnabled': enabled,
                      'sceneItemIndex': len(items), 'transform': {
                          'positionX': 0.0, 'positionY': 0.0, 'rotation': 0.0,
                          'scaleX': 1.0, 'scaleY': 1.0, 'alignment': 5,
                          'cropLeft': 0, 'cropRight': 0, 'cropTop': 0, 'cropBottom': 0,
                          'boundsType': 'OBS_BOUNDS_NONE', 'boundsAlignment': 5,
                          'boundsWidth': 0.0, 'boundsHeight': 0.0,
                          'sourceWidth': width, 'sourceHeight': height,
                          'width': float(width), 'height': float(height)}})
        return {'sceneItemId': next_id}

    def item(self, data):
        return next(item for item in self.state['scenes'][data['sceneName']]
                    if item['sceneItemId'] == data['sceneItemId'])


class ObsControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.password = Path(self.temporary) / 'obs-password'
        self.password.write_text(PASSWORD)
        self.password.chmod(0o600)
        self.fake = FakeObs()
        self.factories = []
        self.events = FakeEvents()
        self.event_factories = []
        self.notifications = []
        self.allowed = True
        self.now = 10.0
        def factory(**kwargs):
            self.factories.append(kwargs)
            return self.fake
        def event_factory(**kwargs):
            self.event_factories.append(kwargs)
            return self.events
        self.control = ObsControl(password_file=self.password, client_factory=factory,
                                  event_factory=event_factory,
                                  on_override=lambda: self.notifications.append('override'),
                                  authorize=lambda: self.allowed() if callable(self.allowed) else self.allowed,
                                  clock=lambda: self.now)
        self.addCleanup(self.control.close)

    def configured(self):
        self.control.connect()
        self.control.configure(manifest())
        return self.control

    def writes(self):
        return [(name, data) for name, data in self.fake.calls
                if name.startswith(('Set', 'Create', 'Remove', 'Start', 'Stop', 'Trigger'))]

    def safe_error(self, action):
        with self.assertRaises(ObsError) as caught:
            action()
        text = str(caught.exception) + repr(caught.exception)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(PRIVATE, text)
        self.assertNotIn('https://', text)
        return caught.exception

    def test_connect_is_persistent_and_credentials_not_in_repr(self):
        self.control.connect()
        self.control.discover()
        self.control.discover()
        self.assertEqual(len(self.factories), 1)
        self.assertEqual(self.factories[0]['password'], PASSWORD)
        self.assertEqual(self.factories[0]['subs'], 0)
        self.assertNotIn(PASSWORD, repr(self.control))
        self.control.close()
        self.control.close()
        self.assertEqual(self.fake.closed, 1)
        self.assertEqual(self.events.closed, 1)

    def test_authentication_must_be_enabled(self):
        self.fake.base_client.server_hello = {'d': {}}
        self.safe_error(self.control.connect)
        self.assertEqual(self.fake.closed, 1)
        self.assertFalse(self.writes())

    def test_event_socket_requires_authentication_and_closes_both_connections(self):
        self.events.base_client.server_hello = {'d': {}}
        self.safe_error(self.control.connect)
        self.assertEqual(self.fake.closed, 1)
        self.assertEqual(self.events.closed, 1)
        self.assertFalse(self.writes())

    def test_public_or_missing_password_rejected_before_connect(self):
        self.password.chmod(0o644)
        self.safe_error(self.control.connect)
        self.assertFalse(self.factories)
        self.password.unlink()
        self.safe_error(self.control.connect)
        self.assertFalse(self.factories)

    def test_symlink_password_rejected_before_connect(self):
        original = self.password.with_name('real-private-password')
        self.password.rename(original)
        self.password.symlink_to(original)
        self.safe_error(self.control.connect)
        self.assertFalse(self.factories)

    def test_discovery_is_readonly_and_never_returns_settings(self):
        self.control.connect()
        result = self.control.discover()
        self.assertIn('Unrelated', str(result))
        self.assertFalse(self.writes())
        self.assertNotIn(PRIVATE, repr(result))
        self.assertNotIn('GetInputSettings', [name for name, _ in self.fake.calls])

    def test_default_or_revoked_authority_prevents_every_write(self):
        self.control.connect()
        self.allowed = False
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertFalse(self.writes())

    def test_default_authorization_denies_configuration(self):
        candidate = ObsControl(password_file=self.password,
                               client_factory=lambda **kwargs: self.fake,
                               event_factory=lambda **kwargs: self.events)
        self.addCleanup(candidate.close)
        candidate.connect()
        self.safe_error(lambda: candidate.configure(manifest()))
        self.assertFalse(self.writes())

    def test_revocation_mid_configuration_stops_following_writes(self):
        self.control.connect()
        calls = 0
        def once():
            nonlocal calls
            calls += 1
            return calls <= 1
        self.allowed = once
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertLessEqual(len(self.writes()), 1)

    def test_configuration_preserves_unrelated_and_warms_both_sources(self):
        original = copy.deepcopy(self.fake.collections['Unrelated'])
        self.configured()
        self.assertEqual(self.fake.collection, 'Tenant Film Crew')
        self.assertEqual(self.fake.collections['Unrelated'], original)
        cameras = {name: value for name, value in self.fake.state['inputs'].items()
                   if value['kind'] == 'browser_source'}
        self.assertEqual(len(cameras), 2)
        for item in cameras.values():
            self.assertIs(item['settings']['shutdown'], False)
            self.assertIs(item['settings']['restart_when_active'], False)
            self.assertIs(item['settings']['reroute_audio'], True)
            self.assertIs(item['muted'], True)
            self.assertEqual(item['monitor'], 'OBS_MONITORING_TYPE_NONE')
        self.assertEqual(set(self.fake.state['scenes']), {'WIDE', 'OBJECT'})
        self.assertEqual(self.fake.transitions, {'WIDE': 'Cut', 'OBJECT': 'Cut'})
        self.assertEqual(sum(n == 'GetSceneSceneTransitionOverride' for n, _ in self.fake.calls), 2)
        for items in self.fake.state['scenes'].values():
            camera_items = [item for item in items if item['sourceName'] in cameras]
            self.assertEqual(len(camera_items), 2)
            self.assertTrue(all(item['sceneItemEnabled'] for item in camera_items))
        forbidden = {'StartRecord', 'StartStream', 'StartVirtualCam',
                     'SetInputVolume', 'StopRecord', 'StopStream'}
        self.assertFalse(forbidden & {name for name, _ in self.fake.calls})
        self.assertEqual({v['settings'].get('text') for v in self.fake.state['inputs'].values()
                          if v['kind'].startswith('text_ft2_source')}, {'WIDE', 'OBJECT'})

    def test_identical_reconfigure_makes_no_source_updates(self):
        self.configured()
        self.fake.calls.clear()
        self.control.configure(manifest())
        self.assertFalse(self.writes())

    def test_owned_setup_detects_source_tampering_without_overwriting(self):
        self.configured()
        camera = next(item for item in self.fake.state['inputs'].values()
                      if item['kind'] == 'browser_source')
        camera['settings']['url'] = 'https://example.invalid/private-changed'
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertFalse(self.writes())
        self.assertEqual(camera['settings']['url'], 'https://example.invalid/private-changed')

    def test_reconfigure_refuses_swapped_camera_stacking_without_repair(self):
        self.configured()
        items = self.fake.state['scenes']['WIDE']
        cameras = [item for item in items if item['sourceName'].startswith('Tenant Film ') and 'Label' not in item['sourceName']]
        cameras[0]['sceneItemIndex'], cameras[1]['sceneItemIndex'] = cameras[1]['sceneItemIndex'], cameras[0]['sceneItemIndex']
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertFalse(self.writes())

    def test_reconfigure_refuses_camera_audio_or_label_operator_edits(self):
        self.configured()
        original = copy.deepcopy(self.fake.state)
        for edit in ('mute', 'monitor', 'label-missing', 'label-text'):
            with self.subTest(edit=edit):
                self.fake.collections['Tenant Film Crew'] = copy.deepcopy(original)
                state = self.fake.state
                camera = next(item for item in state['inputs'].values() if item['kind'] == 'browser_source')
                label_name = 'Tenant Film Label WIDE'
                if edit == 'mute':
                    camera['muted'] = False
                elif edit == 'monitor':
                    camera['monitor'] = 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT'
                elif edit == 'label-missing':
                    state['scenes']['WIDE'] = [item for item in state['scenes']['WIDE'] if item['sourceName'] != label_name]
                else:
                    state['inputs'][label_name]['settings']['text'] = 'Wrong label'
                self.fake.calls.clear()
                self.safe_error(lambda: self.control.configure(manifest()))
                self.assertFalse(self.writes())

    def test_unowned_existing_collection_refused(self):
        self.fake.collections['Tenant Film Crew'] = {'scenes': {}, 'inputs': {}, 'program': None}
        self.control.connect()
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertFalse(self.writes())

    def test_explicit_adoption_only_accepts_active_empty_bootstrap_collection(self):
        self.fake.collections['Tenant Film Crew'] = {'scenes': {'Scene': []}, 'inputs': {}, 'program': 'Scene'}
        self.fake.collection = 'Tenant Film Crew'
        self.control.connect()
        result = self.control.configure(manifest(), adopt_empty_owned=True)
        self.assertEqual(result['scene'], 'WIDE')
        self.assertFalse(result['override_detected'])
        self.assertIn('Scene', self.fake.state['scenes'])
        self.assertFalse(any(name == 'CreateSceneCollection' for name, _ in self.fake.calls))
        self.assertTrue(any(name == 'SetPersistentData' for name, _ in self.fake.calls))

    def test_delayed_bootstrap_selection_event_does_not_mask_later_manual_change(self):
        self.fake.collections['Tenant Film Crew'] = {'scenes': {'Scene': []}, 'inputs': {}, 'program': 'Scene'}
        self.fake.collection = 'Tenant Film Crew'
        self.control.connect()
        self.control.configure(manifest(), adopt_empty_owned=True)
        self.control.switch('detail')
        self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
        self.assertFalse(self.control.manual_override)
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.assertFalse(self.control.manual_override)
        self.assertFalse(self.notifications)
        self.fake.state['program'] = 'WIDE'
        self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
        self.assertTrue(self.control.manual_override)
        self.assertEqual(self.notifications, ['override'])
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_explicit_adoption_refuses_nonempty_or_inactive_or_managed_scene(self):
        self.control.connect()
        cases = [
            ({'scenes': {'Scene': []}, 'inputs': {}, 'program': 'Scene'}, 'Unrelated'),
            ({'scenes': {'WIDE': []}, 'inputs': {}, 'program': 'WIDE'}, 'Tenant Film Crew'),
            ({'scenes': {'Scene': [{'sourceName': 'Unrelated source', 'sceneItemId': 1}]},
              'inputs': {}, 'program': 'Scene'}, 'Tenant Film Crew'),
            ({'scenes': {'Scene': []}, 'inputs': {'Unrelated source': {'kind': 'browser_source'}},
              'program': 'Scene'}, 'Tenant Film Crew'),
            ({'scenes': {'Scene': [], 'Other scene': []}, 'inputs': {}, 'program': 'Scene'}, 'Tenant Film Crew')]
        for index, (state, active) in enumerate(cases):
            with self.subTest(case=index):
                self.fake.collections['Tenant Film Crew'] = copy.deepcopy(state)
                self.fake.collection = active
                self.fake.calls.clear()
                self.safe_error(lambda: self.control.configure(manifest(), adopt_empty_owned=True))
                self.assertFalse(self.writes())
                self.assertEqual(self.fake.collections['Tenant Film Crew'], state)

    def test_explicit_adoption_never_replaces_foreign_ownership_marker(self):
        self.fake.collections['Tenant Film Crew'] = {'scenes': {'Scene': []}, 'inputs': {}, 'program': 'Scene'}
        self.fake.collection = 'Tenant Film Crew'
        self.fake.persistent[('OBS_WEBSOCKET_DATA_REALM_GLOBAL', 'tenant_film_crew_v1')] = {'version': 999}
        self.control.connect()
        self.safe_error(lambda: self.control.configure(manifest(), adopt_empty_owned=True))
        self.assertFalse(self.writes())

    def prepared_without_marker(self, parked=False):
        self.configured()
        self.fake.persistent.clear()
        self.fake.state['scenes']['Scene'] = []
        self.fake.state['program'] = 'OBJECT'
        if parked:
            for role, scene in [('wide', 'WIDE'), ('detail', 'OBJECT')]:
                for item in self.fake.state['scenes'][scene]:
                    if item['sourceName'] in ('Tenant Film Wide', 'Tenant Film Detail'):
                        selected = item['sourceName'] == ('Tenant Film Wide' if role == 'wide' else 'Tenant Film Detail')
                        item['transform']['positionX'] = 0.0 if selected else 1920.0
        self.fake.calls.clear()

    def test_verified_adoption_only_writes_ready_marker_preserving_program_and_sources(self):
        for parked in (False, True):
            with self.subTest(parked=parked):
                self.prepared_without_marker(parked=parked)
                before = copy.deepcopy(self.fake.state)
                result = self.control.configure(manifest(), adopt_verified_owned=True)
                self.assertEqual(self.fake.state, before)
                self.assertEqual(result['scene'], 'OBJECT')
                writes = self.writes()
                self.assertEqual([name for name, _ in writes], ['SetPersistentData'])
                self.assertIs(writes[0][1]['slotValue']['ready'], True)
                self.assertNotIn(PRIVATE, repr(writes[0]))

    def test_verified_adoption_refuses_foreign_marker_input_scene_and_settings(self):
        self.prepared_without_marker(parked=True)
        original = copy.deepcopy(self.fake.state)
        cases = ('foreign-marker', 'extra-input', 'extra-nonempty-scene', 'url', 'geometry',
                 'stack', 'audio', 'label', 'disabled-camera', 'crop', 'rotation', 'mirrored',
                 'current-default-scene', 'wrong-active-collection')
        for edit in cases:
            with self.subTest(edit=edit):
                self.fake.collections['Tenant Film Crew'] = copy.deepcopy(original)
                self.fake.collection = 'Tenant Film Crew'
                self.fake.persistent.clear()
                state = self.fake.state
                camera = state['inputs']['Tenant Film Wide']
                items = state['scenes']['WIDE']
                selected = next(item for item in items if item['sourceName'] == 'Tenant Film Wide')
                other = next(item for item in items if item['sourceName'] == 'Tenant Film Detail')
                if edit == 'foreign-marker':
                    self.fake.persistent[('OBS_WEBSOCKET_DATA_REALM_GLOBAL', 'tenant_film_crew_v1')] = {'foreign': True}
                elif edit == 'extra-input':
                    state['inputs']['Unrelated'] = {'kind': 'browser_source', 'settings': {}}
                elif edit == 'extra-nonempty-scene':
                    state['scenes']['Other'] = [copy.deepcopy(selected)]
                elif edit == 'url':
                    camera['settings']['url'] = 'https://example.invalid/private-changed'
                elif edit == 'geometry':
                    selected['transform']['positionX'] = 50.0
                elif edit == 'stack':
                    # Covered layout must show the selected camera above the other.
                    other['transform']['positionX'] = 0.0
                    selected['sceneItemIndex'], other['sceneItemIndex'] = other['sceneItemIndex'], selected['sceneItemIndex']
                elif edit == 'audio':
                    camera['muted'] = False
                elif edit == 'label':
                    state['inputs']['Tenant Film Label WIDE']['settings']['text'] = 'Wrong'
                elif edit == 'disabled-camera':
                    other['sceneItemEnabled'] = False
                elif edit == 'crop':
                    selected['transform']['cropLeft'] = 40
                elif edit == 'rotation':
                    selected['transform']['rotation'] = 30.0
                elif edit == 'mirrored':
                    selected['transform']['scaleX'] = -1.0
                elif edit == 'current-default-scene':
                    state['program'] = 'Scene'
                else:
                    self.fake.collection = 'Unrelated'
                self.fake.calls.clear()
                before = copy.deepcopy(self.fake.collections)
                self.safe_error(lambda: self.control.configure(manifest(), adopt_verified_owned=True))
                self.assertFalse(self.writes())
                self.assertEqual(self.fake.collections, before)

    def test_missing_source_kind_refuses_before_mutation(self):
        self.fake.kinds = ['browser_source']
        self.control.connect()
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertFalse(self.writes())

    def test_active_outputs_refuse_before_mutation(self):
        for kind in self.fake.outputs:
            with self.subTest(output=kind):
                self.fake.outputs[kind] = True
                self.control.connect()
                self.safe_error(lambda: self.control.configure(manifest()))
                self.assertFalse(self.writes())
                self.fake.outputs[kind] = False

    def test_enabled_desktop_or_microphone_input_refuses_before_mutation(self):
        self.fake.special_inputs['mic1'] = 'Unrelated microphone'
        self.control.connect()
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertFalse(self.writes())

    def test_bad_manifest_refuses_without_mutation_and_without_leaks(self):
        self.control.connect()
        cases = [None, {}, {'schema_version': 1, 'feeds': []}]
        for role, value in [('wide', 'http://vdo.ninja/?view=' + PRIVATE),
                            ('wide', 'https://user:password@vdo.ninja/?view=' + PRIVATE),
                            ('third', 'https://vdo.ninja/?view=' + PRIVATE + '&noaudio')]:
            item = manifest()
            item['feeds'][0].update(role=role, view_url=value)
            cases.append(item)
        duplicate = manifest()
        duplicate['feeds'][1]['role'] = 'wide'
        cases.append(duplicate)
        for value in cases:
            with self.subTest(case=cases.index(value)):
                self.safe_error(lambda: self.control.configure(value))
                self.assertFalse(self.writes())

    def test_switch_is_single_hard_cut_with_readback(self):
        self.configured()
        self.fake.calls.clear()
        self.control.switch('detail')
        self.assertEqual(len([n for n, _ in self.fake.calls if n == 'SetCurrentProgramScene']), 1)
        names = [n for n, _ in self.fake.calls]
        self.assertIn('GetCurrentProgramScene', names)
        self.assertLess(names.index('SetCurrentProgramScene'), len(names) - 1)
        self.assertNotIn('TriggerStudioModeTransition', names)

    def test_own_switch_event_does_not_trigger_manual_override(self):
        self.configured()
        def event(request, data):
            if request == 'SetCurrentProgramScene':
                self.events.emit('on_current_program_scene_changed', scene_name=data['sceneName'])
        self.fake.after_request = event
        result = self.control.switch('detail')
        self.assertEqual(result['scene'], 'OBJECT')
        self.assertFalse(result['override_detected'])
        self.assertFalse(self.control.manual_override)
        self.assertFalse(self.notifications)

    def test_delayed_own_cut_events_are_consumed_in_order_without_false_override(self):
        self.configured()
        self.control.switch('detail')
        self.control.switch('wide')
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.assertFalse(self.control.manual_override)
        self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
        self.assertFalse(self.control.manual_override)
        self.assertFalse(self.notifications)

    def test_manual_back_selection_after_own_events_drained_still_latches(self):
        self.configured()
        self.control.switch('detail')
        self.control.switch('wide')
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
        self.fake.state['program'] = 'OBJECT'
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.assertTrue(self.control.manual_override)
        self.assertEqual(self.notifications, ['override'])
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('wide'))
        self.assertFalse(self.writes())

    def test_unexpected_event_during_pending_cut_acknowledgements_latches(self):
        self.configured()
        self.control.switch('detail')
        self.control.switch('wide')
        self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
        self.assertTrue(self.control.manual_override)
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_same_current_role_is_readonly_noop_without_awaiting_an_event(self):
        self.configured()
        self.fake.calls.clear()
        result = self.control.switch('wide')
        self.assertEqual(result['scene'], 'WIDE')
        self.assertFalse(self.writes())
        self.control.switch('detail')
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.assertFalse(self.control.manual_override)

    def test_cut_deadline_expired_during_preflight_never_sends_or_poisons_control(self):
        self.configured()
        self.fake.calls.clear()
        def slow_preflight(request, data):
            if request == 'GetSceneSceneTransitionOverride':
                self.now = 12.0
        self.fake.after_request = slow_preflight
        error = self.safe_error(lambda: self.control.switch('detail', not_after=11.0))
        self.assertEqual(error.code, 'expired')
        self.assertFalse(self.writes())
        self.assertEqual(self.fake.closed, 0)
        self.assertFalse(self.control.manual_override)
        status = self.control.status()
        self.assertEqual((status['scene'], status['expected_scene']), ('WIDE', 'WIDE'))
        self.fake.after_request = None
        self.control.switch('detail')
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.control.switch('wide')
        self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
        self.assertFalse(self.control.manual_override)

    def test_cut_deadline_rejects_invalid_values_without_sending(self):
        self.configured()
        for deadline in (True, False, float('nan'), float('inf'), -float('inf'), '11', [], {}):
            with self.subTest(deadline=repr(deadline)):
                self.fake.calls.clear()
                self.safe_error(lambda: self.control.switch('detail', not_after=deadline))
                self.assertFalse(self.writes())
                self.assertEqual(self.fake.closed, 0)
                self.assertFalse(self.control.manual_override)

    def test_cut_with_unexpired_finite_monotonic_deadline_sends_once(self):
        self.configured()
        self.fake.calls.clear()
        result = self.control.switch('detail', not_after=11.0)
        self.assertEqual(result['scene'], 'OBJECT')
        self.assertEqual(sum(name == 'SetCurrentProgramScene' for name, _ in self.fake.calls), 1)
        self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
        self.fake.calls.clear()
        result = self.control.switch('wide', not_after=20)
        self.assertEqual(result['scene'], 'WIDE')
        self.assertEqual(sum(name == 'SetCurrentProgramScene' for name, _ in self.fake.calls), 1)

    def assert_pre_send_lock_wait_invalidation(self, manual_override):
        self.configured()
        self.fake.calls.clear()
        original = obs_module._private_sdk
        fired = False
        @contextmanager
        def delayed_lock():
            nonlocal fired
            with original():
                if (not fired and self.fake.calls
                        and self.fake.calls[-1][0] == 'GetSceneSceneTransitionOverride'):
                    fired = True
                    if manual_override:
                        self.events.emit('on_current_program_scene_changed', scene_name='Operator scene')
                    else:
                        self.allowed = False
                yield
        with patch.object(obs_module, '_private_sdk', delayed_lock):
            error = self.safe_error(lambda: self.control.switch('detail'))
        self.assertTrue(fired)
        self.assertEqual(error.code, 'suspended' if manual_override else 'authority')
        self.assertFalse(self.writes())
        self.assertEqual(self.fake.closed, 0)
        status = self.control.status()
        self.assertEqual((status['scene'], status['expected_scene']), ('WIDE', 'WIDE'))
        if not manual_override:
            self.allowed = True
            self.control.switch('detail')
            self.events.emit('on_current_program_scene_changed', scene_name='OBJECT')
            self.control.switch('wide')
            self.events.emit('on_current_program_scene_changed', scene_name='WIDE')
            self.assertFalse(self.control.manual_override)

    def test_authorization_revoked_during_sdk_lock_wait_prevents_cut(self):
        self.assert_pre_send_lock_wait_invalidation(manual_override=False)

    def test_manual_override_during_sdk_lock_wait_prevents_cut(self):
        self.assert_pre_send_lock_wait_invalidation(manual_override=True)

    def sdk_error_module(self):
        module = ModuleType('obsws_python.error')
        class OBSSDKRequestError(Exception):
            def __init__(self, req_name, code, comment):
                self.req_name, self.code = req_name, code
                super().__init__(f'Request {req_name} returned code {code}. With message: {comment}')
        class OBSSDKTimeoutError(Exception):
            pass
        module.OBSSDKRequestError = OBSSDKRequestError
        module.OBSSDKTimeoutError = OBSSDKTimeoutError
        return module

    def test_exact_typed_replay_unavailable_allows_configure_and_verified_adoption(self):
        errors = self.sdk_error_module()
        error = errors.OBSSDKRequestError('GetReplayBufferStatus', 604, PASSWORD + PRIVATE)
        self.fake.request_errors['GetReplayBufferStatus'] = error
        with patch.dict(sys.modules, {'obsws_python.error': errors}):
            self.configured()
            self.assertEqual(self.fake.closed, 0)
            self.fake.persistent.clear()
            self.fake.calls.clear()
            result = self.control.configure(manifest(), adopt_verified_owned=True)
            self.assertEqual(result['scene'], 'WIDE')
            self.assertEqual([name for name, _ in self.writes()], ['SetPersistentData'])
            self.assertEqual(self.fake.closed, 0)

    def test_replay_unavailable_never_masks_other_errors_or_ducktyped_codes(self):
        errors = self.sdk_error_module()
        class DuckError(Exception):
            req_name, code = 'GetReplayBufferStatus', 604
        class SubclassError(errors.OBSSDKRequestError):
            pass
        cases = [
            ('GetReplayBufferStatus', errors.OBSSDKRequestError('GetReplayBufferStatus', 600, PRIVATE)),
            ('GetReplayBufferStatus', errors.OBSSDKRequestError('GetReplayBufferStatus', '604', PRIVATE)),
            ('GetReplayBufferStatus', errors.OBSSDKRequestError('GetReplayBufferStatus', True, PRIVATE)),
            ('GetRecordStatus', errors.OBSSDKRequestError('GetRecordStatus', 604, PRIVATE)),
            ('GetReplayBufferStatus', errors.OBSSDKRequestError('GetStreamStatus', 604, PRIVATE)),
            ('GetReplayBufferStatus', DuckError(PRIVATE)),
            ('GetReplayBufferStatus', RuntimeError('604 ' + PRIVATE)),
            ('GetReplayBufferStatus', errors.OBSSDKTimeoutError(PASSWORD + PRIVATE)),
            ('GetReplayBufferStatus', SubclassError('GetReplayBufferStatus', 604, PRIVATE))]
        with patch.dict(sys.modules, {'obsws_python.error': errors}):
            for index, (request, error) in enumerate(cases):
                with self.subTest(case=index):
                    fake, events = FakeObs(), FakeEvents()
                    fake.request_errors[request] = error
                    control = ObsControl(password_file=self.password,
                                         client_factory=lambda **kwargs: fake,
                                         event_factory=lambda **kwargs: events,
                                         authorize=lambda: True)
                    self.addCleanup(control.close)
                    control.connect()
                    caught = self.safe_error(lambda: control.configure(manifest()))
                    self.assertEqual(caught.code, 'request')
                    self.assertEqual(fake.closed, 1)
                    self.assertFalse(any(name.startswith(('Set', 'Create')) for name, _ in fake.calls))

    def test_typed_replay_unavailable_comment_is_not_logged(self):
        errors = self.sdk_error_module()
        self.fake.request_errors['GetReplayBufferStatus'] = errors.OBSSDKRequestError(
            'GetReplayBufferStatus', 604, PASSWORD + PRIVATE)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger('obsws_python')
        previous = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, previous)
        with patch.dict(sys.modules, {'obsws_python.error': errors}):
            self.configured()
        self.assertNotIn(PRIVATE, stream.getvalue())
        self.assertNotIn(PASSWORD, stream.getvalue())

    def test_manual_override_latches_and_blocks_automatic_switch(self):
        self.configured()
        expected = self.fake.state['program']
        self.fake.state['program'] = 'Unrelated manually selected scene'
        self.control.observe_program()
        self.fake.state['program'] = expected
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())
        self.assertTrue(self.control.manual_override)
        self.assertTrue(self.control.override_event.is_set())

    def test_manual_scene_event_latches_without_waiting_for_poll(self):
        self.configured()
        self.events.emit('on_current_program_scene_changed', scene_name='Unexpected scene')
        self.assertTrue(self.control.override_event.is_set())
        self.assertTrue(self.control.manual_override)
        self.assertEqual(self.notifications, ['override'])
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_event_collection_change_cancels_without_polling(self):
        self.configured()
        self.events.emit('on_current_scene_collection_changing')
        self.assertTrue(self.control.override_event.is_set())
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_event_listener_loss_blocks_future_switch(self):
        self.configured()
        self.events.worker.is_alive = lambda: False
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_collection_change_blocks_switch(self):
        self.configured()
        self.fake.collection = 'Unrelated'
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_uncertain_switch_is_not_replayed(self):
        self.configured()
        self.fake.fail_after = 'SetCurrentProgramScene'
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertEqual(sum(n == 'SetCurrentProgramScene' for n, _ in self.fake.calls), 1)
        self.assertEqual(self.fake.closed, 1)

    def test_authority_revoked_after_setup_blocks_switch(self):
        self.configured()
        self.allowed = False
        self.fake.calls.clear()
        self.safe_error(lambda: self.control.switch('detail'))
        self.assertFalse(self.writes())

    def test_uncertain_setup_never_automatically_replays_creation(self):
        self.control.connect()
        self.fake.fail_after = 'CreateInput'
        self.safe_error(lambda: self.control.configure(manifest()))
        self.assertEqual(sum(n == 'CreateInput' for n, _ in self.fake.calls), 1)

    def test_snapshot_reports_observation_without_claiming_frame_freshness(self):
        self.configured()
        self.now = 22.5
        shot = self.control.snapshot('wide', width=320, height=180)
        self.assertEqual(shot.png, png())
        self.assertEqual(shot.observed_monotonic, 22.5)
        self.assertEqual(shot.request_started_monotonic, 22.5)
        self.assertTrue(shot.source_active)
        self.assertTrue(shot.source_showing)
        self.assertFalse(shot.frame_freshness_verified)
        request = [data for name, data in self.fake.calls if name == 'GetSourceScreenshot'][-1]
        self.assertEqual((request['imageFormat'], request['imageWidth'], request['imageHeight']),
                         ('png', 320, 180))
        self.assertNotIn(base64.b64encode(png()).decode(), repr(shot))
        self.assertNotIn(repr(png()), repr(shot))

    def test_inactive_source_observation_is_not_camera_liveness_claim(self):
        self.configured()
        self.fake.active, self.fake.showing = False, False
        shot = self.control.snapshot('detail')
        self.assertFalse(shot.source_active)
        self.assertFalse(shot.source_showing)
        self.assertFalse(shot.frame_freshness_verified)

    def test_malformed_or_corrupt_snapshot_rejected_safely(self):
        self.configured()
        data = png()
        corrupt = bytearray(data)
        corrupt[40] ^= 1
        cases = [None, '', 'data:image/jpeg;base64,' + base64.b64encode(data).decode(),
                 'data:image/png;base64,not@@base64',
                 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n').decode(),
                 'data:image/png;base64,' + base64.b64encode(corrupt).decode(),
                 'data:image/png;base64,' + base64.b64encode(data + b'private trailing data').decode()]
        for value in cases:
            with self.subTest(case=cases.index(value)):
                self.fake.screenshot = value
                self.safe_error(lambda: self.control.snapshot('wide'))

    def test_png_with_valid_crc_but_bad_structure_or_inflate_is_rejected(self):
        self.configured()
        signature = b'\x89PNG\r\n\x1a\n'
        header = chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
        end = chunk(b'IEND', b'')
        cases = [signature + header + chunk(b'IDAT', b'not-zlib') + end,
                 signature + header + chunk(b'IDAT', zlib.compress(b'too-short')) + end,
                 signature + header + end,
                 signature + chunk(b'IHDR', struct.pack('>IIBBBBB', 100000, 100000, 8, 2, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(b'')) + end,
                 signature + header + header + chunk(b'IDAT', zlib.compress(b'')) + end]
        for data in cases:
            with self.subTest(case=cases.index(data)):
                self.fake.screenshot = 'data:image/png;base64,' + base64.b64encode(data).decode()
                self.safe_error(lambda: self.control.snapshot('wide'))

    def test_request_dimensions_and_roles_rejected_before_screenshot(self):
        self.configured()
        for args in [('third', 320, 180), ('wide', 0, 180), ('wide', True, 180),
                     ('wide', 320, -1), ('wide', 100000, 100000)]:
            with self.subTest(args=args):
                self.fake.calls.clear()
                self.safe_error(lambda: self.control.snapshot(args[0], width=args[1], height=args[2]))
                self.assertNotIn('GetSourceScreenshot', [name for name, _ in self.fake.calls])

    def test_sdk_constructor_failure_restores_logging_and_hides_credentials(self):
        stream = io.StringIO()
        logger = logging.getLogger('obsws_python.baseclient')
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        previous = logger.level, logger.disabled
        logger.setLevel(logging.DEBUG)
        logger.disabled = False
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, previous[0])
        self.addCleanup(setattr, logger, 'disabled', previous[1])
        def fail_factory(**kwargs):
            logger.error('private constructor %s %s', kwargs['password'], PRIVATE)
            raise RuntimeError(PASSWORD + PRIVATE)
        candidate = ObsControl(password_file=self.password, client_factory=fail_factory,
                               event_factory=lambda **kwargs: self.events)
        self.addCleanup(candidate.close)
        self.safe_error(candidate.connect)
        self.assertEqual(stream.getvalue(), '')
        self.assertFalse(logger.disabled)
        self.assertFalse(self.fake.calls)

    def test_sdk_request_log_and_error_cannot_disclose_secrets(self):
        self.control.connect()
        self.fake.fail = 'GetSceneList'
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger('obsws_python')
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, previous)
        self.safe_error(self.control.discover)
        self.assertNotIn(PASSWORD, stream.getvalue())
        self.assertNotIn(PRIVATE, stream.getvalue())


if __name__ == '__main__':
    unittest.main()
