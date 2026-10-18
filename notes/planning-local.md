# Tenant — local feature planning

## Current freeze hold and demo steering

Root's existing core_access_integration agent now owns additive central integration. Keep the photo production/test freeze stable; notes only unless a concrete necessary correction is first recorded for Root. No additional broad reruns, staging, commits, restarts or deployment. E2E/live remains paused.

Jay rejects the band/album-cover idea. Creative multi-device exploration remains interesting, while reliability means the main demo should not depend on it. This is recorded in demo-ideas.md as product/demo selection guidance, with no request to build additional features.

## Strategy capture — vision and customer hypotheses only

Jay's customer candidates are hotels, hospitals, Airbnb/short-term-rental operators, shared spaces and event/demo teams. No single buyer or willingness to pay has been validated. These remain candidates for exploration rather than an accepted customer focus or evidence of demand.

Jay sees Tenant as infrastructure for future scalable, multimodal AI coordination, with future-compatible capabilities and space integration. Preserve that thesis as vision; it does not establish an existing moat, demonstrated scalability or currently implemented model independence. Root owns the ongoing positioning/defensibility discussion and current decisions in jay.md. No new hotel/hospital/PMS/device or other integrations/features are authorized. This note-only capture leaves the frozen production/test files unchanged.

## Final photo software handoff

Photo backend and exact source freeze are ready for Root integration:93 photo components,7 stubbed wiring and52 access/persistence checks PASS; independent review clean on exact hashes. One broader native-terminal regression failure remains recorded for Root, so no whole integrated-suite PASS is claimed. Exact module/test/patch/requirements manifest and remaining UI/central/live gates: notes/photo-handoff.md and tests/evidence/2026-10-17-photo-software-freeze.json. Software tests allowed; E2E/live remains paused. No active output or cleanup; no staging/commits.

## Current policy — software checks resumed; live gate held

Jay permits implementation and software unit/component/isolated integration checks using fakes, temporary files and stubbed model/device transports. End-to-end/live trials, public UI/chat, actual models/camera/devices/outputs, deployed-service experiments, restarts and deployment remain PAUSED. Root holds the live gate. Earlier all-testing-paused sections below are historical and superseded by this policy. No staging/commits while sharing checkout.

## Current photo implementation handoff — testing paused

Jay opened this specific photo feature for parallel implementation, superseding the older planning-only/photo-gated passages below. New photo service, JPEG normalizer, scoped HTTP routes and explicit installer are implemented separately; exact UI contract and current progress: notes/photo-handoff.md. Central integration/native/device wiring is pending, all web/source-reference files remain read-only, and physical acceptance is not claimed.

Jay has now paused ALL tests. No automated/live/UI/device runs, new test cases, retries, restarts or deployment until he resumes. Review/test agents notified; no test/output/guest or cleanup is active from this owner. Before pause: image15/API25/end-to-end4/service28 tests passed individually; earlier combined69 passed before3 final metadata cases, so a combined72 PASS is NOT claimed. Final review of the newest fences and final integrated validation remain pending. The narrow integration patch is now written at notes/proposed-photo-integration.patch after source-only adaptation to the metadata camera_ready hook; it remains unapplied and UNVALIDATED during the pause. No shared integration files were edited. No staging/commits.

Accepted initiative preference from Jay via Root: use context judgment to choose a concrete useful suggestion or a simple capability notice; lean toward concrete suggestions for the demo. A suggested action waits for yes. Discovery grants neither effects nor speech. Earlier two-minute/two-per-guest numbers are unapproved tuning proposals, not accepted constants. Root owns central suggestion coordination; this adds no suggestion implementation to the photo task.

Owner: local planning. Updated October 17, 2026, 19:58 PT.
Read-only source inspected: HEAD `f228b39963958bc2911b13f8e933ae5aeb4d800d`, the five requested notes, registry, display publisher, native helper and architecture. No service, device, output, volume or web changes were made. This file is a proposal, not a shipped interface or an acceptance record.

## Outcome and limits

Make newly available tools useful through one evidence-backed device inventory: discover → reconcile identity → clarify missing role/location/permission with the host → publish truthful availability → accept a natural guest request → recheck authority at dispatch → report the actual result → update the dashboard. Use existing MCP/adapter tools; do not start a new integration program. Music stays with Audio.

The handoff reports deployed `f228b39`, independently reviewed 484 Python + 12 Node checks. Planning inspected that source revision but did not rerun those checks. Reply mode is text by default; ongoing voice requires the current guest's explicit choice of the exact available speaker. Discovery does not enable speech. One-off requested speech remains independent.

