"""One-still lifecycle and adversarial fences with a real Bus/Registry/Leases.

Sockets are inert test doubles: nothing opens a camera, browser or network.
Ordinary uploads use the real Pillow normalizer; a thread gate makes validation
races deterministic without sleeping or changing production code.
"""
import asyncio
from contextlib import suppress
from io import BytesIO
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

from PIL import Image as PillowImage

from brain.core.bus import Bus
from brain.core.device_metadata import MAX_AGE, update_metadata
from brain.core.integration import Core
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.native_devices import NativeDevices, TurnGrant
from brain.core.photos import CAPTURE_ARGS, MAX_BYTES, PhotoError, PhotoService
from brain.core.registry import Registry
from brain.state import Room


def jpeg(color="red"):
    output = BytesIO()
    with PillowImage.new("RGB", (32, 24), color) as image:
        image.save(output, "JPEG")
    return output.getvalue()


class Socket:
    def __init__(self):
        self.frames = []
        self.queue = asyncio.Queue()

    async def send_json(self, frame):
        self.frames.append(frame)
        self.queue.put_nowait(frame)


class ValidationGate:
    def __init__(self, loop):
        self.loop = loop
        self.entered = asyncio.Event()
        self.release = threading.Event()

    def __call__(self, body, content_type):
        self.loop.call_soon_threadsafe(self.entered.set)
        if not self.release.wait(5):
            raise RuntimeError("The test failed to release image validation")
        from brain.core.photo_image import normalize_jpeg
        return normalize_jpeg(body, content_type)


class PhotoServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000.0
        self.mono = 500.0
        self.registry = Registry(Room("TEST", "Photo test room"))
        self.registry.metadata.clock = lambda: self.now
        self.registry.metadata.monotonic = lambda: self.mono
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.lease = self.leases.create(scopes={"camera.capture", "photo.show"})
        self.leases.current(self.lease.guest_id, activate=True)
        self.allowed, self.generation, self.source_allowed = True, 7, True
        self.socket = Socket()
        self.phone = self.register("phone", self.socket)
        self.service = PhotoService(
            self.registry, self.bus, self.leases,
            authority=lambda lease, generation: self.allowed and lease is self.lease and generation == self.generation,
            source_allowed=lambda dev: self.source_allowed,
        )
        # Match the explicit installer: metadata remains closed until the real
        # photo owner supplies its consent/viewer hook. Never replace it with True.
        self.registry.metadata.camera_ready = self.service.camera_ready
        self.service.configure("phone", "mac-main")
        self.viewer_token = self.service.enroll_viewer("mac-main")
        self.consent()
        self.tasks, self.gates = [], []

    async def asyncTearDown(self):
        for gate in self.gates:
            gate.release.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError, PhotoError):
                await task

    def register(self, device_id, socket):
        device = self.registry.register({
            "type": "hello", "id": device_id, "label": "Room phone", "room": self.registry.room.code,
            "caps": {"camera.capture": {"description": "One opted-in still", "args": CAPTURE_ARGS}},
        }, socket)
        device.last_seen = self.mono
        return device

    def metadata_update(self, **body):
        core = SimpleNamespace(registry=self.registry,
            config=SimpleNamespace(host_token="host-private", device_token="device-private"),
            agent=SimpleNamespace(private_values=()))
        return update_metadata(core, "phone", body)

    def consent(self, *, enabled=True, ready=True, device=None):
        return self.service.device_event(device or self.phone,
            {"type": "photo.consent", "enabled": enabled, "ready": ready})

    def capture_task(self, request_id="request-1"):
        task = asyncio.create_task(self.service.capture(
            self.lease, request_id, "phone", generation=self.generation))
        self.tasks.append(task)
        return task

    async def begin(self, request_id="request-1"):
        task = self.capture_task(request_id)
        frame = await asyncio.wait_for(self.socket.queue.get(), 1)
        self.assertEqual(frame["cap"], "camera.capture")
        self.assertEqual(set(frame["args"]), set(CAPTURE_ARGS))
        return task, frame

    def ack(self, frame, *, payload=None, device=None):
        self.bus.receive(device or self.phone, {
            "type": "ok", "req": frame["req"],
            "result": payload if payload is not None else {
                "capture_id": frame["args"]["capture_id"], "state": "captured"},
        })

    async def upload(self, frame, body=None, content_type="image/jpeg"):
        args = frame["args"]
        return await self.service.upload(args["capture_id"], args["upload_token"],
                                         jpeg() if body is None else body, content_type)

    async def display(self, request_id="request-1", color="red"):
        task, frame = await self.begin(request_id)
        await self.upload(frame, jpeg(color))
        self.ack(frame)
        result = await task
        self.assertEqual(result["state"], "ready")
        state = self.service.viewer_state(self.viewer_token)
        photo = state["photo"]
        receipt = self.service.viewer_receipt(self.viewer_token, photo["photo_id"], photo["version"])
        self.assertEqual(receipt["state"], "displayed")
        return frame, photo

    def assert_error(self, code, status=None):
        test = self

        class ExpectedError:
            def __enter__(self):
                self.context = test.assertRaises(PhotoError)
                return self.context.__enter__()

            def __exit__(self, typ, value, tb):
                result = self.context.__exit__(typ, value, tb)
                if not result:
                    return result
                test.assertEqual(self.context.exception.code, code)
                if status is not None:
                    test.assertEqual(self.context.exception.status, status)
                return result

        return ExpectedError()

    async def test_upload_then_matching_ack_then_exact_render_receipt(self):
        task, frame = await self.begin()
        uploaded = await self.upload(frame)
        self.assertEqual(uploaded["state"], "stored")
        self.assertTrue(uploaded["stored"])
        self.assertFalse(uploaded["captured"])
        self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(self.viewer_token, frame["args"]["capture_id"])
        self.ack(frame)
        result = await task
        self.assertEqual((result["state"], result["captured"], result["stored"], result["displayed"]),
                         ("ready", True, True, False))
        state = self.service.viewer_state(self.viewer_token)
        self.assertTrue(state["pending"])
        photo = state["photo"]
        image = self.service.image(self.viewer_token, photo["photo_id"])
        with PillowImage.open(BytesIO(image)) as decoded:
            self.assertEqual((decoded.format, decoded.size), ("JPEG", (32, 24)))
        with self.assert_error("STALE", 409):
            self.service.viewer_receipt(self.viewer_token, photo["photo_id"], photo["version"] + 1)
        self.assertIsNone(self.service.latest)
        receipt = self.service.viewer_receipt(self.viewer_token, photo["photo_id"], photo["version"])
        self.assertEqual(receipt["state"], "displayed")
        self.assertFalse(self.service.viewer_state(self.viewer_token)["pending"])
        self.assertEqual(self.service.status(self.lease, "request-1")["state"], "displayed")
        self.assertEqual(self.service.viewer_receipt(self.viewer_token, photo["photo_id"], photo["version"]), receipt)

    async def test_ack_before_upload_waits_for_bytes_and_does_not_claim_display(self):
        task, frame = await self.begin()
        self.ack(frame)
        captured = await task
        self.assertEqual((captured["state"], captured["captured"], captured["stored"]), ("captured", True, False))
        self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])
        result = await self.upload(frame)
        self.assertEqual((result["state"], result["displayed"]), ("ready", False))

    async def test_duplicate_request_has_one_ticket_and_conflicting_reuse_is_rejected(self):
        task, frame = await self.begin()
        duplicate = await self.service.capture(self.lease, "request-1", "phone", generation=7)
        self.assertEqual(duplicate["capture_id"], frame["args"]["capture_id"])
        self.assertEqual(len(self.socket.frames), 1)
        self.register("phone-2", Socket())
        for source, generation in (("phone-2", 7), ("phone", 8)):
            with self.subTest(source=source, generation=generation), self.assert_error("CONFLICT", 409):
                await self.service.capture(self.lease, "request-1", source, generation=generation)
        self.ack(frame)
        await task
        again = await self.service.capture(self.lease, "request-1", "phone", generation=7)
        self.assertEqual(again["state"], "captured")
        self.assertEqual(len(self.socket.frames), 1)

    async def test_opt_in_is_distinct_from_camera_capability_and_exact_connection(self):
        self.service.consents.clear()
        self.assertFalse(self.service.inventory(self.lease, generation=7)["ready"])
        with self.assert_error("PERMISSION", 403):
            await self.service.capture(self.lease, "not-opted-in", "phone", generation=7)
        self.assertEqual(self.socket.frames, [])
        for bad in ({"type": "photo.consent", "enabled": True, "ready": True, "device_id": "phone"},
                    {"type": "photo.consent", "enabled": False, "ready": True},
                    {"type": "photo.consent", "enabled": 1, "ready": True}):
            with self.subTest(frame=bad), self.assert_error("INVALID", 400):
                self.service.device_event(self.phone, bad)
        old = self.phone
        self.registry.offline(old)
        replacement = self.register("phone", Socket())
        with self.assert_error("PERMISSION", 403):
            self.consent(device=old)
        self.assertFalse(self.service.inventory(self.lease, generation=7)["ready"])
        self.consent(device=replacement)
        self.assertTrue(self.service.inventory(self.lease, generation=7)["ready"])

    async def test_identical_consent_is_idempotent_but_opt_out_cancels(self):
        revision = self.consent()["revision"]
        task, frame = await self.begin()
        self.assertEqual(self.consent()["revision"], revision)
        self.assertIsNotNone(self.service.pending)
        self.consent(enabled=False, ready=False)
        self.ack(frame)
        result = await task
        self.assertEqual((result["state"], result["displayed"]), ("cancelled", False))
        with self.assert_error("STALE", 410):
            await self.upload(frame)

    async def test_readiness_requires_live_lease_scopes_controller_and_allowed_source(self):
        for scopes in (set(), {"camera.capture"}, {"photo.show"}):
            with self.subTest(scopes=scopes):
                self.lease.scopes = scopes
                with self.assert_error("PERMISSION", 403):
                    await self.service.capture(self.lease, "scope-check", "phone", generation=7)
        self.lease.scopes = {"*"}
        self.assertTrue(self.service.inventory(self.lease, generation=7)["ready"])
        self.assertFalse(self.service.inventory(self.lease, generation=8)["ready"])
        self.source_allowed = False
        self.assertFalse(self.service.inventory(self.lease, generation=7)["ready"])
        self.source_allowed = True
        self.lease.state = "joining"
        with self.assert_error("PERMISSION", 403):
            await self.service.capture(self.lease, "joining-check", "phone", generation=7)
        self.assertEqual(self.lease.state, "joining")
        self.assertEqual(self.socket.frames, [])

    async def test_selected_viewer_enrollment_secret_rotation_and_liveness(self):
        with self.assert_error("TARGET", 409):
            self.service.enroll_viewer("other-mac")
        original = self.viewer_token
        self.now += 14
        for action in (lambda: self.service.viewer_state("wrong-secret"),
                       lambda: self.service.image("wrong-secret", "photo"),
                       lambda: self.service.viewer_receipt("wrong-secret", "photo", 1)):
            with self.assert_error("PERMISSION", 403):
                action()
        self.assertEqual(self.service.viewer.seen, 1000)
        self.now += 1
        with self.assert_error("VIEWER_OFFLINE", 409):
            await self.service.capture(self.lease, "viewer-expired", "phone", generation=7)
        self.service.viewer_state(original)
        self.assertTrue(self.service.inventory(self.lease, generation=7)["ready"])
        self.viewer_token = self.service.enroll_viewer("mac-main")
        with self.assert_error("PERMISSION", 403):
            self.service.viewer_state(original)
        self.assertTrue(self.service.inventory(self.lease, generation=7)["ready"])

    async def test_metadata_host_allowance_is_required_in_addition_to_photo_consent(self):
        self.assertIs(self.registry.metadata.binding("phone"), self.phone)
        self.metadata_update(allowed=False)
        self.assertFalse(self.service.camera_ready(self.phone))
        self.assertFalse(self.service.inventory(self.lease, generation=7)["ready"])
        with self.assert_error("PERMISSION", 403):
            await self.service.capture(self.lease, "metadata-denied", "phone", generation=7)
        self.assertEqual(self.socket.frames, [])
        self.assertEqual(self.service.records, {})
        self.metadata_update(allowed=True)
        self.assertTrue(self.service.camera_ready(self.phone))
        self.assertTrue(self.service.inventory(self.lease, generation=7)["ready"])
        task, frame = await self.begin("metadata-now-allowed")
        self.ack(frame)
        self.assertEqual((await task)["state"], "captured")

    async def test_metadata_binding_requires_fresh_heartbeat_and_photo_camera_readiness(self):
        self.mono += MAX_AGE
        self.assertIsNone(self.registry.metadata.binding("phone"))
        self.assertFalse(self.service.camera_ready(self.phone))
        self.assertFalse(self.service.inventory(self.lease, generation=7)["ready"])
        with self.assert_error("PERMISSION", 403):
            await self.service.capture(self.lease, "stale-heartbeat", "phone", generation=7)
        self.phone.last_seen = self.mono
        self.assertIs(self.registry.metadata.binding("phone"), self.phone)
        self.assertTrue(self.service.inventory(self.lease, generation=7)["ready"])
        self.consent(ready=False)
        self.assertFalse(self.service.camera_ready(self.phone))
        with self.assert_error("PERMISSION", 403):
            await self.service.capture(self.lease, "camera-not-ready", "phone", generation=7)
        self.assertEqual(self.socket.frames, [])
        self.assertEqual(self.service.records, {})

    async def test_photo_readiness_hook_keeps_pending_capture_dispatchable(self):
        self.assertIs(self.registry.metadata.camera_ready.__self__, self.service)
        self.assertTrue(self.registry.metadata.available(self.phone, "camera.capture"))
        lock = self.bus.locks["phone"]
        await lock.acquire()
        task = self.capture_task("readiness-queued")
        try:
            for _ in range(20):
                if self.service.pending is not None:
                    break
                await asyncio.sleep(0)
            self.assertIsNotNone(self.service.pending)
            self.assertFalse(self.service.inventory(self.lease, generation=7)["ready"])
            # Admission is busy, but that must not close the already-admitted
            # capture's metadata gate while the actual Bus lock is queued.
            self.assertTrue(self.service.camera_ready(self.phone))
            self.assertTrue(self.registry.metadata.available(self.phone, "camera.capture"))
        finally:
            lock.release()
        frame = await asyncio.wait_for(self.socket.queue.get(), 1)
        self.ack(frame)
        self.assertEqual((await task)["state"], "captured")

    async def test_photo_readiness_hook_tracks_selected_viewer_consent_and_closure(self):
        self.assertTrue(self.service.camera_ready(self.phone))
        self.consent(enabled=False, ready=False)
        self.assertFalse(self.registry.metadata.available(self.phone, "camera.capture"))
        self.consent()
        self.now += self.service.viewer_ttl
        self.assertFalse(self.service.camera_ready(self.phone))
        self.service.viewer_state(self.viewer_token)
        self.assertTrue(self.service.camera_ready(self.phone))
        self.service.configure("phone", "other-mac")
        self.assertFalse(self.service.camera_ready(self.phone))
        self.service.enroll_viewer("other-mac")
        self.assertTrue(self.service.camera_ready(self.phone))
        self.service.close()
        self.assertFalse(self.service.camera_ready(self.phone))
        self.assertFalse(self.registry.metadata.available(self.phone, "camera.capture"))

    async def test_readiness_is_not_guest_authority_and_native_raw_camera_stays_blocked(self):
        self.assertTrue(self.service.camera_ready(self.phone))
        self.allowed = False
        self.assertTrue(self.service.camera_ready(self.phone))
        with self.assert_error("PERMISSION", 403):
            await self.service.capture(self.lease, "not-controller", "phone", generation=7)
        self.allowed = True
        helper = NativeDevices(self.registry, self.bus, self.leases, EventLog(), lambda grant: True)
        helper.photos = self.service
        grant = TurnGrant(self.lease.guest_id, 7, self.lease, "test-thread", self.registry.room.id,
                          self.registry.room.epoch, Path("unused-photo-test-context"), "test-turn-token")
        grant.turn_id, grant.deadline = "test-turn", asyncio.get_running_loop().time() + 10
        helper._grants[grant.token] = grant
        inventory = await helper.dispatch({"token": grant.token, "operation": "inventory"})
        self.assertFalse(any(cap["name"] == "camera.capture"
                             for device in inventory["devices"] for cap in device["caps"]))
        result = await helper.dispatch({"token": grant.token, "operation": "call", "request_id": "raw-camera",
            "device_id": "phone", "cap": "camera.capture",
            "args": {"capture_id": "unbound", "upload_url": "/unbound", "upload_token": "unbound"}})
        self.assertFalse(result["ok"])
        self.assertEqual(self.socket.frames, [])
        self.assertEqual(self.service.records, {})

    async def test_capture_queued_on_real_bus_rechecks_every_authority_fence(self):
        changes = ("scope", "expiry", "generation", "host", "consent", "role", "viewer", "socket", "replacement", "epoch",
                   "metadata-role", "metadata-revision", "metadata-allowed", "heartbeat")
        for change in changes:
            with self.subTest(change=change):
                # Each case gets a fresh real room/lease/socket, not a mocked Bus.
                await self.asyncSetUp()
                lock = self.bus.locks["phone"]
                await lock.acquire()
                task = self.capture_task("queued-" + change)
                try:
                    # Starting capture registers its tombstone before waiting on Bus.
                    for _ in range(20):
                        if self.service.pending is not None:
                            break
                        await asyncio.sleep(0)
                    self.assertIsNotNone(self.service.pending)
                    if change == "scope": self.lease.scopes.remove("photo.show")
                    elif change == "expiry": self.now = self.lease.expires_at
                    elif change == "generation": self.generation += 1
                    elif change == "host": self.source_allowed = False
                    elif change == "consent": self.consent(ready=False)
                    elif change == "role": self.service.configure("phone", "other-mac")
                    elif change == "viewer": self.service.enroll_viewer("mac-main")
                    elif change == "socket": self.phone.ws = Socket()
                    elif change == "replacement":
                        self.registry.offline(self.phone)
                        self.register("phone", Socket())
                    elif change == "epoch": self.registry.room.epoch += 1
                    elif change == "metadata-role": self.metadata_update(role="different-room-role")
                    elif change == "metadata-revision": self.metadata_update(location="Whiteboard")
                    elif change == "metadata-allowed":
                        self.metadata_update(allowed=False)
                        self.metadata_update(allowed=True)
                    elif change == "heartbeat": self.mono += MAX_AGE
                finally:
                    lock.release()
                result = await asyncio.wait_for(task, 1)
                self.assertFalse(result["sent"])
                self.assertFalse(result["ok"])
                self.assertIn(result["state"], {"cancelled", "failed"})
                self.assertEqual(self.socket.frames, [])
                self.service.sweep()
                self.assertIsNone(self.service.pending)
                await self.asyncTearDown()

    async def test_upload_ticket_authentication_single_use_and_identical_retry(self):
        task, frame = await self.begin()
        args = frame["args"]
        for capture_id, token in (("unbound", args["upload_token"]), (args["capture_id"], "wrong"),
                                  (args["capture_id"], None), (args["capture_id"], "x" * 129)):
            with self.subTest(capture_id=capture_id, token_kind=type(token)), self.assert_error("PERMISSION", 403):
                await self.service.upload(capture_id, token, jpeg(), "image/jpeg")
        body = jpeg()
        stored = await self.upload(frame, body)
        self.assertEqual(await self.upload(frame, body), stored)
        with self.assert_error("CONFLICT", 409):
            await self.upload(frame, jpeg("blue"))
        self.ack(frame)
        await task
        self.assertEqual((await self.upload(frame, body))["state"], "ready")
        self.assertEqual(len(self.socket.frames), 1)

    async def test_upload_empty_nonbytes_and_oversize_do_not_consume_ticket(self):
        task, frame = await self.begin()
        args = frame["args"]
        for body, status in ((b"", 400), (bytearray(jpeg()), 400), (b"x" * (MAX_BYTES + 1), 413)):
            with self.subTest(length=len(body)), self.assert_error("INVALID_IMAGE", status):
                await self.service.upload(args["capture_id"], args["upload_token"], body, "image/jpeg")
        self.assertFalse(self.service.pending.ticket_used)
        await self.upload(frame)
        self.ack(frame)
        self.assertEqual((await task)["state"], "ready")

    async def test_invalid_mime_or_image_consumes_ticket_without_publication(self):
        for index, (body, mime) in enumerate(((jpeg(), "image/png"), (b"not-an-image", "image/jpeg"),
                                             (jpeg()[:-2], "image/jpeg"))):
            with self.subTest(mime=mime, index=index):
                task, frame = await self.begin("invalid-" + str(index))
                with self.assert_error("INVALID_IMAGE", 400):
                    await self.upload(frame, body, mime)
                self.ack(frame)
                result = await task
                self.assertEqual((result["state"], result["stored"], result["displayed"]), ("failed", False, False))
                self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])
                with self.assert_error("CONFLICT", 409):
                    await self.upload(frame)

    async def test_thread_validation_rechecks_all_current_authority_before_commit(self):
        changes = ("scope", "expiry", "generation", "host", "consent", "role", "viewer", "socket", "replacement", "epoch", "reset",
                   "metadata-role", "metadata-revision", "metadata-allowed", "heartbeat")
        for change in changes:
            with self.subTest(change=change):
                await self.asyncSetUp()
                gate = ValidationGate(asyncio.get_running_loop())
                self.gates.append(gate)
                self.service.normalizer = gate
                task, frame = await self.begin("validation-" + change)
                self.ack(frame)
                self.assertEqual((await task)["state"], "captured")
                upload = asyncio.create_task(self.upload(frame))
                self.tasks.append(upload)
                await asyncio.wait_for(gate.entered.wait(), 1)
                with self.assert_error("BUSY", 409):
                    await self.upload(frame)
                if change == "scope": self.lease.scopes.clear()
                elif change == "expiry": self.now = self.lease.expires_at
                elif change == "generation": self.generation += 1
                elif change == "host": self.source_allowed = False
                elif change == "consent": self.consent(enabled=False, ready=False)
                elif change == "role": self.service.configure("phone", "other-mac")
                elif change == "viewer": self.service.enroll_viewer("mac-main")
                elif change == "socket": self.phone.ws = Socket()
                elif change == "replacement":
                    self.registry.offline(self.phone)
                    self.register("phone", Socket())
                elif change == "epoch": self.registry.room.epoch += 1
                elif change == "reset": self.service.reset()
                elif change == "metadata-role": self.metadata_update(role="different-room-role")
                elif change == "metadata-revision": self.metadata_update(location="Whiteboard")
                elif change == "metadata-allowed":
                    self.metadata_update(allowed=False)
                    self.metadata_update(allowed=True)
                elif change == "heartbeat": self.mono += MAX_AGE
                gate.release.set()
                with self.assert_error("STALE", 410):
                    await upload
                self.assertIsNone(self.service.latest)
                self.assertIsNone(self.service.pending)
                self.assertTrue(all(rec.image is None for rec in self.service.records.values()))
                await self.asyncTearDown()

    async def test_unknown_and_malformed_ack_never_publish_or_replay_shutter(self):
        for index, payload in enumerate(({"capture_id": "wrong", "state": "captured"},
                                         {"state": "captured"}, {"capture_id": "unused", "state": "ok"})):
            with self.subTest(index=index):
                task, frame = await self.begin("malformed-" + str(index))
                await self.upload(frame)
                self.ack(frame, payload=payload)
                result = await task
                self.assertEqual((result["state"], result["code"]), ("unknown", "UNKNOWN"))
                self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])
                count = len(self.socket.frames)
                duplicate = await self.service.capture(self.lease, "malformed-" + str(index), "phone", generation=7)
                self.assertEqual(duplicate, result)
                self.assertEqual(len(self.socket.frames), count)
        self.service.capture_timeout = .02
        task, frame = await self.begin("timeout")
        result = await task
        self.assertEqual((result["state"], result["sent"]), ("unknown", True))
        self.ack(frame)  # Late Bus resolution cannot promote/replay a terminal photo.
        self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])
        self.assertEqual(await self.service.capture(self.lease, "timeout", "phone", generation=7), result)
        self.assertEqual(len(self.socket.frames), 4)

    async def test_wrong_device_ack_cannot_confirm_authenticated_source(self):
        task, frame = await self.begin()
        other = self.register("other-phone", Socket())
        await self.upload(frame)
        self.ack(frame, device=other)
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])
        self.ack(frame)
        self.assertEqual((await task)["state"], "ready")

    async def test_phone_error_cannot_echo_private_ticket_or_message_into_safe_status(self):
        task, frame = await self.begin()
        secret = frame["args"]["upload_token"]
        self.bus.receive(self.phone, {
            "type": "err", "req": frame["req"], "code": secret,
            "message": "private phone detail: " + secret,
        })
        result = await task
        self.assertEqual((result["state"], result["code"]), ("failed", "PHONE_FAILED"))
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("private phone detail", json.dumps(result))
        self.assertEqual(self.service.status(self.lease, "request-1"), result)
        self.assertIsNone(self.service.viewer_state(self.viewer_token)["photo"])

    async def test_final_dispatch_callback_is_rechecked_after_bus_queue_wait(self):
        lock = self.bus.locks["phone"]
        await lock.acquire()
        dispatch = {"allowed": True}
        task = asyncio.create_task(self.service.capture(
            self.lease, "dispatch-race", "phone", generation=7,
            dispatch_allowed=lambda: dispatch["allowed"]))
        self.tasks.append(task)
        try:
            for _ in range(20):
                if self.service.pending is not None:
                    break
                await asyncio.sleep(0)
            self.assertIsNotNone(self.service.pending)
            dispatch["allowed"] = False
        finally:
            lock.release()
        result = await asyncio.wait_for(task, 1)
        self.assertEqual((result["state"], result["code"], result["sent"]), ("failed", "PERMISSION", False))
        self.assertEqual(self.socket.frames, [])

    async def test_cancel_at_possible_send_is_unknown_and_request_never_replays(self):
        task, frame = await self.begin()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        result = self.service.status(self.lease, "request-1")
        self.assertEqual((result["state"], result["code"], result["sent"]), ("unknown", "UNKNOWN", True))
        self.ack(frame)
        duplicate = await self.service.capture(self.lease, "request-1", "phone", generation=7)
        self.assertEqual(duplicate, result)
        self.assertEqual(len(self.socket.frames), 1)
        with self.assert_error("STALE", 410):
            await self.upload(frame)

    async def test_busy_request_rejected_without_second_shutter(self):
        task, frame = await self.begin()
        with self.assert_error("BUSY", 409):
            await self.service.capture(self.lease, "another-request", "phone", generation=7)
        self.assertEqual(len(self.socket.frames), 1)
        self.ack(frame)
        await task

    async def test_failed_replacement_preserves_previous_display_and_lease_end_retains_it(self):
        _, photo = await self.display()
        retained = self.service.image(self.viewer_token, photo["photo_id"])
        task, frame = await self.begin("replacement")
        await self.upload(frame, jpeg("blue"))
        self.ack(frame, payload={"state": "captured", "capture_id": "wrong"})
        self.assertEqual((await task)["state"], "unknown")
        self.assertEqual(self.service.viewer_state(self.viewer_token)["photo"], photo)
        self.leases.revoke(self.lease.guest_id)
        self.service.invalidate_guest(self.lease.guest_id)
        self.service.sweep()
        self.assertEqual(self.service.image(self.viewer_token, photo["photo_id"]), retained)
        self.lease = self.leases.create(scopes={"*"})
        self.leases.current(self.lease.guest_id, activate=True)
        self.assertEqual(self.service.viewer_state(self.viewer_token)["photo"], photo)
        self.now = self.lease.expires_at
        self.leases.sweep()
        self.service.sweep()
        self.assertEqual(self.service.image(self.viewer_token, photo["photo_id"]), retained)
        # A render receipt retry is still idempotent after the guest has expired.
        self.assertEqual(self.service.viewer_receipt(self.viewer_token, photo["photo_id"], photo["version"])["state"], "displayed")

    async def test_leave_cancels_unconfirmed_candidate_and_late_render_receipt(self):
        _, old = await self.display()
        task, frame = await self.begin("candidate")
        await self.upload(frame, jpeg("blue"))
        self.ack(frame)
        await task
        candidate = self.service.viewer_state(self.viewer_token)["photo"]
        self.leases.revoke(self.lease.guest_id)
        self.service.invalidate_guest(self.lease.guest_id)
        self.assertEqual(self.service.viewer_state(self.viewer_token)["photo"], old)
        with self.assert_error("STALE", 409):
            self.service.viewer_receipt(self.viewer_token, candidate["photo_id"], candidate["version"])
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(self.viewer_token, candidate["photo_id"])

    async def test_metadata_role_change_fences_render_receipt_and_preserves_previous_display(self):
        _, old = await self.display()
        task, frame = await self.begin("metadata-render-race")
        await self.upload(frame, jpeg("blue"))
        self.ack(frame)
        self.assertEqual((await task)["state"], "ready")
        candidate = self.service.viewer_state(self.viewer_token)["photo"]
        self.metadata_update(role="new-camera-role")
        with self.assert_error("STALE", 409):
            self.service.viewer_receipt(self.viewer_token, candidate["photo_id"], candidate["version"])
        self.assertEqual(self.service.status(self.lease, "metadata-render-race")["state"], "cancelled")
        self.assertEqual(self.service.viewer_state(self.viewer_token)["photo"], old)
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(self.viewer_token, candidate["photo_id"])

    async def test_new_display_replaces_previous_bytes_without_gallery(self):
        _, old = await self.display()
        _, new = await self.display("second", "blue")
        self.assertNotEqual(new["photo_id"], old["photo_id"])
        self.assertGreater(new["version"], old["version"])
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(self.viewer_token, old["photo_id"])
        self.assertEqual(self.service.viewer_state(self.viewer_token)["photo"], new)
        self.assertTrue(all(rec.image is None for rec in self.service.records.values()))

    async def test_host_reset_erases_all_image_bytes_and_late_ack_cannot_restore(self):
        _, old = await self.display()
        task, frame = await self.begin("reset-pending")
        await self.upload(frame, jpeg("blue"))
        before = self.service.version
        self.leases.reset()
        self.service.reset()
        self.assertIsNone(self.service.latest)
        self.assertIsNone(self.service.pending)
        self.assertTrue(all(rec.image is None for rec in self.service.records.values()))
        self.ack(frame)
        self.assertEqual((await task)["state"], "cancelled")
        state = self.service.viewer_state(self.viewer_token)
        self.assertIsNone(state["photo"])
        self.assertGreater(state["version"], before)
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(self.viewer_token, old["photo_id"])
        with self.assert_error("STALE", 409):
            self.service.viewer_receipt(self.viewer_token, old["photo_id"], old["version"])
        self.assertEqual((await self.service.capture(self.lease, "reset-pending", "phone", generation=7))["state"], "cancelled")
        self.assertEqual(len(self.socket.frames), 2)

    async def test_selected_viewer_role_change_preserves_but_does_not_leak_old_photo(self):
        _, photo = await self.display()
        self.service.configure("phone", "other-mac")
        with self.assert_error("PERMISSION", 403):
            self.service.image(self.viewer_token, photo["photo_id"])
        other_token = self.service.enroll_viewer("other-mac")
        self.assertIsNone(self.service.viewer_state(other_token)["photo"])
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(other_token, photo["photo_id"])
        self.assertIsNotNone(self.service.latest)

    async def test_request_tracking_is_bounded_and_reaped_without_dropping_latest(self):
        self.service.capacity = 2
        _, old = await self.display()
        _, new = await self.display("second", "blue")
        with self.assert_error("CAPACITY", 503):
            await self.service.capture(self.lease, "third", "phone", generation=7)
        self.assertEqual(len(self.socket.frames), 2)
        self.now = self.lease.expires_at + 120
        self.service.sweep()
        self.assertEqual((self.service.records, self.service.by_capture), ({}, {}))
        self.assertEqual(self.service.image(self.viewer_token, new["photo_id"]), self.service.latest.data)
        with self.assert_error("NOT_FOUND", 404):
            self.service.image(self.viewer_token, old["photo_id"])

    async def test_safe_status_inventory_repr_public_core_and_history_exclude_private_material(self):
        task, frame = await self.begin()
        body = jpeg()
        await self.upload(frame, body)
        self.ack(frame)
        await task
        app = SimpleNamespace(state=SimpleNamespace(registry=self.registry, bus=self.bus,
                              config=SimpleNamespace(public_url="https://room.invalid", host_token="host", device_token="device")))
        core = Core(app, planner=None, clock=lambda: self.now)
        core.leases = self.leases
        core.photos = self.service
        public = core.snapshot()
        status = self.service.status(self.lease, "request-1")
        inventory = self.service.inventory(self.lease, generation=7)
        for safe in (status, inventory, public, self.leases.sessions[self.lease.guest_id].messages):
            serialized = json.dumps(safe)
            for secret in (frame["args"]["upload_token"], self.viewer_token, "/photos/images/", "upload_token", "ticket_digest"):
                self.assertNotIn(secret, serialized)
            self.assertNotIn(body.hex(), serialized)
        self.assertNotIn("photos", public)
        self.assertNotIn("image", status)
        self.assertNotIn("image_url", status)
        for record in self.service.records.values():
            self.assertNotIn(frame["args"]["upload_token"], repr(record))
            self.assertNotIn(repr(body), repr(record))
        self.assertNotIn(self.viewer_token, repr(self.service.viewer))


if __name__ == "__main__":
    unittest.main()
