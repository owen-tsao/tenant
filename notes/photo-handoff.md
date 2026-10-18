# Photo backend → Root / Owen handoff

## Current narrow readiness candidate — October 18

Isolated software candidate: **116 photo component tests +3 dedicated native readiness checks PASS**. Independent final source review found no material defects and confirmed exact final source/patch hashes. Exact owned source/test and composed hashes are in `tests/evidence/2026-10-18-photo-readiness.json`. No staging or commits. This candidate is not deployed or physically accepted.

Changes are limited to host-authenticated `GET /host/photos/config` and safe inventory reasons. The existing capture/upload/ACK/viewer/receipt protocol remains unchanged. `notes/proposed-photo-readiness-wiring.patch` is a one-line Root-owned native inventory proposal, applied only in the disposable software copy. No served phone UI, Mac agent, shared native source, live settings, effects, restart or deployment was touched by this owner. Root retains the live-source gate.

Accepted phone constraint: **QR connection + existing agent backend + explicitly connected phone services; no iPhone Mirroring.** This camera work does not authorize general native-phone app inventory, automation or new adapters. Camera permission never advertises app-control authority. The camera bridge remains the sole implementation scope here.

Remaining: Device Runtime phone handler/consent/upload patch; Audio existing Mac-agent viewer; Root coherent merge/configuration/deploy; Tester actual capture/render/projector acceptance. Older freeze/deployment entries below are historical or Root-attributed.

## Current deployed status — Root report, supersedes older summaries

Current deployed/source revision: `e294e66`. Root reports generic native app/browser discovery with96 focused software checks and independent Audio review. Do not sum this with overlapping earlier suites. The earlier e4b8426/761-check deployment entry below is historical, not the latest revision or a current aggregate count. This owner did not rerun checks or inspect the live deployment.

Fresh ordinary-browser “Japanese Denim” playback was heard after delayed onset: bounded music PASS. The same guest used ordinary Stop/Leave; absence of the exact owned browser tab was verified. Stop response was about36s, so this is not a fast-stop/latency PASS. Reactive visual work remained failed/unperformed beyond the waiting capture; no successful reactive visual result is established.

Photon: the sole LocalTester is preparing one real phone inbound. No Photon inbound/delivery PASS is claimed. Jay resumed E2E; LocalTester exclusively owns live cases, with no competing actions from planning/photo. Older paused/freeze/pending-integration status sections below are historical where superseded here. Product ideas are unchanged. Photo production/test files remain frozen unless Root assigns a concrete failure; no source/UI/tests/effects/research, staging or commits were performed for this notes-only update.

## Historical deployment status — e4b8426

Jay explicitly resumed E2E. Root reports combined revision `e4b8426` published with761 Python+12 Node checks and independent exact-map review, then deployed Brain and audio while the room was quiet. Room8157, the current phone and Mac survived; song capabilities are live. These are Root-attributed results, not checks rerun by this owner. LocalTester exclusively owns finite actual-UI/live cases; planning/photo issues no competing actions or broad duplicate tests.

Device backend state/API is live; optional dashboard presentation remains Owen's work. Root's current web inspection found photo consent, capture/upload and authenticated viewer UI absent. Photo physical E2E is therefore OWEN-BLOCKED, not passed or attempted by this owner; the exact handoff has been reposted by Root. The source/test freeze remains in force unless a concrete failure is assigned. No source edits, service changes or live effects were made for this status update. Earlier live-pause and central-integration-pending summaries below are historical and superseded by this update where applicable.

## Historical freeze hold for central composition

Root assigned additive central software integration to the existing core_access_integration agent. This owner holds all frozen production/test/requirements/patch files stable; notes may be updated. No additional broad reruns without a concrete new finding. Any necessary correction must first be recorded here for Root before editing an overlapping file. Software checks with fakes remain permitted; all E2E/live work, deployment and restarts remain paused. No new source changes or tests were made for this handoff.

## Historical component software freeze — before central integration

Software checks are resumed; live/E2E/public UI/chat/actual model/device/camera/output/deployed-service experiments, restarts and deployment remain paused. This summary supersedes historical pause/pending-status sections below. No photo operation was sent to the live room. No active output/test guest or cleanup exists from this owner. No staging/commits.

