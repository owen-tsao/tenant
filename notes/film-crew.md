# Tenant live film crew

**Paused at Jay’s explicit request to stop and pivot.** Both actual feeds and ten rendered manual cuts passed. The real adapter adopted the setup and an unarmed model pass produced36 numeric observations. Roles were remapped in software; close-up orientation remains unresolved. The automatic trial was never armed, and disconnect/reconnect remains untested. No new live work is authorized by this checkpoint. Saved setup/evidence are retained; the unused private trial approval is revoked.

The requested demo is two real iPhones feeding this Mac, an obvious WIDE/OBJECT cut in OBS, then one silent model-driven choice when someone demonstrates an object. Reuse VDO.Ninja, OBS and a pretrained local model. No custom phone app, new video transport, guest-page changes, audio capture or external broadcast.

## What is established

- Both separate phone pages show live video, confirmed by Jay. Tester has independently observed two distinct, changing real camera images in OBS and the actual Mac Program window. Initial black OBS sources were fixed with the combined recipe below; no individual change is claimed as the sole cause.
- Dedicated Tenant Film Crew profile/collection is saved. WIDE/OBJECT labels and Cut transitions are configured, with both feeds kept rendering. All OBS global audio inputs are Disabled. Tenant services, Spotify, system output and volume were preserved.
- The isolated combined film-crew suite passed134 checks at this integration checkpoint. These are software checks, not physical acceptance. The local model also executes and is warmed outside an event; measured paired inference is16–34ms on this Mac's GPU depending on input size, excluding phone transport, OBS capture, dwell and the actual visible cut.
- Ten actual Mac Program cuts passed, with correct labels and distinct camera images individually inspected; native window checks corroborated start/midpoint/end. Final useful composition/phone-role challenge, disconnect/reconnect and the requested semantic trial remain pending. Do not infer those passes from the setup or software count. The latest actual results belong in `notes/tester.md` and sanitized test evidence.

## Working setup on this Mac

The two private QR PNGs, `cameras.json` and authenticated `obs.json` are under ignored `.venv/tenant-runtime/film-crew/`. Keep these files local. Phone URLs/passwords, QR payloads and camera images do not belong in repository notes or public evidence. Both phone push links/QRs are stable; viewer-only compatibility changes do not require another phone enrollment.

Each phone uses the standard VDO.Ninja camera page with rear-camera preview and microphone input disabled. It must actually start sharing, remain foreground and awake, and show the intended lens. WIDE means one camera placed farther away to show the demonstration area. OBJECT means a second camera aimed close enough to show useful details of a held object. These are placements, not special phone modes. No Photo Booth or iPhone Mirroring is involved.

Observed OBS32.2.2/macOS working recipe: Browser Source Hardware Acceleration **OFF**, viewer URLs request `codec=h264`, and the **same two input objects** remain enabled in both scenes. The off-air view may be outside the canvas, rather than hidden/disabled, so rendering continues. `shutdown=false`, `restart_when_active=false`; both inputs are muted with monitoring disabled. A hard Cut and readable WIDE/OBJECT text make the attention shift visible without speech. Do not restart OBS during the staged demo; warm both feeds first and verify the off-air one still moves. Hardware-acceleration changes require an OBS-only restart during preparation.

The OBS client connects to127.0.0.1 using its private generated password. Stock OBS's server is authenticated but is not established as loopback-bound. No network/firewall changes were made. No stream, recording or virtual camera is required. The projector is outside this first proof; the Mac Program window is the actual output.

## Small local controls

Use the existing isolated environment; base dependencies are `requirements-film-crew.txt`, model dependencies are `requirements-film-crew-vision.txt`. This does not change the production Brain environment. Model weights/config/tokenizer are already local at `.venv/film-crew-models/mobileclip2-s0`; pinned files and checksums are in the vision handoff.