Latest Root steering: local tester exclusively owns the live `f228b39` gate. Actual native default-silent check passed `TEXT_DEFAULT`, zero `say` dispatches (Root report; no new physical evidence from planning). Core owns the bounded public display conversation projection and truthful TTL denominator; these are separate from this device contract. No competing human questions/tests and no staging or commits until Root coordinates.

Manual phone OFF while beat continues, followed by a separate beat stop, has physical PASS at `0b4a1ec`. Current program expiry is physically UNVERIFIED; the earlier run was interrupted. Physical synchronization, fullbeat cadence, Photon delivery and native window visibility have no new acceptance from this planning pass. Photo, perception and proactive implementation remain gated.

## Smallest host / device / dashboard contract — proposed

Use the existing registry as the authority and the existing state publisher as its display projection. No new device framework, separate discovery UI, endpoint or public frame is required for this plan. Root must update ARCHITECTURE before implementing any additions below; Owen owns all web work.

| Internal field | Required meaning |
| --- | --- |
| `stable_device_id` | Room-scoped persistent identity, independent of invitation code, guest, socket and tool-session handles. Preserve the existing enrolled `Device.id` where its continuity is established. |
| `bindings` | Private adapter/provider namespace plus stable resource key, current connection generation and last observation time. Existing enrolled endpoints may use their persisted enrollment identity. A tool name alone is not a physical device key. |
| `label`, `role`, `location` | Human label; task role such as room light, capture source or room display; optional placement. Missing values stay unknown. Host supplies only facts tools cannot establish. |
| `provenance` | Per field: `detected` with provider/resource observation and time, or `host_specified` with host assertion and time. A host label must not relabel a guessed capability as detected. Private identifiers remain private. |
| `connection_state` | `online`, `offline` or `unknown` from the bound endpoint's actual liveness. Stale discovery is unknown/unavailable, not online. Reconnect retains identity but replaces the connection generation. |
| `available_capabilities` | Capability name, private callable binding/schema, status `available` or `blocked`, reason, observation time and provenance. Preserve blocked evidence for host understanding, but publish only usable capabilities in the guest's controls. |
| `permissions` | Host device-use allowance, device/operator consent and per-guest scope remain distinct. Discovery grants none of them. Existing lease/epoch/dispatch policy stays authoritative. |

Availability means a discovered callable/resource is currently bound, the required endpoint is online, its relevant device permission/consent is valid, the feature gate is open, and host policy permits use. A guest can use only the intersection with that guest's current grant. An exposed tool schema establishes a possible operation; it does not establish the physical device, present permission, success or a measured effect. Descriptions and device labels are data, never agent instructions.

### Identity and reconciliation

1. Observe tools/resources already exposed by the connected MCP provider or existing adapter. Perform only read-only discovery; do not call effects to prove presence. Store the exact resource evidence and current binding privately.
2. Match the provider/resource key or authenticated persisted enrollment to an existing room identity. Reconnect changes liveness/capabilities, not identity, label, original guest expiry or permissions. Invitation rotation does not create another device.
3. If evidence cannot distinguish endpoints, retain the endpoint identity and mark the physical attribution unknown. Ask the host only the missing factual question when a task needs it, for example which enrolled phone faces the whiteboard. Do not merge two records from matching labels, IP addresses or capabilities. Do not split a Mac into speaker, projector and camera merely because Mac tools exist.
4. Persist identity-to-binding and host metadata independently of transient availability. Fail closed on uncertain binding or failed identity persistence; do not claim continuity or route a command using a guessed match. A retired or re-enrolled identity is not automatically merged without evidence. A newly observed tool never restores an expired grant.
5. Publish changes when observed and on disconnect/reconnect. Recheck exact target, connection generation, capability, consent and guest authority after any queue wait, immediately before dispatch. UNKNOWN retains its no-replay/no-substitution rule. A new explicit action is distinct from retrying an uncertain one.

| Observed evidence | Honest room inventory |
| --- | --- |
| Existing authenticated Mac bridge with `say` / music tools | One Mac endpoint with the observed capabilities. Its selected output can be an attribute. |
| Host says the Mac currently plays through a Bluetooth speaker; no separate resource/control evidence | Host-specified output description attached to the Mac; no independently controllable speaker card. Do not change the output to investigate. |
| Provider exposes a distinct persistent speaker resource and a current callable binding | Distinct speaker identity may be recorded, with its exact supported operations and permissions. Merely knowing a Bluetooth name does not prove control. |
| Enrolled phone reconnects with the same authenticated persisted identity | Same phone, updated liveness/caps; no duplicate card or new guest authority. |
| Mac has a display tool, but no identified projector/output resource | Mac display capability only. Preserve projector as an idea; do not announce one as found. |