Exact owned-file/patch/requirement hashes and composed-source manifest: `tests/evidence/2026-10-17-photo-software-freeze.json`. Independent final source review verified that manifest and found no material defects. Final callback, installer, default-closed metadata fixtures and proposed central composition are software-tested; no final owned source edits remain untested.

Completed on the disposable source copy with mandatory device-awareness + photo wiring applied: **93 photo components +7 dedicated stubbed wiring +52 access/persistence PASS**, zero failures/errors/skips in those batches. Tests used in-process HTTP, temporary private helper sockets and fake model/device/viewer transports only. Broader existing native batch **51/52 PASS,1 failure retained** in the same-guest native interruption/follow-up regression (exact name/expected/actual in evidence). It constructs ConversationAgent without a registry/helper, outside the photo path; Root owns central resolution. No full integrated-suite or physical acceptance claim.

Root merges: (1) device-awareness source + mandatory wiring patch; (2) new photo modules/requirements; (3) `notes/proposed-photo-integration.patch` for Core synchronous reset/revoke/sweep/close, installer, authenticated device consent and private native/CLI photo operations. The photo installer already binds the actual `metadata.camera_ready` callback. **Do not apply the older optional `proposed-device-photo-readiness.patch` on top:** it duplicates the now-owned installer code. Patch shapes remain compatible with the original Owen contract; source revision/identifier/native semantics clarifications are dated below. Root must reconcile against its final concurrent Audio/helper/native-error source; shared central files were not edited by this owner.

Remaining: Root central integration and final combined software gate, dependency installation on deployment, Owen phone/viewer implementation, and live/physical acceptance only when Jay reopens that gate. Projection remains a separate unverified output path. Retention stays latest displayed still through Leave/expiry/new guests until replacement/host reset, with image bytes outside model history. Q-PHONE-SHARE is queued only.

### Frozen owned file hashes

- `brain/core/photos.py` — `83bd615a15f490d4c30c7a35d78b0e8f0b7eee773c93628ccb620e29169a494e`
- `brain/core/photo_image.py` — `e6477dc469c85ad70f9d517ea10d83289bd82f327498bc5bf9bb6ea883d58afe`
- `brain/core/photo_install.py` — `aa08ed9e09b061619f8c697fe02fc414593ae472ecfa8a84e541f5d335ce5c0d`
- `brain/api/photos.py` — `5e4b62ba8c75dc11fe46505bbfd9f91f5fe0bea12beb4d484e093989ec41a6e6`
- `requirements-photo.txt` — `053f79eae479c140adf5f2430e8c711253c522b5dd583977c5d7ea58b8ad5d4f`
- `tests/test_photo_api.py` — `a2b8551ead2a96d7a4d3eca12cd9ec4f3e2391e7d1f89af1743df1f5cf568bce`
- `tests/test_photo_backend.py` — `d66e20aaa99e66a9642754979839fa930f7ec5ba990e0d810f6e735e554b7317`
- `tests/test_photo_image.py` — `6af94477274ef90d7614dd71cf5cd40c81f8e552c316812569ec4144c9a9cbab`
- `tests/test_photo_installer.py` — `3b0468fc5eb01dad4794412580d286b8fa158f13b7105b66f5027a13fc12b54d`
- `tests/test_photo_service.py` — `019ba2de0fd916bc8acb4c92649cfedb850d6f6fbd681c84cf721e00de1b2463`
- `tests/photo_wiring_checks.py` — `3945750f2631651c0044ed4634e02335fd3bfac77f936fd196382ffa52f29fd0`
- `notes/proposed-photo-integration.patch` — `6fbe7d2717fcee9abdfb9cedd028b168cac1e5e8db3ec4b7fa6d041fe4975327`

## Historical work log and published contract

## Historical testing policy — earlier live pause

Jay permits implementation and software unit/component/isolated integration checks using fakes, temporary files and stubbed model/device transports. End-to-end/live trials, public UI/chat, actual models/camera/devices/outputs, deployed-service experiments, restarts and deployment remain PAUSED. Root holds the live gate. Earlier all-testing-paused sections below are historical and superseded by this policy. No staging/commits while sharing checkout.

