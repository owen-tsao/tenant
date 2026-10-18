"""Photo readiness diagnostics with real core objects and inert device transport.

No browser, model, network, camera, service process or physical device is used.
"""
import asyncio
from contextlib import suppress
import copy
import json
from types import SimpleNamespace
import unittest

from brain.core.bus import Bus
from brain.core.device_metadata import MAX_AGE, update_metadata
from brain.core.leases import Leases
from brain.core.photos import CAPTURE_ARGS, Image, PhotoError, PhotoService
from brain.core.registry import Registry
from brain.state import Room


class DiagnosticSocket:
    def __init__(self):
        self.frames = []
        self.queue = asyncio.Queue()

    async def send_json(self, frame):
        self.frames.append(frame)
        self.queue.put_nowait(frame)


class PhotoReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now, self.mono = 2000.0, 500.0
        self.registry = Registry(Room("TEST", "Photo diagnostics room"))
        self.registry.metadata.clock = lambda: self.now
        self.registry.metadata.monotonic = lambda: self.mono
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.lease = self.leases.create(scopes={"camera.capture", "photo.show"})
        self.leases.current(self.lease.guest_id, activate=True)
        self.controller_allowed = self.source_allowed = True
        self.generation = 11
        self.service = PhotoService(self.registry, self.bus, self.leases,
            authority=lambda lease, generation: self.controller_allowed and lease is self.lease and generation == self.generation,
            source_allowed=lambda source: self.source_allowed)
        self.registry.metadata.camera_ready = self.service.camera_ready
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task

    def enroll_source(self, *, device_id="phone", args=None):
        socket = DiagnosticSocket()
        device = self.registry.register({"type": "hello", "id": device_id, "label": "Whiteboard phone",
            "room": "TEST", "caps": {"camera.capture": {"description": "One opted-in still",
                "args": copy.deepcopy(CAPTURE_ARGS if args is None else args)}}}, socket)
        device.last_seen = self.mono
        return device

    def opt_in(self, source, *, enabled=True, ready=True):
        return self.service.device_event(source, {"type": "photo.consent", "enabled": enabled, "ready": ready})

    def ready_room(self):
        source = self.enroll_source()
        self.service.configure(source.id, "mac-main")
        self.opt_in(source)
        viewer_token = self.service.enroll_viewer("mac-main")
        return source, viewer_token

    def metadata_update(self, source, **body):
        core = SimpleNamespace(registry=self.registry,
            config=SimpleNamespace(host_token="host-private", device_token="device-private"),
            agent=SimpleNamespace(private_values=()))
        return update_metadata(core, source.id, body)

    def inventory(self, lease=None):
        return self.service.inventory(self.lease if lease is None else lease, generation=self.generation)

    def assert_guest_blocked(self, reason, *, lease=None):
        result = self.inventory(lease)
        self.assertFalse(result["ready"])
        self.assertIsNone(result["source_device_id"])
        self.assertIsNone(result["source_label"])
        self.assertEqual(result["reason"], reason)
        self.assertIsInstance(result["message"], str)
        self.assertTrue(result["message"].strip())
        return result

    async def test_default_configuration_has_no_phantom_source_or_viewer(self):
        configuration = self.service.configuration()
        self.assertEqual(set(configuration), {"ok", "enabled", "source_device_id", "viewer_id", "source", "viewer",
                                              "ready", "pending", "blockers"})
        self.assertTrue(configuration["ok"])
        self.assertFalse(configuration["enabled"])
        self.assertIsNone(configuration["source_device_id"])
        self.assertIsNone(configuration["viewer_id"])
        self.assertFalse(any(configuration["source"].values()))
        self.assertEqual(configuration["viewer"], {"enrolled": False, "online": False})
        self.assertEqual(configuration["blockers"], ["DISABLED", "SOURCE_UNSELECTED", "VIEWER_UNSELECTED"])
        self.assertFalse(configuration["ready"])
        self.assertFalse(configuration["pending"])
        self.assert_guest_blocked("DISABLED")
        self.assertEqual(self.registry.devices, {})
        self.assertEqual(self.registry.enrollments, {})
        self.assertEqual(self.service.consents, {})
        self.assertIsNone(self.service.viewer)

    async def test_ready_configuration_exposes_only_host_facts_and_guest_selected_source(self):
        source, _ = self.ready_room()
        configuration = self.service.configuration()
        self.assertEqual(configuration["source_device_id"], source.id)
        self.assertEqual(configuration["viewer_id"], "mac-main")
        self.assertEqual(configuration["source"], {"enrolled": True, "online": True, "host_allowed": True,
            "capture_advertised": True, "consent_enabled": True, "camera_ready": True})
        self.assertEqual(configuration["viewer"], {"enrolled": True, "online": True})
        self.assertTrue(configuration["ready"])
        self.assertEqual(configuration["blockers"], [])
        result = self.inventory()
        self.assertTrue(result["ready"])
        self.assertEqual((result["source_device_id"], result["source_label"]), (source.id, source.label))
        self.assertIsNone(result["reason"])
        self.assertEqual(source.ws.frames, [])

    async def test_configuration_requires_exact_advertised_capture_argument_schema(self):
        source, _ = self.ready_room()
        schemas = ({}, {"capture_id": {"type": "string"}},
                   dict(CAPTURE_ARGS, extra={"type": "string"}),
                   dict(CAPTURE_ARGS, upload_token={"type": "integer"}))
        for schema in schemas:
            with self.subTest(schema=schema):
                source.caps["camera.capture"].args = copy.deepcopy(schema)
                configuration = self.service.configuration()
                self.assertFalse(configuration["source"]["capture_advertised"])
                self.assertIn("CAPTURE_UNAVAILABLE", configuration["blockers"])
                self.assert_guest_blocked("CAPTURE_UNAVAILABLE")
        source.caps.pop("camera.capture")
        self.assertIn("CAPTURE_UNAVAILABLE", self.service.configuration()["blockers"])
        self.assertEqual(source.ws.frames, [])

    async def test_consent_and_camera_readiness_remain_explicit_on_exact_source_socket(self):
        source, _ = self.ready_room()
        self.service.consents.clear()
        configuration = self.service.configuration()
        self.assertFalse(configuration["source"]["consent_enabled"])
        self.assertFalse(configuration["source"]["camera_ready"])
        self.assert_guest_blocked("PHOTO_CONSENT_REQUIRED")
        self.opt_in(source, ready=False)
        configuration = self.service.configuration()
        self.assertTrue(configuration["source"]["consent_enabled"])
        self.assertFalse(configuration["source"]["camera_ready"])
        self.assert_guest_blocked("CAMERA_UNREADY")
        self.opt_in(source)
        original_socket = source.ws
        source.ws = DiagnosticSocket()
        self.assert_guest_blocked("PHOTO_CONSENT_REQUIRED")
        self.assertFalse(self.service.configuration()["source"]["consent_enabled"])
        self.opt_in(source)
        self.assertTrue(self.service.configuration()["ready"])
        self.assertEqual(original_socket.frames, [])
        self.assertEqual(source.ws.frames, [])

    async def test_reconnected_source_requires_new_consent_and_real_fresh_binding(self):
        original, _ = self.ready_room()
        self.registry.offline(original)
        replacement = self.enroll_source()
        self.assertIsNot(original, replacement)
        self.assert_guest_blocked("PHOTO_CONSENT_REQUIRED")
        self.opt_in(replacement)
        self.assertTrue(self.service.configuration()["ready"])
        self.mono += MAX_AGE
        self.assertIsNone(self.registry.metadata.binding(replacement.id))
        self.assertFalse(self.service.configuration()["source"]["online"])
        self.assert_guest_blocked("SOURCE_OFFLINE")
        replacement.last_seen = self.mono
        self.assertTrue(self.service.configuration()["ready"])
        self.assertEqual(original.ws.frames, [])
        self.assertEqual(replacement.ws.frames, [])

    async def test_removed_or_wrong_room_source_is_not_reported_as_enrolled(self):
        source, _ = self.ready_room()
        source.room_id = "other-room"
        configuration = self.service.configuration()
        self.assertFalse(configuration["source"]["enrolled"])
        self.assertFalse(any(configuration["source"].values()))
        self.assert_guest_blocked("SOURCE_MISSING")
        source.room_id = self.registry.room.id
        self.registry.devices.pop(source.id)
        configuration = self.service.configuration()
        self.assertFalse(configuration["source"]["enrolled"])
        self.assert_guest_blocked("SOURCE_MISSING")
        self.assertEqual(source.ws.frames, [])

    async def test_host_metadata_denial_and_extra_source_policy_explain_unreadiness(self):
        source, _ = self.ready_room()
        self.metadata_update(source, allowed=False)
        configuration = self.service.configuration()
        self.assertFalse(configuration["source"]["host_allowed"])
        self.assertTrue(configuration["source"]["consent_enabled"])
        self.assert_guest_blocked("HOST_DENIED")
        self.metadata_update(source, allowed=True)
        self.source_allowed = False
        configuration = self.service.configuration()
        self.assertTrue(all(configuration["source"].values()))
        self.assert_guest_blocked("SOURCE_UNREADY")
        self.source_allowed = True
        self.assertTrue(self.service.configuration()["ready"])
        self.assertEqual(source.ws.frames, [])

    async def test_viewer_selection_does_not_enroll_and_exact_selected_cookie_is_required(self):
        source = self.enroll_source()
        self.service.configure(source.id, "mac-main")
        self.opt_in(source)
        configuration = self.service.configuration()
        self.assertEqual(configuration["viewer"], {"enrolled": False, "online": False})
        self.assert_guest_blocked("VIEWER_UNREGISTERED")
        token = self.service.enroll_viewer("mac-main")
        viewer, seen = self.service.viewer, self.service.viewer.seen
        with self.assertRaises(PhotoError) as caught:
            self.service.viewer_state("wrong-cookie")
        self.assertEqual(caught.exception.status, 403)
        self.assertIs(self.service.viewer, viewer)
        self.assertEqual(viewer.seen, seen)
        self.assertTrue(self.service.configuration()["ready"])
        self.service.configure(source.id, "another-mac")
        configuration = self.service.configuration()
        self.assertEqual(configuration["viewer_id"], "another-mac")
        self.assertEqual(configuration["viewer"], {"enrolled": False, "online": False})
        self.assert_guest_blocked("VIEWER_UNREGISTERED")
        with self.assertRaises(PhotoError):
            self.service.viewer_state(token)
        self.assertIs(self.service.viewer, viewer)
        self.assertEqual(source.ws.frames, [])

    async def test_viewer_heartbeat_ttl_boundary_and_future_timestamp_fail_closed(self):
        source, token = self.ready_room()
        for age, online in ((0, True), (self.service.viewer_ttl - .001, True),
                            (self.service.viewer_ttl, False), (self.service.viewer_ttl + 1, False), (-.001, False)):
            with self.subTest(age=age):
                self.service.viewer.seen = self.now - age
                seen = self.service.viewer.seen
                configuration = self.service.configuration()
                self.assertEqual(configuration["viewer"], {"enrolled": True, "online": online})
                self.assertEqual(configuration["ready"], online)
                if online:
                    self.assertIsNone(self.inventory()["reason"])
                else:
                    self.assert_guest_blocked("VIEWER_OFFLINE")
                self.assertEqual(self.service.viewer.seen, seen)
        self.service.viewer_state(token)
        self.assertTrue(self.service.configuration()["viewer"]["online"])
        self.assertEqual(source.ws.frames, [])

    async def test_diagnostics_never_enable_enroll_touch_liveness_or_activate_guest(self):
        source, _ = self.ready_room()
        self.service.configure(source.id, "mac-main", enabled=False)
        joining = self.leases.create(scopes={"*"})
        self.now += 5
        before = (self.service.enabled, self.service.source_id, self.service.viewer_id, self.service.role_revision,
                  self.service.viewer, self.service.viewer.seen, source.last_seen,
                  copy.deepcopy(self.registry.enrollments), copy.deepcopy(self.registry.metadata.export()),
                  joining.state, joining.expires_at, joining.joining_until, self.registry.room.epoch,
                  self.service.version)
        for _ in range(3):
            self.service.configuration()
            self.assert_guest_blocked("GUEST_INACTIVE", lease=joining)
        after = (self.service.enabled, self.service.source_id, self.service.viewer_id, self.service.role_revision,
                 self.service.viewer, self.service.viewer.seen, source.last_seen,
                 self.registry.enrollments, self.registry.metadata.export(), joining.state, joining.expires_at,
                 joining.joining_until, self.registry.room.epoch, self.service.version)
        self.assertEqual(before, after)
        self.assertEqual(source.ws.frames, [])
        self.assertEqual(self.bus.pending, {})
        self.assertEqual(self.service.records, {})

    async def test_technical_readiness_does_not_grant_guest_scope_or_controller_authority(self):
        source, _ = self.ready_room()
        self.assertTrue(self.service.configuration()["ready"])
        result = self.service.inventory(None, generation=self.generation)
        self.assertEqual(result["reason"], "GUEST_INACTIVE")
        self.assertIsNone(result["source_device_id"])
        for scopes in (set(), {"camera.capture"}, {"photo.show"}):
            with self.subTest(scopes=scopes):
                self.lease.scopes = scopes
                self.assertTrue(self.service.configuration()["ready"])
                self.assert_guest_blocked("SCOPE_REQUIRED")
        self.lease.scopes = {"*"}
        self.controller_allowed = False
        self.assertTrue(self.service.configuration()["ready"])
        self.assert_guest_blocked("CONTROLLER_CHANGED")
        self.controller_allowed = True
        wrong_generation = self.service.inventory(self.lease, generation=self.generation + 1)
        self.assertEqual(wrong_generation["reason"], "CONTROLLER_CHANGED")
        self.assertIsNone(wrong_generation["source_device_id"])
        self.assertTrue(self.inventory()["ready"])
        self.assertEqual(source.ws.frames, [])

    async def test_inactive_guest_reason_precedes_scope_controller_and_setup_blockers(self):
        joining = self.leases.create(scopes=set())
        self.controller_allowed = False
        original_expiry = joining.expires_at
        self.assert_guest_blocked("GUEST_INACTIVE", lease=joining)
        self.assertEqual((joining.state, joining.expires_at), ("joining", original_expiry))
        self.lease.scopes.clear()
        self.assert_guest_blocked("SCOPE_REQUIRED")
        self.lease.scopes = {"*"}
        self.assert_guest_blocked("CONTROLLER_CHANGED")
        self.controller_allowed = True
        self.assert_guest_blocked("DISABLED")
        self.leases.revoke(self.lease.guest_id)
        self.assert_guest_blocked("GUEST_INACTIVE")

    async def test_pending_capture_reports_busy_without_breaking_dispatch_readiness(self):
        source, _ = self.ready_room()
        task = asyncio.create_task(self.service.capture(self.lease, "diagnostic-pending", source.id,
                                                       generation=self.generation))
        self.tasks.append(task)
        frame = await asyncio.wait_for(source.ws.queue.get(), 1)
        configuration = self.service.configuration()
        self.assertTrue(configuration["pending"])
        self.assertFalse(configuration["ready"])
        self.assertEqual(configuration["blockers"], ["BUSY"])
        self.assert_guest_blocked("BUSY")
        self.assertTrue(self.service.camera_ready(source))
        self.bus.receive(source, {"type": "ok", "req": frame["req"],
            "result": {"capture_id": frame["args"]["capture_id"], "state": "captured"}})
        self.assertEqual((await task)["state"], "captured")
        self.assert_guest_blocked("BUSY")
        self.service.invalidate_guest(self.lease.guest_id)
        self.assertFalse(self.service.configuration()["pending"])
        self.assertTrue(self.service.configuration()["ready"])
        self.assertEqual(len(source.ws.frames), 1)

    async def test_closed_service_and_host_disable_have_explicit_safe_reasons(self):
        source, _ = self.ready_room()
        self.service.configure(source.id, "mac-main", enabled=False)
        self.assertEqual(self.service.configuration()["blockers"], ["DISABLED"])
        self.assert_guest_blocked("DISABLED")
        self.service.close()
        self.assertEqual(self.service.configuration()["blockers"][0], "CLOSED")
        self.assert_guest_blocked("CLOSED")
        self.assertEqual(source.ws.frames, [])

    async def test_configuration_and_inventory_never_include_tokens_images_or_schemas(self):
        source, viewer_token = self.ready_room()
        private_bytes = b"private retained still bytes"
        self.service.latest = Image("p_retained", 1, private_bytes, self.now, source.label, "mac-main")
        source.caps["camera.capture"].description = "private adapter description"
        task = asyncio.create_task(self.service.capture(self.lease, "private-diagnostic", source.id,
                                                       generation=self.generation))
        self.tasks.append(task)
        frame = await asyncio.wait_for(source.ws.queue.get(), 1)
        for safe in (self.service.configuration(), self.inventory()):
            serialized = json.dumps(safe)
            for forbidden in (viewer_token, frame["args"]["upload_token"], private_bytes.decode(),
                              "private adapter description", "upload_token", "ticket_digest", "digest",
                              "image_url", "photo_id", "p_retained", "upload_url", "capture_id"):
                self.assertNotIn(forbidden, serialized)
        self.bus.receive(source, {"type": "ok", "req": frame["req"],
            "result": {"capture_id": frame["args"]["capture_id"], "state": "captured"}})
        await task


if __name__ == "__main__":
    unittest.main()