### Host clarification and publication

The host sets a missing label/role/location or allowed use through the existing host setup flow when Root defines its authenticated seam. A role never manufactures hardware support or guest authority. Revoking permission updates controls immediately and invalidates queued actions; already-dispatched outcomes remain explicit. Host metadata must survive ordinary reconnect. OS/device permission prompts stay on the device that owns them.

The smallest additive display proposal keeps `devices[].id/label/caps/online/busy/last_action` compatible and adds optional `role`, `location`, `connection_state`, field-level `provenance` (public summary only), and `capability_status: [{label,status,reason}]`. `id` is the stable public alias, not a second identity. Do not expose adapter resource keys, credentials, paths, raw schemas or audit history. Guest lease controls still contain only current permitted labels/caps; they are not the host inventory. A device row can be online while its camera is permission-blocked.

Owen can use the existing Device / Can do / State / Last action table. Plain sentences such as “Camera off” or “Location supplied by host” suffice; details can stay one tap away. The dashboard shows detected and host-specified facts distinctly and never converts a request into a success dot. This proposal does not ask for a redesign.

## Photo finale — minimal capture → viewer contract, gated

One enrolled room phone faces the team and judges by the whiteboard. The operator manually frames the group on that phone; everyone knowingly poses. The current guest asks the same Tenant agent for one still. The Mac shows the actual new image. No face recognition, continuous upload, tracking, camera-derived triggers, front/back switching or new camera provider is required.

### Roles, opt-in and readiness

- Host identifies the exact enrolled phone as `capture_source` and the exact existing Mac viewer as `photo_viewer`. Use source identity and viewer identity separately; a viewer is a display session on the Mac, not evidence of a separate physical monitor/projector. Bind the selected viewer through authenticated host authority to its current display connection. An untrusted client-supplied viewer ID cannot select a target or attest display. Changing either assigned role invalidates pending captures.
- On the phone, the operator explicitly enables “Allow room photos” and sees the selected camera's local framing preview. OS camera permission alone, including permission already used for the torch, is not photo consent. Do not advertise `camera.capture` until both permissions are valid, the preview stream is live and the feature gate is open.
- The operator chooses/frames the existing camera locally before readiness. Do not open a competing camera stream or switch lenses during a request. If torch/camera contention cannot be ruled out by the existing adapter, return blocked and offer a choice; do not stop a performance silently. Disabling photo consent revokes capture only; release camera resources only when no permitted torch/camera use needs them.
- “Ready to take a photo” requires source readiness, current consent revision, host allowance, current guest capture scope and the selected viewer online. Host role assignment does not grant camera or guest permission. A disconnected/reloaded camera must reestablish readiness and consent; stored OS permission is insufficient.

### Request, commit and result

| Step | Proposed minimum contract |
| --- | --- |
| Authorize | Agent supplies unique request ID and exact source ID for `camera.capture`; the server binds it to current guest/grant, room generation/epoch, connection generation, consent revision, role revision and exact authenticated viewer. Keep a bounded request record through the originating grant's lifetime plus any unresolved dispatch deadline; duplicate ID with identical parameters returns existing state, conflicting reuse fails, and UNKNOWN never dispatches again. No arbitrary destination URL or upload path from the model. |
| Prepare | Server reserves one pending capture per room and issues one opaque, short-lived upload ticket for that request/source. Proposed fixed bound: 30 seconds, additionally capped by the guest's remaining authority. Keep the previous photo visible. The phone visibly signals capture; optional countdown is local and within the same deadline. |
| Shutter | Phone checks current consent, request validity and live source before taking exactly one frame. Server checks authority before dispatch; phone cancels on an observed cancellation. Late revocation cannot undo an already-taken frame and must not be described as cancellation of the shutter. |
| Upload | Device-bound one-use ticket, exact capture ID and same-origin upload. Proposed bounded format: JPEG, at most 5 MiB and 16 million decoded pixels; server validates/decodes and removes metadata before publishing. Root selects final limits before implementation. No arbitrary remote fetch. A duplicate ticket cannot cause another capture or another commit; return its existing result where known. |
| Commit | Immediately before atomically replacing the current photo, recheck guest/grant/expiry, room generation, current host source/viewer allowance, unchanged role assignments, source connection/consent revision and selected authenticated viewer readiness. Reject late or stale uploads. The old photo stays on failure. At most one latest image and one bounded pending image live in memory; no disk/archive/gallery. |
| Display | Publish `room.latest_photo = {photo_id, image_url, captured_at, source_label, version}` or `null` only to the authenticated selected viewer's state projection, independently of ledger rows. Other/public displays get at most a status sentence, no image URL/bytes. The same-origin opaque image URL additionally requires that viewer's authorization; opacity alone is insufficient. `version` includes the room generation and increases on replacement/clear. After successful decode/render, accept a `photo_id/version` receipt only from the bound viewer's current authenticated connection. A host-authenticated reconnect rebinds that viewer and fetches current state, never repeats a shutter. |
| Receipt | Track `captured`, `stored` and `displayed` independently for the same capture ID. A phone ACK or upload success cannot claim “shown on Mac.” Before viewer evidence say “Photo received; display unconfirmed.” A viewer receipt proves software rendering only; the exact real Mac/group-image observation remains a physical check. |