Device Runtime coordination resolved in the final software-only composition: the real installer binds `metadata.camera_ready = photos.camera_ready`, and the photo owner's direct service fixture now binds the same callback. The old optional runtime lambda patch has been withdrawn/deleted. Final immutable runtime validation4 passes710 Python tests plus16 explicit wiring/queue checks; this includes the current photo source and nonnegative viewer-age correction. Root still must merge the unapplied central hooks; physical/UI acceptance remains paused and unclaimed. Exact source/hash/result record: tests/evidence/2026-10-17-device-awareness.json.

## Historical handoff — full testing pause

Jay explicitly paused all testing after the completed evidence below. No live/UI/device/audio trials, automated runs, new cases, retries, deployment or service restart until Jay resumes. All owned review/test agents were notified. Implementation/read-only review may continue. No test, guest, output or cleanup is active from this owner; all completed tests used fake I/O and closed their local contexts.

Implemented, new files only: brain/core/photos.py (consent, dedup/ticket, exact binding/authority fences, upload staging, matching device ACK, selected viewer/version/receipt, bounded retention/reset), brain/core/photo_image.py (Pillow JPEG validation/metadata removal), brain/api/photos.py (scoped authenticated endpoints), brain/core/photo_install.py (explicit installer), requirements-photo.txt and four dedicated test modules. Pillow13.0.0 was installed only into the development .venv; deployment dependency installation remains Root's step.

Most recent completed evidence BEFORE pause: 15 image tests,25 API tests,4 real HTTP/service/Bus path tests and28 service tests passed individually. An earlier combined photo suite passed69 tests before the last3 metadata service tests were added; no combined72-test run has occurred and none will start during this pause. The service suite includes real metadata host denial, revision/role/heartbeat fences, post-decode races, UNKNOWN/no replay, secret-echo sanitization, Leave/new-guest retention and reset. Original independent read-only review found no material issues in its inspected module revisions; the newer dispatch_allowed/metadata fences/installer still need final review. Initial end-to-end fixture failures were corrected (HTTPS Secure-cookie origin and duplicate-installer fixture);4/4 then passed.

Pending: Root's central installer/lifecycle/same-device consent/native-helper wiring; reconcile the device-awareness Bus feature-gate seam described below; Owen phone opt-in/capture/upload and selected Mac viewer UI; final integrated review and checks only after Jay resumes; then Root deployment and Tester-initiated physical acceptance. No source/physical release PASS is claimed. An unapplied integration patch is now written at notes/proposed-photo-integration.patch, composed on top of the device-awareness proposal in a disposable copy. It is UNVALIDATED: no integrated checks were run after the testing pause. Shared central files were untouched. No staging/commits by this owner.

The photo implementation gate was explicitly OPENED by Jay's parallel-work direction, superseding older planning-only statements for this feature. Physical release remains unaccepted. Perception and automatic physical rules are not opened by this work. Accepted latest-displayed-photo retention remains unchanged.

Owner: local photo backend. Initial exact interface, October 17, 2026. Base HEAD0058cc1; no deployment or physical effects. Implementation below is being built in new files only. Root routes this request to Owen; no other chat was messaged.

## Accepted behavior

Operator explicitly opts the exact enrolled phone into still photos and frames the group locally. Camera/torch OS permission alone does not authorize capture. Current guest asks for one still; same authenticated phone captures/uploads it and the selected authenticated Mac viewer displays it. Keep the latest displayed photo through Leave/expiry/new guests until replacement or host reset. Clear guest context/queued commands on replacement; no image bytes in model history. Host retention setting, gallery and perception are excluded. Mac/projector routing remains a later display operation; this backend establishes actual still → selected Mac viewer.

## Exact phone contract — Owen

After enrolling normally at /ws/device, advertise capability:

```json
{"camera.capture":{"description":"Take one explicitly permitted still","args":{"capture_id":{"type":"string"},"upload_url":{"type":"string"},"upload_token":{"type":"string"}}}}
```

Photo opt-in is a separate local switch, initially OFF on every page/socket load. Once the chosen existing preview stream is live, send on that SAME authenticated device socket:

```json
{"type":"photo.consent","enabled":true,"ready":true}
```

Opt-out/stream failure: send enabled:false,ready:false (or enabled:true,ready:false if still opted in). Root routes only this frame to service.device_event(dev,frame), replies with its returned frame `{type:"photo.consent",ok:true,revision:N,enabled:bool,ready:bool}`. Repeating identical state is idempotent. State change/reconnect invalidates pending work. No arbitrary source ID is trusted in consent frames. Device must locally recheck consent immediately before shutter.

On normal `do` for camera.capture, args contain capture_id, same-origin upload_url and private upload_token; do not log/show them or include them in model replies. Respect deadline_ms and epoch as for other device actions. Use the existing chosen preview stream, take ONE JPEG frame; no lens switch, competing stream or automatic retry. POST raw image/jpeg bytes to upload_url with Authorization: Bearer upload_token. Bound:5MiB input,16million decoded pixels. After upload returns ok, ACK through the existing device result path:

```json
{"type":"ok","req":"BUS_REQ","result":{"capture_id":"CAPTURE_ID","state":"captured"}}
```

On denial/failure use existing err req/code/message. A repeated do/capture_id must return its recorded outcome without another shutter. UNKNOWN must not recapture. Upload success is storage staging, not a claim of Mac rendering. Capture/upload and matching phone ACK are both required before viewer publication. Keep the previous displayed image on failure.

## Exact host/viewer HTTP contract — Owen

All JSON mutations require approved same-origin Origin. Host endpoints additionally require normal Authorization: Bearer HOST_TOKEN. No host token is placed in URLs. Root includes the new router before the static mount.

1. `POST /host/photos/config` body `{source_device_id:"PHONE_ID",viewer_id:"mac-main",enabled:true}`. Exact fields; IDs1–128 chars. enabled:false revokes new capture/publication. Changes fence pending work, preserve the existing displayed photo. This binds photo-specific source/viewer roles without editing device identity persistence.
2. From the actual intended Mac viewer browser: `POST /host/photos/viewer` body `{viewer_id:"mac-main"}` with host authorization. Server sets private HttpOnly SameSite=Strict cookie `tenant_photo_viewer`, Path=/photos, Secure on HTTPS. Re-enrollment replaces the viewer binding, invalidates pending work and old cookie. No credential comes back in JSON. Response `{ok:true,viewer_id:"mac-main"}`.
3. `GET /photos/viewer/state`, cookie required, no-store. Poll about every second; this also establishes selected viewer liveness (15s window). Returns `{ok:true,version:N,photo:null|{photo_id,image_url,captured_at,source_label,version},pending:bool}`. `version` increases on replacement/clear/invalidation. The photo is either the authorized current candidate or the latest actually render-confirmed still; no public /ws/display photo URL is added. Keep the old visible image until new image successfully loads. Discard any old-version load finishing after a newer state/clear. A null state clears only when it represents an actual newer host reset/absence, not a transient request/network failure. Guest ending cancels a pending candidate, not the accepted displayed photo.
4. `GET /photos/images/{photo_id}` uses the same viewer cookie; returns normalized JPEG only for that selected viewer's currently allowed candidate/latest. No-store/nosniff; an opaque URL alone never grants access. Do not fetch remote URLs.
5. After actual decode/render of the exact photo, `POST /photos/viewer/receipt` body `{photo_id:"...",version:N}` using viewer cookie. Matching current authenticated viewer + current candidate required; first valid receipt promotes it to latest displayed. Duplicates for the retained latest are idempotent even after guest ending. The software receipt is not physical screen evidence. Reset invalidates old images/receipts and broadcasts via state polling a newer null version.

## Guest / native integration — Root

