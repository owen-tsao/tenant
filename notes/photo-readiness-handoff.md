# Superseded language admission

Current `brain/core/demo_photo.py` delegates all intent/readiness interpretation to the genuine agent. No phrase matcher remains. See `notes/live-demo-agent.md` for the current contract: actual app provenance, same guest/later turn/published reply, pending ID/expiry and one-shot effects are mechanical; `capture_eligible_this_turn` is not a consent classifier. Display discovery and optional pinned IDs support Mac fallback without a projector. The earlier handoff below is historical.

# Photo readiness: software handoff to the combining owner

Status: **module ready; Root owns shared wiring and the actual guest test.** The previously accepted Mac-camera/countdown/TV-photo implementation is preserved. No service restart, camera capture, TV movement, speech, audio-routing action, transcript action or web-file edit was performed in this software pass.

## Owned changes and checks

- `brain/core/demo_photo.py`: one in-memory `DemoPhotos(tools)` instance binds the pending native photo id to the exact lease object, guest, generation, room identity and epoch. It expires at the earliest of the CLI expiry, 90 seconds and lease expiry. A later grant must have an eligible **actual ordinary webchat message**; payload flags or microphone text cannot authorize it. Same-turn capture, wrong id, expiry, other guest/generation/epoch, reset and unknown-result replay are fenced.
- `tests/test_demo_photo.py`: **15 passing software-only checks**, using the real lease/publication classes and fake physical effects. Includes normal `Not yet` → `I'm ready`, bare yes only directly after the photo question, unrelated yes/ready rejection, exact-id one-shot consumption, the post-lock publication race and a blocked-capture/late-cancel regression.
- `tenant-fast-demo/photo.py`: only the cancellation branch changed. `cancel --id <id>` now checks that the CLI's current waiting pose has that exact id before stopping its camera; a stale cancel cannot stop another pending pose. Existing unbound host cancellation is retained. Capture/TV/countdown code is unchanged.
- `tenant-fast-demo/test_fast_demo.py`: **8 passing checks**, including the new stale-cancel guard. All effects are mocked.

This is not evidence of a real Tenant guest readiness pass. Earlier physical acceptance used Codex confirmations; it does not establish the new app boundary. The new module is not a transcript watcher and does not run any effect on import, `observe_turn`, status, context or publication polling.

## Frozen interface and Root's shared hooks

