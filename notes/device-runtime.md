# Device runtime — local Mac owner

## Current deployed status — Root reported

Root reports deployed source `e294e66`, including the generic native Mac/browser discovery correction. This revision has **96 focused software checks** and an independent Audio review against exact source hashes. These are separate validation reports; no overlapping counts are added. This owner has not rerun checks or independently redeployed this revision.

Root reports a fresh browser Japanese Denim **PASS**: Jay heard playback after an onset delay, the ordinary Stop reply took roughly36 seconds, normal Leave completed, and the owned browser tab was confirmed absent. The phone was not exercised in that browser case. Tester is currently preparing one real-phone Photon inbound case; no outcome is claimed yet.

The projector remains blocked on physical power: its power adapter has not been located and its electrical rating is unknown. Wall projection is unconfirmed. The Mac-side path was separately verified as external extended, built-in main, both mirror-off, with the dedicated public Tenant window preserved externally; this does not establish projector power or wall-image acceptance.

Root coordinates live gates and Tester owns the authorized live cases. This owner's production/tests remain frozen unless a concrete failure is assigned. This update changes only this notes file for Root publication: no source/test, effect, service or UI action and no rerun. The source-handoff snapshots, pause statements, manifests and test counts below are historical evidence, not current deployed status.

### Earlier rollout checkpoint — historical

Before the current revision, Root reported combined `e4b8426` published after761 Python+12 Node checks and independent exact-map review, then Brain+audio deployed while the room was quiet. Room8157/current phone/Mac survived, and song capabilities and device backend state/API were reported live. These were Root's rollout attestations at that checkpoint, not a current test or deployment verification by this owner. Optional device UI was Owen-owned; photo consent/capture/upload/authenticated-viewer UI was then absent per Root inspection, so physical photo acceptance was then Owen-blocked. These historical assertions do not supersede later case-specific evidence.

## Historical device-awareness source handoff — frozen before Root rollout

At this historical source-handoff checkpoint, Jay had resumed software work only. **End-to-end/live/public UI/real model-room/deployed-service/device/camera/music testing was paused and Root held the live gate at that time.** No service restart, deployment, live effect, staging or commit was performed by this owner at that checkpoint. Independent bounded diagnostic, queue and freeze reviewers were used.

Final immutable `validation4` passes **710 Python tests +16 explicit metadata wiring/queue checks**, zero failures/errors/skips. The12 Node checks passed on the identical phone runtime/test hashes; no unnecessary rerun after the speech-only patch. Independent final reviewer `/root/device_awareness_final_review` passed **68 targeted checks** (28 metadata,8 wiring,8 queue/scheduling,24 existing speech/voice), found no remaining actionable issues, and matched all137 validation hashes. Full-map canonical digest: `1b730f941a2f4369bf78ed4e32877706f788f6a58ec7ce2b1f0679a1b69d8b04`. Exact full source map, changed-source map, commands' results/limits and failure history are in `tests/evidence/2026-10-17-device-awareness.json`.

Implemented only registry/persistence/device metadata/API/tests and the **unapplied** `notes/proposed-device-awareness-wiring.patch`. **No state.py, ws/display.py, web/, sources/, Audio driver/song source or Tester room_session/room_conversation/webchat edits by this owner.** Root must integrate the proposed central hooks before exposing the new API/state. Patch is tested on the snapshot, not applied in the shared checkout. It targets integration.py, bus.py, guest_view.py, native_devices.py, conversation_speech.py, room_programs.py, tools.py and agent.py; expected base/applied hashes for each are in evidence. Preserve the parallel owners' source when adapting it. Any post-freeze edit needs appropriate review/checks before a new source PASS claim.

Behavior: existing authenticated enrollment ID/stable room identity is retained across reconnect/reset/restart; host label/role/location/output description/use allowance survive changed hello frames. V1 room state migrates to strict V2 with bounded metadata; connections, capability schemas, guest credentials/history and camera consent stay transient. Failed/ambiguous persistence remains closed until trusted reload, so unrelated hellos cannot overwrite a durably saved denial. Known private literals and control characters are removed from retained/public adapter labels; host metadata rejects credentials. Unknown facts remain unknown; a Mac output is an attribute, never a fabricated speaker/projector endpoint.

Persistence migration savesV2 at startup; an olderV1-only reader cannot load it. Root must use trusted compatible state/recovery for any rollback, rather than silently downgrading or replacing room identity.

Availability requires exact current enrollment/binding/room, online/fresh heartbeat, healthy identity storage, advertised capability and host allowance. Guest scopes/controller/consent remain separate. Revisions are captured before logical queues and checked through Bus dispatch, blink waits, generated/song pulse loops, monitors and scheduled speech. Host deny→reenable cannot revive old work. Scheduled old narration is consumed with0sends; a fresh reply can still speak once under the existing opt-in. Discovery grants no authority, triggers no effect, enables no speech and creates no suggestion engine.