- `POST /photos/captures` body `{guest_id,request_id,source_device_id}`, original per-guest HttpOnly cookie required. Exact current active lease, camera.capture + photo.show scope (or *), controller/generation, source consent/connection, host source/viewer roles and live selected viewer required. No activation/renewal by this route. Response is safe status only, never ticket/image URL/bytes.
- `GET /photos/captures/{request_id}?guest_id=...`, same guest cookie, returns that request's safe status. Pending, captured, stored and displayed are distinct. Duplicate immutable request IDs never create another ticket/shutter; conflicting reuse fails. UNKNOWN is never replayed.
- Native helper should invoke `await core.photos.capture(lease,request_id,source_device_id,generation=grant.generation)` through its existing authorized turn path; no shell HTTP host bypass and no model-visible upload token. New scoped native operation/inventory wiring is a narrow Root integration task; this owner does not edit native_devices.py. `core.photos.inventory(lease,generation=...)` returns safe readiness only.
- Bind service's current-controller authority callback to `core.agent.allows_program(lease,generation)` in native mode; fail closed if controller changes. Non-native tests explicitly supply a callback. Never use a caller-supplied generation as authority. REST adapter derives generation from the current server agent.
- Root instantiates PhotoService and installs the router; see proposed integration patch after tests. Route photo.consent via the actual authenticated device object, call photos.sweep() from sweep, photos.invalidate_guest(guest_id) on revoke, and synchronous photos.reset() immediately after lease reset BEFORE any await in host reset. Only explicit host reset clears latest; room.epoch changes from ordinary Leave do not clear it.
- No photo bytes/credentials enter transcript/log/model history or public state. Source labels are human-facing only. Service uses exact enrolled Device object + socket, current cap schema, consent/role/viewer revisions, lease object, epoch and controller generation as fences. Runtime metadata owner can route host photo role changes through configure; do not invent physical identities.

## Library / review / evidence

Image normalizer, backend, routes and dedicated tests are being implemented separately. Final tested hashes, independent review, dependency version and remaining integration/physical gates will be appended here. No source PASS, deployment or physical success is claimed by this initial contract.

## Compatibility addendum — October 17, implementation in progress

The initial phone/HTTP wire shapes above remain unchanged. Source/request/viewer identifiers are ASCII letters/digits plus `_-.` (1–128 chars); generated capture IDs already meet this. Error codes from devices are whitelisted before safe status; arbitrary device code/message text is never copied to model/guest status.

Native integration adds optional `dispatch_allowed` to capture(), checked at actual Bus dispatch after queue waits. Root passes the exact native grant/connection check there. Once a request has been dispatched, image validation/render confirmation may complete while that SAME guest/controller generation/lease remains authorized, even after its originating native turn finishes; a finished turn is not permission to transfer the request to another guest. Revoke/expiry/new controller/epoch/source/consent/role/viewer changes still fence commit. This allows a natural final reply while Mac rendering finishes without extending authority.

Device Runtime's new metadata interface was read: binding(device_id), revision/guard, and host allowed are used as necessary source checks. PhotoService snapshots metadata.guard({source_id}) at admission and checks it through validation/rendering, so metadata edits cancel pending photos. configure() defines the explicit photo roles; a generic device role never grants consent/viewer/guest permission.

**Integration collision to resolve before enabling:** the unapplied device-awareness patch makes Bus call metadata.available(), while the metadata owner's blocked_reason currently always blocks camera.capture as not enabled. Preserve that raw/public gate; do not simply advertise camera.capture globally. Root/device owner must distinguish transport binding/host-policy availability from guest-facing feature availability: the photo service supplies its own required consent/viewer/lease dispatch policy, while ordinary raw helper calls still omit camera.capture. The final proposed photo patch will show the small required metadata/Bus seam, for Root to coordinate with the runtime owner. Do not deploy a photo backend behind an unconditional camera dispatch rejection.

## Post-pause implementation addendum — NOT EXECUTION-VALIDATED

The metadata owner has now supplied `registry.metadata.camera_ready = callback`, default false. PhotoService.camera_ready(dev) checks configured host allowance/source, exact live binding and photo consent, plus the selected authenticated viewer's liveness; it does not claim guest authority. The installer attaches this callback. This resolves the earlier unconditional-camera rejection collision without a metadata/Bus source edit. Full photo-specific guest/controller/epoch/revision checks remain in the Bus authorization callback. Neither this new callback nor its final composition has been tested after the pause.

`notes/proposed-photo-integration.patch` is a narrow UNAPPLIED proposal for Core sweep/revoke/reset/close, explicit installer, actual authenticated source WS photo.consent routing, and native helper/CLI operations. It is composed against the concurrent device-awareness patch, not bare HEAD; Root must merge the small hooks with its final integration source. No web or shared runtime source was edited by this owner.