`DemoPhotos(tools)` expects the current `NativeDevices` owner (`registry`, `leases`, `permitted` through the caller's authorization callback). Default runner calls the existing `tenant-fast-demo/photo.py` once. Tests can inject `runner`.

1. Construct `self.demo_photos = DemoPhotos(self)` in NativeDevices.
2. Extend its `prepare(..., *, user_text=None)` only with **canonical current guest input supplied by ConversationAgent**. After creating/storing a grant, call `demo_photos.observe_turn(grant, user_text)`. This method stays **synchronous**. Do not derive this text from helper JSON, native model claims or the continuous transcript. Observation turns get no admission.
3. Append `demo_photos.context(grant)` to current native context; optionally include `demo_photos.status(grant)['pending']` in inventory. It tells the genuine agent to prepare, reply exactly **Are you ready?**, and **END/WAIT**. It forbids the raw `photo.py --confirmed` shortcut. Root must update only the photo guide section to use the bound helper, coordinating the Q&A section separately.
4. Route the operations below through the existing grant/request-id validation and duplicate cache. Invoke `await demo_photos.dispatch(grant, operation, payload, authorized=lambda: permitted(grant) and connected())`. The existing common cache should still return duplicate results without re-running effects.
5. Call `demo_photos.finish(grant)` when closing a turn grant (retains the pending pose, discards that turn's readiness). Call `invalidate()` on revoke/reset/controller replacement/close (forgets the pending pose; no old file id is adopted). The already-existing camera auto-expiry remains the backstop; this module does not claim to undo completed native effects.

### Exact helper schemas

Every schema also has the existing private token and operation envelope. Do not accept a caller `confirmed` or `requested_by_user` boolean as photo authority.

| Operation | Payload fields |
| --- | --- |
| `demo-photo-prepare` | `request_id` |
| `demo-photo-status` | `request_id` |
| `demo-photo-capture` | `request_id`, `photo_id` |
| `demo-photo-cancel` | `request_id`, `photo_id` |

Add these choices/field checks to `agent/tenant_device.py`, and use the context's **long_timeout** for these operations, not the existing 8-second default. The physical CLI runner has a **24-second overall bound**, checks current authorization before spawn and while waiting, and terminates its own process group if authorization/disconnection/cancellation ends. Already-sent native actions are not guaranteed reversible. Keep the normal request/lease deadline fence around dispatch.

Prepare returns `phase:waiting_for_reply`, the exact `photo_id`, `message:Are you ready?`, `end_turn_and_wait:true`, and `capture_allowed_this_turn:false`. Successful later capture returns `phase:displayed` only after the accepted CLI reports that exact id and a verified displayed photo. No image bytes/path need enter model history.

**Cancellation is supported only while waiting before countdown.** Once capture consumes the id, a validated same-guest/current-id cancellation returns promptly before the effect lock with `ok:false`, `code:UNKNOWN`, `status:unknown`, `phase:capture_requested_or_unknown`, and the exact `photo_id`. It sends no native cancellation, changes no capture state, and makes no claim that countdown/shutter stopped. The outcome may still be pending or unconfirmed; never retry capture. After a verified displayed result, cancel reports `code:COMPLETED`, `status:displayed` and leaves the photo displayed. Root must feed canonical validated steered guest input into `observe_turn` too, so actual cancellation text replaces the original readiness text. This adds no in-flight native cancellation machinery.

## Early readiness and the actual app publication boundary

`requires_new_turn(guest_id, text)` is **synchronous**. While that guest has a live waiting pose, it identifies ready/yes/not-yet/cancel messages that must **skip generic turn/steer**. Preserve the actual message with its original lease/generation/epoch; do not overwrite the preparation grant's input or promote it to readiness.

Queue that ordinary message until the preceding native turn releases the controller lock. **Acquiring the lock alone is insufficient:** the app publishes its response after `agent.turn` returns.

After the queued message acquires the ordinary controller lock, call:

```python
if not await demo_photos.wait_for_prompt(guest_id, text, timeout=1.5):
    # Return explicit feedback/denial. Do not steer, capture or silently drop it.
    ...
```

Then record/observe/start it as a **new** ordinary native turn/grant. `wait_for_prompt` is the only asynchronous admission helper; it is read-only and bounded. `observe_turn` remains synchronous.

The existing boundary is `GuestPublisher.send_batch`: it successfully sends the assistant frame, then calls **Core.published_reply**, which records the genuine receipt's `(generation, thread_id, turn_id)` in `Session.published_turns` and room text in `Session.transcript`. The module requires the preparation grant to be closed and that exact publication plus an actual readiness question. A successful `photo.py prepare` or its spoken audio alone is insufficient. No new shared publication hook is required for this read-only check.

The module does not itself implement the room's incoming-message queue. Root must wire this before claiming the in-app feature is complete. An early readiness reply otherwise follows the existing steer path and is not eligible for capture; it must not be silently lost.

## Requested bounded physical acceptance, after Audio releases ownership

Use one actual current Tenant guest and the existing room conversation, no new chat/model:

1. Guest sends **Take a photo of us**. Verify preview/question, **no countdown or capture**, and a completed preparation turn.
2. Same guest sends **Not yet**. Verify no countdown/capture.
3. Same guest sends **I'm ready** in Tenant. Verify one capture using the same pending id, final photo on TV and Photo Booth closed.

Also software-check a fast ready reply during preparation, so it is queued across the question's successful app publication. Stale/other-guest/reset/observation rejection already has focused unit coverage. Record actual native/helper/app identities and physical outcome separately; guide text and these fake-effect checks are not a live pass.