Use the current device result path for capture outcomes and the existing display publisher with a selected-viewer-only projection for the image; names above are proposed fields, not implemented routes/frames. The current public display state must not simply acquire an image URL for all listeners. The architecture's generic `/upload` and `ok.result.image_url` sketches are insufficient authorization and viewer-receipt contracts. Root and Owen must agree authenticated viewer enrollment, exact upload/ticket and viewer-receipt seams before code; no guest-wide unbound upload route is implied.

### Ending access, reset and uncertain outcomes

Leave, expiry and revoke invalidate pending captures/tickets; already-dispatched shutter outcomes can remain uncertain. A late image cannot become a new display effect after authority ends. UNKNOWN means report uncertainty and do not recapture or select another source automatically. An explicit later request needs fresh authority and its own ID. No queued capture transfers to the next guest.

**Accepted retention policy — Jay’s 19:17 direction, confirmed by Root.** Keep the latest displayed photo after Leave until replacement or explicit host reset. Ordinary expiry/revoke and a new guest do not automatically clear that physical displayed photo. A new guest resets agent working context and pending commands only; keep image bytes out of model history. Future host-configurable retention stays deferred. Retention is settled and needs no further Jay question. Root must supersede ARCHITECTURE’s older ten-minute photo TTL when implementing this accepted policy; that documentation correction is not a decision blocker.

Host reset revokes first, changes room generation, invalidates pending tickets, clears the photo and broadcasts a newer null version. Old image URLs stop serving bytes, and a late upload/render acknowledgment cannot restore them. Viewer must discard a prior-version image fetch that finishes after a newer clear. Software clear confirmation and physical screen clear remain separate. Already viewed/downloaded pixels cannot be recalled. No persistent album or durable recovery after process failure is promised; a reconnect/restart is not itself an authorized host reset and must not automatically blank a still-displayed photo.

## Concise feature request for Owen — ready for Root to route

“Please keep the current room table and show each evidenced device's role/location, connection state, usable capabilities and whether a fact was detected or supplied by the host. Root will provide optional additions to existing state; keep IDs/tool details out of visible copy. A Mac output description is not another controllable speaker. Do not add camera claims while gated. Once Root opens photos and supplies capture/upload plus viewer-receipt seams, add explicit photo opt-in and local framing on the assigned phone, then show the committed latest photo on the assigned Mac with honest loading/failure state and a matching render receipt. Keep the judges/team whiteboard finale and the latest displayed photo through Leave and new guests until replacement or host reset. New guests clear agent context/commands, not the displayed photo; keep image bytes out of model history. No new retention setting or redesign.”

Not sent to Owen or any other chat. This is the bounded UI request; backend identity, consent/ticket validation and permission enforcement belong to Root/device owners.

## Evaluation and readiness — owner-run, no new human checklist

The local tester initiates experiments automatically once Root authorizes a ready capability. Humans only confirm actual visible/audible outcomes that software cannot establish. Do not force an unbriefed rehearsal or restart the manual stop trial. Preserve `demo-testing.md` as the shared acceptance record; the exact proposed amendments below have not been applied there.