Native exact operations proposed in the patch: `photo-capture {request_id,source_device_id}` and `photo-status {request_id,capture_request_id}`. The status request's own request_id is distinct from the original capture_request_id, so existing helper deduplication can safely cache each operation. Photo capture uses the existing long helper deadline; raw camera.capture is still not in ordinary CAPABILITIES. Native grant/connection is checked after queue waits. An uncertain source is added to that native turn's unknown-device set, preventing a fresh-ID recapture in the same turn. Image tickets/bytes never reach native helper replies.

Dependency: `requirements-photo.txt` pins Pillow13.0.0, installed only in the development .venv. Primary references used by the image owner: https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html ; https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg ; https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose ; https://pillow.readthedocs.io/en/stable/reference/Image.html . JPEG is fully decoded before fresh RGB encoding; EXIF orientation is applied, metadata removed, input/output each5MiB and decoded pixels16million bounded. Strict single-JPEG envelope rejects concatenated/trailing data. No durable album or image-model history was added.

Final source-only independent review during the testing pause found no material defects in the updated service, installer or unapplied integration patch. No code execution/tests were performed. Exact current source hashes and completed pre-pause component evidence are recorded in tests/evidence/2026-10-17-photo-backend.json; the manifest is explicitly NOT an executed final-source validation. Testing remains paused, central/UI integration and physical acceptance pending. No cleanup is active.

## Software composition progress after resume

Final callback/installer and direct fixture compatibility are software-tested. In a disposable copy with mandatory device-awareness + proposed photo wiring applied:93 photo component tests PASS,7 dedicated stubbed native/device/HTTP wiring checks PASS,52 existing access/persistence tests PASS. Every model/device/viewer transport is fake/in-process; no live/public UI or physical effects. Existing native regression batch:51/52 PASS, one failure retained at test_native_terminal_events.NativeTerminalEventsTests.test_confirmed_interruption_allows_only_next_explicit_request_without_old_tool_replay, which expected Fresh request completed. but received the generic unconfirmed-result reply. That test constructs ConversationAgent without a registry/device helper, so photo wiring is not on its execution path. Root owns native-error source; this owner did not edit it or hide the failure. Exact frozen composed-source hashes are in tests/evidence/2026-10-17-photo-freeze-candidate.json. No full integrated-suite or physical PASS is claimed.

## October 18 — narrowly authorized backend/device completion candidate

Jay authorized completing the existing photo path without a new service or layout. This supersedes the source hold only for assigned backend/readiness/config glue. Device Runtime owns the unapplied nonvisual phone runtime patch; Audio owns the existing Mac agent/viewer; Root owns central/native glue and active integration. This owner performs isolated software checks only, with no live API/UI/camera/output, staging, commits or restart.

Backend pipeline remains the original one: source photo.consent → camera.capture over the existing Bus → one-use ticket upload → JPEG validation + matching phone ACK → selected authenticated viewer → exact versioned render receipt. The previously observed live PERMISSION and light-only phone are a pre-dispatch capability/readiness failure, not proof that iOS rejected capture. We have not inspected or changed current in-process host settings. New host-only GET /host/photos/config reports those exact settings and separate blockers, without enrolling/activating a viewer, enabling capture or refreshing viewer liveness.

### Client contract kept stable

Phone: advertise the existing camera.capture schema exactly (`capture_id`, `upload_url`, `upload_token`: strings). Send photo.consent only from the actual enrolled socket, after separate explicit photo permission and a live chosen camera stream. Opt-out/stream loss emits false readiness; OS torch permission does not imply photo opt-in. Capture one frame from that stream on a permitted do, upload same-origin JPEG with ticket Bearer, then ACK `{capture_id,state:"captured"}` on the matching Bus req. Do not advertise capture before the handler exists or claim ready after permission is denied. No guest/host token, image bytes or ticket appears in public output.

### Root setup and smallest existing Mac-agent viewer protocol