Host `allowed:false` blocks all new Bus effects, including cleanup; it does **not** claim to undo started effects. Cleanup may remain unconfirmed until host re-enable and a fresh explicit OFF/stop. Those fresh paths are verified with fakes, while old queued actions stay fenced. UNKNOWN no-replay/substitution and existing voice/default-output policy are preserved.

### Root / photo coordination

`metadata.camera_ready` defaults false. Photo owner now supplies `PhotoService.camera_ready` via its explicit installer, checking exact source/consent/host allowance and current authenticated viewer; PhotoService still owns originating guest/controller/epoch/ticket/commit authorization. Raw `Core.host_do` camera capture is rejected, including display host.do. The former optional `notes/proposed-device-photo-readiness.patch` was **withdrawn/deleted** because it duplicated the owner's real callback; do not restore/apply it. Photo's direct-service fixture now explicitly binds that same callback. Final710-test snapshot includes those owner fixes and nonnegative viewer-age bounds. Photo/UI/physical acceptance is separate, not opened by this software pass.

Read-only interface: `registry.metadata.role_devices(role)` returns detached `({device_id,metadata_revision},...)` for live host-allowed explicit role matches. `binding(id)` returns the exact live Device object or None; `revision(id)` and `guard(ids)` fence identity/metadata across waits. `available(device,cap)` is only a necessary availability check, never a guest grant, source consent or viewer authorization.

### Optional state/API contract — ready for Owen via Root

Existing device rows keep `id,label,caps,online,busy`. Add optional `role,location,output_description` (null when unknown), `connection_state` (`online|offline|unknown`), `allowed`, `metadata_revision`, field-level `provenance`, and `capability_status:[{name,status:'available'|'blocked',reason,provenance:'adapter_reported',observed_at}]`. Public `caps` lists available operations only; guest controls intersect scopes. Internal/native inventory keeps offline schemas as non-executable descriptions for compatibility. Provenance distinguishes `host_specified`, `adapter_reported`, `authenticated_enrollment`, `existing_enrollment_policy`, and `unknown`; no hardware attestation is inferred. No sockets/raw schemas/private provider keys/known credentials are public. A Mac output description stays on the same row. Owen owns every UI file; no redesign requested.

Bearer-authenticated `PATCH /host/devices/{existing_id}/metadata` accepts a nonempty subset of `label,role,location,output_description,allowed`. Unknown identity404; missing/invalid host auth403; invalid/private text400; uncertain storage503. It never creates an identity, guest scope, speech choice or effect. The coordinator can diff factual availability changes and apply Jay's contextual suggestion/notice judgment; no fixed announcements, quotas or separate suggestion engine were added.

### Failure history — retained, resolved in final snapshot

The paused validation2 run ended by SIGINT/130, not PASS. Exact causes were independently diagnosed: retirement fixture incorrectly expected an ordinary persist to heal unhealthy storage; app fixture's credential `device` overlapped visible label `Room device`; direct PhotoService fixture omitted readiness wiring. Device compatibility tests now use independent audit scenarios/trusted reload and a noncolliding label; photo owner corrected its fixture.

Validation3 completed698 tests with2 failures from incomplete **other-owner** candidates: native stale-approval recovery and song buffering/resume. Both reproduced identically with this metadata patch reversed, confirming separate causes. Tester/Audio subsequently updated their source; final validation4 captures their new hashes and passes710/710. These earlier failures are retained in evidence, not averaged away or credited as fixes by this owner.

### Frozen owned files — Root integrates, no owner staging/commit

SHA256s below cover the11 owned source/test/proposal files. Root may add this note, final evidence, historical paused evidence and `notes/device-awareness-manifest.sha256`; do not stage other owners' files on this owner's behalf. Proposed patch SHA256 is `1dc18d54e98ad62fdbef00e1e049f4f922ae7c32aa01b6e281ae53519df00df3`.

```text
f13af289fc63494805c764ab0c7e290a83e15ccdb9ca561a402f4e0cddb2f17b  brain/api/device_metadata.py
7b6a4ec48bdffa9a1592b515d75950a476f5026f9901578d5f1d1e834b619ffd  brain/core/device_metadata.py
bb1f2af07c5aa65c14f85c83054b12e188cd61478f4071edc050945fe0fb3199  brain/core/persistence.py
c0a7f260bbad1e3de732d98b2b9d94009428b4d2ac8f5070abffb44ec73b57bf  brain/core/registry.py
1dc18d54e98ad62fdbef00e1e049f4f922ae7c32aa01b6e281ae53519df00df3  notes/proposed-device-awareness-wiring.patch
deecdda453da0d5b8d321f2eb55ffa4757df7c102169a859a9f4db182cb844a3  tests/device_metadata_queue_checks.py
452ea2c74b99e99cb077b9afcc00d89c61f43d29d169c3d941dd92ccb2971693  tests/device_metadata_wiring_checks.py
912f766583d3c47233a856c69fa2f20f535c1e3ca93f4be14e1bee576cb319c9  tests/test_access_persistence.py
50b627c8d83f2488f324dcaa01133962c437e4c657a4117bbebf29d9d996e5d9  tests/test_app_integration.py
31fb26f2f896ee622b6d48fde86060fb0a75f89fd66681fc19a8d8c22d428039  tests/test_device_metadata.py
4abbc604945a9d065e44e0806f2f1acd071b19df48d13b66dd07f7204407be65  tests/test_device_retirement.py
```