```sh
.venv/film-crew-lab/bin/python -m film_crew status
.venv/film-crew-lab/bin/python -m film_crew setup --adopt-verified-owned
.venv/film-crew-lab/bin/python -m film_crew cut wide
.venv/film-crew-lab/bin/python -m film_crew cut detail
.venv/film-crew-lab/bin/python -m film_crew watch --model-dir .venv/film-crew-models/mobileclip2-s0 --device mps
```

`prepare` reuses the private invitations without opening a camera. `setup` creates dedicated scenes or verifies an existing owned setup; explicit adoption verifies the exact already-prepared sources before recording ownership, and never replaces working feeds. Ordinary `status` is read-only. `watch` keeps the classifier and authenticated OBS sockets resident; by default it only reports semantic evidence. Ctrl-C stops observation while retaining the current scene. A cut receipt is a request/readback result; visible output still needs verification.

For the single requested supervised experiment, after actual manual two-feed switching is proved, Root records a private trial receipt for the exact vision/policy hashes: `manual_two_feed_switching_passed:true`, `supervised_trial_approved:true`, `held_out_replay_passed:false`, plus `vision_sha256` and `policy_sha256`. Then use `watch --arm --trial --validation <private-receipt>`. This authorizes **one experimental choice**, not a claim of semantic reliability. It is not an extra user-approval flow. Fully accepted automatic use instead needs a genuine held-out replay receipt; software tests/timing cannot manufacture that result.

## What the AI contributes and what stays deterministic

MobileCLIP2-S0 compares the two views against fixed semantic descriptions of an object demonstration, empty-handed movement and useful/unusable detail views. It proposes OBJECT only when the detail seems relevant and better. The scores are uncalibrated prompt-relative evidence, not probabilities; still-image embeddings do not prove intent or same-object identity. There is no person tracking, recognition or transcription.

Deterministic code handles authorization of this local rehearsal window, recent decoded-pixel changes, acquisition age, stable evidence, one proposal per arm, manual override, switch/readback and stop. Repeated identical pixels or PNG metadata changes cannot accumulate observations. Negative/uncertain/incomplete observations interrupt dwell. Manual scene/collection changes latch a stop even if the operator returns to WIDE. The pending proposal has a short evidence deadline, rechecked at dispatch; an uncertain write is never automatically retried. An in-flight human/network race cannot be made atomic by OBS's API.

Pixel change is only a conservative freshness interlock. It can reject a truly static view and cannot authenticate a sensor or detect every changing replay. OBS source-active flags and screenshot receipt times do not prove phone capture freshness. Physical motion, source identity and deliberate disconnect/recovery remain separate checks. Vendor stats are available interactively; no new telemetry/video platform is claimed.

## Trial and acceptance

First prove both real feeds and ten actual WIDE/OBJECT cuts, checking output pixels and labels. Record fresh movement and both staying live off-air; separately test a deliberately missing camera and recovery. Then take a short no-object/empty-hand baseline and try one real held-object demonstration with a useful close-up. Make the model's chosen cut visible, with no spoken explanation or hidden manual cue. Record whether the view was useful, any false intervention, the event/decision/request/visible-effect timestamps, and cleanup. The human only supplies unavoidable physical placement/motion and observation, while Tester starts the software experiments.

One supervised success is a demo proof, not a reliability estimate. The optional stronger replay plan uses six held-out positive and six negative events, including different objects, ordinary gestures and blocked/wrong detail. Freeze prompts before labels/scores are compared, report misses/false cuts and sample counts, and do not tune on the held-out set. See `film-crew-vision.md` for the precise distinction.

This is currently a host-operated film-crew capability alongside Tenant. It does not silently register a public-guest capability or inherit a guest lease. Connecting it to Tenant's ordinary guest access/expiry is a separate integration decision after this physical experiment; do not pitch that boundary as already implemented. All `web/` files remain Owen's responsibility and were untouched by this work.

Detailed handoffs: [camera transport](film-crew-cameras.md), [OBS control](film-crew-obs.md), [vision and policy](film-crew-vision.md).