1. Root reads GET /host/photos/config with ordinary Host Bearer plus the exact approved Origin. This reports factual enabled/source/viewer values and blockers rather than inferring them from PERMISSION. Host settings remain transient; a Brain restart starts disabled/unselected. No identities are created by this API.
2. Root selects the actual enrolled source phone and intended existing Mac viewer using unchanged POST /host/photos/config `{source_device_id,viewer_id,enabled:true}`. Use the real Mac/session identity as the viewer label; a room label/tool name does not establish a peripheral. No guest-facing control grants host setup authority.
3. Audio's existing Mac agent, explicitly supplied its private host credential, calls unchanged POST /host/photos/viewer `{viewer_id}` with Host Bearer + approved Origin. Keep returned tenant_photo_viewer cookie only in its private HTTP client jar. No new authentication transport or service is required.
4. Subsequent GET /photos/viewer/state, GET its same-origin relative /photos/images/{photo_id}, and POST /photos/viewer/receipt use that cookie and **omit Authorization**: viewer routes intentionally reject Bearer. Receipt also sends the exact approved Origin. Do not leave Host Bearer in default headers on those requests. Poll about1s (must remain inside15s liveness). A failed poll is not a new grant or an instruction to capture again.
5. Decode the normalized JPEG and use the existing Mac viewer/application to show this exact image. If a temporary local file is needed for the native app, keep it private/bounded, never return its bytes/path/credentials to model/guest history, and let Audio own cleanup of only that exact artifact. Backend retains no disk album. Only send `{photo_id:photo.photo_id,version:photo.version}` after verified actual decode/render; a successful open command alone is not that verification. Until then status is received/display-unconfirmed.
6. Respect monotonically newer state/clear versions; reject late old-image loads. Leave/expiry/new guests retain the latest displayed image. Explicit host reset clears it; the Mac client clears the exact owned viewer/image on the newer null state. Re-enrollment replaces the viewer credential, so discard old in-flight requests and reset client-side version bookkeeping for that new authenticated session. No automatic recapture or migration to another viewer.

The agent gets authoritative safe status/reference through existing photo-capture/photo-status; it does not receive image bytes or upload/viewer credentials. Existing Mac tools can access the visible viewer as permitted. This does not implement perception/history embedding.

### Readiness addition and narrow Root merge

GET /host/photos/config is additive and host-only. It returns enabled/source_device_id/viewer_id; source enrollment, current connection, host allowance, capture schema, separate photo consent and camera readiness; viewer registration/liveness; pending; ready; and explicit blockers. Host technical readiness is not guest authorization. Native inventory adds a reason and truthful message, preserving source ID/label only when guest-authorized and ready.

Root's proposed one-line native inventory merge will expose the existing safe photos inventory even while disabled, so a natural request can discover a concrete missing prerequisite rather than invent a camera or misreport an OS denial. It does not enable capture or grant new scope. No central file is edited by this owner. Final isolated checks, independent review and hashes will be appended before freeze.

### October 18 final diagnostics validation

The first 116-test run found one installer regression: the new inventory explanation rechecked controller authority after an initial denial. Final inventory checks controller authority once, retains active/current lease and both photo scopes, source/viewer blockers and the existing lease-device allowance. No test expectation was weakened. Final rerun:116/116 PASS; dedicated readiness helper checks:3/3 PASS; source whitespace check clean. Independent read-only final review found no material defects. No broader aggregate or physical PASS is implied.

Host diagnostic request: `GET /host/photos/config`, existing Host Bearer plus exact approved Origin, no query/body. Response contains selected IDs, enabled, source connection/schema/explicit consent/camera readiness, viewer registration/liveness, pending, ready and blocker codes. It does not enable photos, create an identity, enroll/heartbeat a viewer or activate guest access. Safe native inventory exposes no source ID/label unless currently guest-authorized and ready. Full manifest: `tests/evidence/2026-10-18-photo-readiness.json`.

## October 18 — current native camera route; supersedes earlier QR-only preference