Historical public-conversation projection handoff follows; it was integrated/deployed as c7e902b and actual-UI verified by Tester. Its older deployment/feature status statements are history, not this candidate's current status.

October 17: working from frozen voice baseline `f228b39`. Scope is Owen's existing public display transcript and truthful lease totals. Voice policy/helper code remains frozen; the only overlapping seams are additive publication hooks in Core, GuestPublisher and Photon after successful text publication. No web/source-reference edits, deployment, service restart, live guest creation or physical actions. Root owns final integration and live testing.

20:00 PT — READY FOR ROOT INTEGRATION, source only. No staging or commit. Independent review `/root/display_projection_review` reports no actionable findings; 165 related fake-I/O checks passed, followed by confirmation of the final test-only assertions. Frozen isolated source passes **496 Python +12 Node**, zero failures/skips (17.472s /2.268s). This count includes the concurrently supplied one-test voice acceptance file; its ownership remains with tester/Root. Projection adds 11 tests. Shared source still matches all 106 frozen validation files.

Implemented the existing `guests[].transcript` contract: separate last10 in-memory `{role:'guest'|'room',text,t}` rows; native input is validated/authorized and redacted before capture; room text is the exact already-redacted completed final reply after WebSocket send success or Photon HTTP acceptance. Publication deduplicates native receipts internally; receipts, tools, commentary, model/native history and speech output never enter the projection. Photon acceptance is **not delivered-message proof**. Failed/uncertain publication retains guest input only. Late handoff/revoke/expiry/reset cannot repopulate ended guests. Ended projections are cleared; fresh guests start empty; snapshots detach row copies and show only live current-room grants. Current native controller sorts first, then active, then joining.

`guests[].lease_total` is the **issued** effective joining duration (normally120s, capped by original access duration), then original active duration (normally600s). Custom durations are covered. Activation, reconnect and inspection renew neither deadline nor denominator. Owen already consumes this field on guests; no web edit or room field was necessary.

Frozen owned files below; Root should stage only these eight source/test files plus this note and `tests/evidence/2026-10-17-display-projection.json`. Full validation manifest and precise checks are in that evidence JSON; canonical full-map digest is `2e751f910d7510c6e2e6877fa1c958f53848d400705215fa674c8e49b1addf98` (SHA256 of sorted-key JSON hash map). No architecture, web, Audio policy/helper, deployment or live-state change was made. The three overlapping publication hooks are additive and preserve frozen voice scheduling/authorization.

```text
49325832ecf376c7b8db2064d30df08b644770d261bf8c8b316cc35b605be863  brain/state.py
fb83bba8e4b1b1123937df057c293f71e4fffef9c59c1df53abfedd100facf5a  brain/core/leases.py
056bf7535c55f589527226785eb9f0f95ebf508561dd77d4a114f0d3beb48078  brain/core/integration.py
8534021edb56e10f513720c4b0f435fa758db1c6ae4703cf84f434f2a6520d6b  brain/core/room_conversation.py
fb29312c48568f48d3751371981c00a968c920a53f5e7935ea8a65fb9ff19ac5  brain/core/guest_view.py
ae62bf6577974f26011a77df7338421c76bc28ad2acce5107aeb80d095f28889  brain/channels/photon.py
3b3933e029836e53f33a13acceabcb9e0564aac65c407e2a50fa8531f9279cc0  tests/test_access_core.py
d150dde16b37a784795f29b9901563495bf606a21b8e32e5dcf8ebe376d0ae69  tests/test_display_projection.py
```

Identity/capability status (source evidence, no new physical claims): existing enrolled device IDs/stable room binding survive reconnect and invitation rotation; current full checks preserve that behavior. Capabilities remain authenticated hello declarations backed by the existing client probes. Mac `say` uses its current audio output: the configured “Room speaker” label does **not** prove a separate external speaker. No new detected role/location/provenance fields or discovery implementation were added; planning owns that contract. Keep host labels/placement distinct from observed facts in its eventual dashboard schema.

Live gate remains with Root/tester on deployed `f228b39`; do not read this source pass as deployed acceptance. Historical physical manual stop PASS and automatic-expiry UNVERIFIED remain separate. Photo/perception stay gated. No human test request was made.