| Check before exposing the capability | Evidence required / current state |
| --- | --- |
| Device identity continuity | Automated fixture: duplicate labels remain separate; reconnect/rotated invitation retain one ID; changed connection invalidates queued bindings; missing persistent key stays unknown. PROPOSED, not run. |
| Discovery and permissions | Automated fixture: tool schema alone creates no peripheral; Mac output remains an attribute; stale/denied/gated caps leave guest controls; host role changes never grant scope; provenance survives reconnect. PROPOSED, not run. |
| Camera consent and lifecycle | Automated fixture: torch-only permission cannot capture; opt-out/denial/disconnect invalidate readiness; grant/epoch/consent change during countdown/upload denies commit; duplicate/UNKNOWN produces no recapture. PROPOSED, gate closed. |
| Actual photo-to-viewer path | Tester initiates one authorized request after readiness; exact new still/source/capture/version reaches exact Mac viewer. Human confirms the actual group/whiteboard image once. BLOCKED on implementation/gate. |
| Clear and stale work | Automated upload/clear race, stale URL and viewer late-fetch checks; tester initiates host reset only when authorized; human confirms physical clear. BLOCKED on implementation. |
| Retention | Accepted: latest displayed photo survives Leave/expiry/revoke and new guests until replacement or host reset; new-guest context/commands clear and image bytes never enter model history. Automated lifecycle checks and one combined physical observation remain BLOCKED on implementation/gate only. |

Report each stage separately: source checks, discovery evidence, dispatch, source capture, storage, viewer receipt and observed screen. No aggregate demo PASS from a tool list or test count. Experience prompt, if Jay later elects a participant session: invite natural room use without coaching command wording; record assistance/false claims/context loss. The group-photo finale itself deliberately prompts people to pose and does not prove spontaneous discovery.

### Exact acceptance-note amendments proposed to Root

1. Replace a current-deployment summary with: “Handoff reports deployed f228b39, independently reviewed 484 Python + 12 Node checks. Text is default; ongoing voice is current-guest opt-in to the exact available speaker, with opt-out; one-off say is independent. This planning pass did not rerun source checks or add physical evidence.”
2. Preserve: “Manual phone OFF with beat continuing, then separate beat stop: physically PASS at 0b4a1ec. Current program expiry: physically UNVERIFIED; earlier run INTERRUPTED. Do not restart/repeat physical work solely to close a planning record.”
3. Replace forced E1/prerequisite-rehearsal language with: “Local tester initiates ready, authorized experiments automatically. Humans confirm only physical outcomes; no forced unbriefed rehearsal. Existing E1 criteria are an optional experience protocol when Jay chooses one.”
4. Add: “Capability discovery, camera opt-in/roles and capture-to-viewer contracts are proposed in notes/planning-local.md; no implementation or physical acceptance. Retention follows accepted 19:17 direction: latest displayed photo remains after Leave and across new guests until replacement or host reset; new guests reset context/commands, and image bytes stay out of model history. Future host retention setting is deferred. Photo/perception/proactive gates remain closed.”

## Direct feature discussion — October 17, 20:13 PT

Jay endorses four connected directions: a room that keeps learning newly connected devices; AI coordination across them; internal suggestion generation with selective publication; and photo capture followed by an explicit request to show that photo on the Mac-connected projector. Record these as product direction. No integrations, effects, schedules, web edits or capability gates were activated by this discussion.

### Growing room and coordination

Device admission is incremental: an evidenced endpoint joins, keeps its identity, gains only actually available capabilities and exposes the host's role/location/permissions. The AI refreshes its usable inventory as that changes and can propose new combinations. No fixed demo device count or baked-in room template. New operations still require a discovered supported binding and current authority; joining alone triggers no light/music/camera action.

For a coordination request, resolve the intended participating devices and supported actions from that inventory, maintain the current activity's context, then report each actual outcome. A device joining a beat is the existing example; showing a captured photo through the Mac's projector is another. Do not infer synchronization or all-device success from successful individual dispatches. Audio retains timing/music ownership.

### Selective suggestions — proposed first version

Use the model internally to generate an optional useful next question for the guest. A small deterministic filter decides whether to publish it. This is suggestion generation, distinct from autonomous physical rules. The model may return no suggestion; silence is a normal outcome.

Candidate generation happens after a meaningful event (a newly usable capability or a completed guest turn/action), coalesced while a turn is active; no polling loop or new background automation is needed for the proposal. Supply minimal current text context, usable inventory and recent suggestion/dismissal identifiers. Keep image bytes and private device identifiers out of this prompt. The generator has no effect tools or host authority, and the internal prompt/result stays out of the visible conversation unless selected. Tie its result to the original guest/generation so it cannot leak to the next guest.

Publish only if all these proposed criteria pass again at publication:

- The same guest is still active; the suggestion is directly relevant to the current activity and names only available, guest-permitted, open-gate capabilities. Permission denial, UNKNOWN, unresolved failure and access ending suppress suggestions rather than inviting retries.
- A useful change occurred; do not generate conversation filler. No camera-scene interpretation is assumed. “Want the phone light to join the beat?” can follow an observed running beat and available light. “Want this photo on the projector?” requires an accepted photo and verified permitted projection path.
- No turn, confirmation question or earlier suggestion is awaiting an answer. Publish as one short text question after a natural pause; no unsolicited speech in this first version.
- Avoid repeated or dismissed ideas. Proposed starting budget: at least two minutes between suggestions and at most two per guest, with a maximum of one pending suggestion. These are tuning proposals, not accepted product constants. “No suggestions” suppresses the rest of that guest session.

A yes binds to the exact still-current proposed action; recheck authority/devices/targets before dispatch. A declined, stale, unavailable or expired suggestion produces no effect. Do not infer consent from silence. A general ongoing-voice opt-in does not itself authorize physical action. Acceptance checks later should cover suppression, guest replacement, deduplication, dismissal, stale yes and zero dispatch before explicit acceptance; no test or implementation was started here.

### Photo → Mac → projector — explicit second request

Desired journey: take the opted-in group photo, see the result on the Mac, then Jay asks “can you display it on the projector?” Resolve “it” to the same accepted photo ID/version; do not recapture or send image bytes into model history. Keeping a physical photo on screen across guest changes does not restore an old guest's conversation/queued requests or grant a new guest authority to redistribute it.

Represent a physically connected projector as an evidenced Mac output relation with its observed display key and host-specified projector role/location. This is not an independent controllable projector endpoint unless distinct control/resource evidence exists. A display being plugged in establishes neither targetable fullscreen placement nor actual projection; discover those capabilities through existing tools/adapters and identify the correct output with the host where needed.

Before dispatch, require current guest display permission, host allowance to present the retained photo on that output, exact live Mac/output binding and a supported display operation. Extend the authenticated viewer contract with the approved output target; changing output role/binding invalidates pending projection. Display the existing stored image through the Mac, without changing sound output/volume or opening unrelated desktop content. Projection permission does not imply permission to mirror the entire desktop or alter system display arrangement.

If the Mac is already mirrored, the image may already be projected: acknowledge that truthfully. A visible second-step transition requires a supported separate output/viewer path (for example, an already-configured extended display); plan around actual available routing, not a fabricated projection action. If target selection is unavailable, explain it and offer the supported Mac display rather than claiming projector success or silently changing display settings.

Track stored-photo evidence, Mac viewer render and target-output render separately. Only an actual human-observed projector image proves physical projection. The local tester owns any later authorized experiment; there is no new physical ask now. Latest displayed-photo retention remains until replacement/host reset; new guests reset context/commands, and image bytes stay out of model history. Projector connection/routing and photo/proactive implementation remain unverified/gated.

Owen request addendum, ready for Root to route: show newly usable devices as the room grows; support at most one short contextual suggestion with accept/dismiss only after a backend publication decision; when photos/projection open, distinguish “received,” “shown on Mac” and the evidenced projector result. Keep the existing theme/table and no speculative device cards. Core supplies inventory, suggestion eligibility and exact photo/output/result bindings. No message was sent.

## Independent design review — original base contract

Read-only review identified three gaps: authenticate the exact viewer rather than trusting its supplied ID/public image URL; deduplicate capture request IDs before issuing tickets or dispatching the shutter; recheck host allowance and role revisions at commit. All three were incorporated above. The reviewer confirmed the endpoint/peripheral distinction, reconnect provenance, separate capture consent and truthful result stages. This is design review only, not implementation or physical acceptance.

Follow-up independent read-only review of all three revised notes: clean, no remaining material design issues. Readback/format checks pass and all original demo candidate categories remain present. No source/runtime tests were needed for these note-only changes.

Root retains acceptance, product decisions and routing. Planning edits only this file, demo-ideas.md and demo-alignment.md. Nothing in this plan opens a capability gate. Planning stages or commits only when Root coordinates. The new feature-discussion addendum has not had an independent design review.

Final source-only independent review during the testing pause found no material defects in the updated service, installer or unapplied integration patch. No code execution/tests were performed. Exact current source hashes and completed pre-pause component evidence are recorded in tests/evidence/2026-10-17-photo-backend.json; the manifest is explicitly NOT an executed final-source validation. Testing remains paused, central/UI integration and physical acceptance pending. No cleanup is active.