Root reports Jay now prefers no phone browser QR and accepts the existing Mac gateway/native apps. Browser photo roles remain disabled/held; the earlier QR-only/no-Mirroring preference above is historical. Root reports actual paired-iPhone Mirroring Clock navigation passed, but Apple excludes camera/microphone from Mirroring. Existing Photo Booth selected the actual paired iPhone through Continuity Camera and showed a real room feed after Jay locked/mounted the phone sideways: native feed PASS, attributed to Root/Tester. Focus changes repeatedly paused Photo Booth. One shutter attempt has UNKNOWN saved-image outcome; protected Photo Booth library metadata returned OperationNotPermitted. No bypass, old-photo inspection, verified saved still, or projector PASS follows from the feed result.

Tester exclusively owns the current guest, live UI/camera/capture/display continuation and cleanup. Root has authorized the existing FFmpeg fallback within that finite case, with exact iPhone source, finite timeout, private new output file and actual display verification. This owner remains read-only for devices/UI; no camera open, capture, app launch, install, wrapper/server/adapter/library, source change, deployment or commit was performed in this assessment.

### Installed asset and finite read-only evidence

- `/opt/homebrew/bin/ffmpeg` resolves to `/opt/homebrew/Cellar/ffmpeg/9.0.2_1/bin/ffmpeg`; `-version` reports FFmpeg9.0.2, libavdevice63.1.102. Installed `-h demuxer=avfoundation` confirms AVFoundation input, device listing, name/index selection, frame-rate, size and pixel-format options. Only version/help, binary linkage/section metadata and installed manual text were inspected; device enumeration was NOT executed.
- Matching n9.0.2 release source explicitly includes `AVCaptureDeviceTypeContinuityCamera` in macOS14+ discovery. The installed binary reports macOS26 minimum deployment target. This establishes a supported candidate, not that this process currently sees or can open the paired phone. Release source: https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/libavdevice/avfoundation.m#L704-L755
- This installed release lists localized camera names and indices and selects by name/index. It does not expose the newer `video_device_id`/unique-ID options present in current online documentation. Name matching in release source accepts prefixes, so use the complete unambiguous paired-iPhone name, never `default`, an assumed index, the built-in Mac camera, Desk View or a screen capture. Tester must match a fresh listing to the already-observed paired iPhone; absent/duplicate/ambiguous names are a stop, not permission to guess. Release-specific listing/selection source: https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/libavdevice/avfoundation.m#L779-L911

Smallest supported workflow for Tester only, after Root release; neither command was run by this owner:

```sh
/opt/homebrew/bin/ffmpeg -hide_banner -f avfoundation -list_devices true -i ""
/opt/homebrew/bin/ffmpeg -hide_banner -nostdin -n -f avfoundation -framerate 30 -i "EXACT_IPHONE_CAMERA_NAME:none" -frames:v 1 -update 1 "/absolute/private/writable/path/new-capture.png"
```

Use a fresh private writable path and retain the finite case timeout. `none` excludes microphone input; `-frames:v 1` saves one frame from a briefly opened camera video stream. This is not a full-resolution iPhone still shutter, phone photo-library operation or continuous recording deliverable. A one-frame output limit is not a wall-clock limit: release source waits for an initial frame, so Tester must stop a stalled process within its existing case deadline. FFmpeg device documentation: https://ffmpeg.org/ffmpeg-devices.html#avfoundation ; output frame-limit documentation: https://ffmpeg.org/ffmpeg.html#Video-Options ; image output documentation: https://ffmpeg.org/ffmpeg-formats.html#image2-2

### Permission and acceptance boundary

Actual launching-process/application macOS Camera permission is UNMEASURED. Photo Booth's access does not demonstrate permission for FFmpeg's actual launch context. An OS request/denial must remain visible and be handled through normal user authorization; this assessment does not grant access or alter privacy settings. Apple documents per-app Camera controls and built-in Photo Booth's automatic access: https://support.apple.com/guide/mac-help/control-access-to-your-camera-on-mac-mchlf6d108da/mac

Keep the same paired iPhone locked, stable, mounted and nearby. Apple documents Continuity Camera positioning and pause/disconnect behavior: https://support.apple.com/en-us/102546 . Avoiding Photo Booth's foreground UI is a reason to test this existing CLI, not proof of steadier capture. Source identity, successful new-image decode, and actual display of that exact new image remain Tester's verification gates. No physical capture/display/projector success is claimed by this read-only assessment. Handoff frozen after this notes-only update; no further work started.
