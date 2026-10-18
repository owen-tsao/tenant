# Film crew camera transport — private preparation, October 18

Scope: two REAL phone camera feeds into existing OBS using standard VDO.Ninja phone pages and private viewer URLs. Root requested this new film-crew trial; the prior browser-photo pipeline stays held. No custom phone UI, capture server, video transport, new adapters, Brain/audio restart, room message or OBS mutation was added by this owner. Tester exclusively owns native UI, OBS setup and all live camera/display effects. Phone setup and OS camera consent are a real human gate coordinated by Root once both QRs are ready.

## Assets and small API

Owned files: `film_crew/cameras.py`, `tests/test_film_crew_cameras.py`, this note. `prepare_manifest()` creates or reuses a private local setup and two QR PNGs, without network access. `load_manifest()` only loads/validates. Both return `CameraManifest`; `.feeds` contains two `CameraFeed` objects with `role`, `source_name`, `push_url`, `view_url`; `.feed('wide')` or `.feed('detail')` selects one. URLs are excluded from repr; `.to_private_dict()` explicitly returns secret-bearing data and must never be printed/logged. No readiness/liveness boolean is returned.

Default runtime path, ignored by existing `.gitignore`: `.venv/tenant-runtime/film-crew/`. Private artifacts:

- `cameras.json`: canonical private manifest, `{schema_version:1,feeds:[{role,source_name,push_url,view_url},...]}`. Root requested this filename for controller/Tester coordination. No duplicate credential manifest is retained.
- `wide-phone-qr.png`: phone invitation for source `Tenant Film Wide`.
- `detail-phone-qr.png`: phone invitation for source `Tenant Film Detail`.

Runtime directory mode0700; JSON/QR files0600. Links use independently generated 24-character alphanumeric stream IDs and 32-character alphanumeric passwords for EACH feed. Password and stream ID must match between that feed's push/view URLs; cross-feed reuse, duplicate roles/names, duplicate query fields, unexpected origins or audio-enabling options fail closed. Existing invalid manifests are not rotated or replaced. Preparation is a single-owner setup action, not intended for concurrent calls. The IDs establish two distinct stream slots, not proof of two physical phones; Tester verifies the physical pairing.

Preparation uses already-installed `qrcode`/Pillow in Tenant's `.venv`; no package was installed. Loading requires Python standard library only, so Root can use the capability lab interpreter for OBS work. Safe local preparation invocation, with no URLs printed:

```python
from film_crew.cameras import prepare_manifest
manifest = prepare_manifest()
```

Root/Tester must read the private manifest directly for OBS configuration. Do not paste URLs/passwords into chat, notes, screenshots of OBS properties, public pages or repo files. Display only the corresponding QR privately for its contributor. QR images are access credentials too. Standard vendor URLs include passwords in their query strings; their privacy depends on keeping the links private and the vendor/browser handling. No public media, recording or remote QR-generation service is used.

## Vendor parameters, exact intent and primary documentation

Phone push URLs use `push=<privateID>&password=<privatePassword>&webcam=&vdo=back&audiodevice=0&width=1280&height=720&maxframerate=30`.

- `push`: stable, distinct publisher identity; fixed IDs let the SAME phone return to the same OBS source. Another simultaneous sender using an already-active ID is an error, not a second camera. [Push](https://docs.vdo.ninja/advanced-settings/setup-parameters/push), [permanent links](https://docs.vdo.ninja/guides/how-to-get-permanent-links), [identity collisions](https://docs.vdo.ninja/common-errors-and-known-issues/already-in-use-or-claimed-errors).
- `password`: same per-feed password on publisher/viewer, alphanumeric and case-sensitive. [Password](https://docs.vdo.ninja/advanced-settings/setup-parameters/and-password).
- `webcam`: camera sharing rather than screen-sharing choice. `vdo=back` requests the iPhone rear camera while keeping selection available during setup; unlike a locked `videodevice` choice, it permits correction if the phone labels its rear camera differently. On Android the matching label may be `rear`; the human must verify the preview on EACH actual phone, not assume the requested lens was honored. No `autostart` is included: confirm preview/OS permission and explicitly start sharing once. [Webcam](https://docs.vdo.ninja/advanced-settings/setup-parameters/and-webcam), [VDO camera choice](https://docs.vdo.ninja/advanced-settings/setup-parameters/and-vdo), [camera-name matching](https://docs.vdo.ninja/advanced-settings/setup-parameters/videodevice), [OS permissions](https://docs.vdo.ninja/common-errors-and-known-issues/enable-camera-microphone-permissions).
- `audiodevice=0` disables microphone input, rather than merely muting a captured microphone. `width=1280&height=720&maxframerate=30` targets a modest 720p/up-to30fps capture; actual resolution, encoding rate and latency remain unmeasured. Supported constraints can still fail on a particular camera; Root/Tester should report the actual setup error instead of inventing a live result. [Audio input](https://docs.vdo.ninja/advanced-settings/setup-parameters/audiodevice), [width](https://docs.vdo.ninja/advanced-settings/video-parameters/and-width), [height](https://docs.vdo.ninja/advanced-settings/video-parameters/and-height), [frame-rate fallback](https://docs.vdo.ninja/advanced-settings/video-parameters/and-maxframerate).

OBS view URLs use `view=<sameID>&password=<samePassword>&noaudio=&retry=10&retrytimeout=5000`.

- `view` receives that one publisher, with no room, director or remote-control API added. `noaudio` blocks incoming audio tracks/playback. This is separate from disabling the phone's microphone at the sender. [Basic push/view setup](https://docs.vdo.ninja/getting-started/vdo.ninja-basics), [video-only viewer](https://docs.vdo.ninja/advanced-settings/audio-parameters/noaudio).
- `retry=10` requests periodic stream-state recovery; `retrytimeout=5000` is the documented minimum missing-stream recovery wait in milliseconds. It is not a five-second recovery guarantee or proof of reconnection. Fixed identities are reused after a phone returns. No periodic `autoreload` is added: reloading during a shot would defeat warmed switching. Vendor guidance warns a camera freeze can escape automatic detection. [Retry](https://docs.vdo.ninja/advanced-settings/settings-parameters/and-retry), [recovery](https://docs.vdo.ninja/guides/handling-guest-disconnects-and-connection-recovery), [undetected camera freeze](https://docs.vdo.ninja/common-errors-and-known-issues/webcam-freezes-after-a-time).

## Smallest OBS setup proposal — Tester only

Use existing OBS and the lab's already-installed `obsws-python`; this module does not connect to OBS. Add one Browser Source per manifest source_name using its private view_url (Local file OFF, viewport1280x720,30fps). Reuse those same source objects in wide/detail/both scenes. Keep **Shutdown source when not visible OFF** and **Refresh browser source when scene becomes active OFF** so both peer connections remain warm across cuts. Do not recreate/reload a source on each switch, enable desktop/microphone capture, start recording/streaming, or grant VDO.Ninja OBS-control API access for this trial. [OBS Browser Source properties](https://obsproject.com/kb/browser-source).

Keep both phone vendor pages foreground and phones awake/unlocked during sharing; mount/aim wide vs detail after consent. Two independent browser publishers avoid Continuity Camera's one-iPhone-per-Mac limit. This is a new explicitly requested two-phone vendor-page trial, not an implicit reactivation of Tenant's old phone bridge.

## Liveness mechanism and evidence boundary

Available without a custom wrapper: VDO.Ninja's built-in per-video **Stats** UI (desktop Ctrl/Cmd-click or right-click→Stats; `stats` can show it on load). The existing iframe API can request `getStats:true` and receive connection/media stats, but this direct-URL OBS setup adds no parent iframe or stats collector. There is no programmatic phone-frame-freshness endpoint in this manifest module. [Stats UI](https://docs.vdo.ninja/advanced-settings/settings-parameters/and-stats), [existing iframe stats API](https://docs.vdo.ninja/guides/iframe-api-documentation).

Observe changing inbound media statistics/received video frame rate where the actual vendor UI exposes them, then correlate with a fresh, role-specific visible movement from EACH real phone. A connection event proves a peer connection; positive bitrate alone can include overhead; OBS input active/scene-selected and a recent screenshot timestamp prove neither new phone frames nor an unfrozen sensor. Even decoded frame counts can advance while a sender repeats stale imagery. A stale/frozen/disconnected/unknown view must not be promoted as a useful live view. Loading-circle disappearance is not a recurring health check: the vendor says it need not reappear after later freezes. [Loading-circle limitation](https://docs.vdo.ninja/common-errors-and-known-issues/loading-circle-shows-in-obs-or-browser).

## Smallest two-feed physical gate before proactivity

1. Root makes the one coordinated human setup ask with both labeled private QRs. One person opens WIDE on phoneA, another opens DETAIL on phoneB; each grants Camera, checks rear preview, confirms no microphone input and starts sharing. Do not show both QRs to one phone and call that two real devices.
2. Tester verifies both OBS feeds simultaneously: a different fresh movement/object challenge in each view, correct source identity, both continuing while the other changes. Keep a short bounded observation and actual media stats; record no credentials or raw phone media in public evidence.
3. Tester performs wide→detail→wide cuts using existing warmed OBS scenes and visually checks the actual output for the correct live angle each time. Report perceived delay/freeze/black frames; do not substitute WebSocket ACK for physical switching.
4. Briefly interrupt DETAIL and verify WIDE remains useful; return the SAME DETAIL link and re-prove fresh detail motion before considering it selectable. Keep this within Root's finite live case. Retry configuration alone is not reconnect PASS.
5. Only after both live feeds and physical cuts pass, Root's coordinator may make ONE silent proactive useful-view choice during the requested object demonstration. Camera preparation implements no object inference, selection policy, narration or automatic scene cut. End/pause phone sharing and perform exact owned-source cleanup under Tester's case when finished.

Current physical state is NOT TESTED by this owner; phone availability, two consented publishers, peer connectivity, actual fresh frames, smooth switching, reconnect and projection remain live gates. Root clarifies both phones feed THIS Mac; actual Mac screen switching is the first output gate, before any projector claim.

## Frozen software handoff and exact private artifact paths

Final focused command `.venv/bin/python -m unittest discover -s tests -p test_film_crew_cameras.py -q`: **11 tests PASS**,0 failures/errors,0.251s. Covers identity separation/matching, no-microphone and rear-preview parameters, viewer retry/video-only options, exact QR payload pixels, private permissions, preserved/reusable links, invalid existing manifests, duplicate/malformed data, credential-free repr/errors and symlink rejection. No model, network, phone, OBS, camera or native UI used by these checks. `git diff --check` clean. Independent read-only review found no material defects and confirmed the final module/test hashes after the canonical filename change.

- Module SHA256: `2c5f3d5f1672dcf3a7982636284bce9936f321e5f8e3c22047c4164514868ce1`.
- Test SHA256: `c11c5cb9eb6cdf2ba6556e98f7d2e35aa2786d44215ddfab33e8af9c85083139`.
- Canonical manifest: `/Users/jay/.codex/.chatgpt-projects/g-p-6ad3f8165b088191abcf2e1da4ad5fa8/tenant/.venv/tenant-runtime/film-crew/cameras.json`.
- Wide QR: `/Users/jay/.codex/.chatgpt-projects/g-p-6ad3f8165b088191abcf2e1da4ad5fa8/tenant/.venv/tenant-runtime/film-crew/wide-phone-qr.png`.
- Detail QR: `/Users/jay/.codex/.chatgpt-projects/g-p-6ad3f8165b088191abcf2e1da4ad5fa8/tenant/.venv/tenant-runtime/film-crew/detail-phone-qr.png`.

All three artifacts exist privately; existing Git ignore covers them. `manifest.json` was renamed to `cameras.json` once, with the same identities/passwords and QR payloads; no duplicate credential manifest remains. Preparation does not open either camera or start a publisher. Do not print private values when Root passes the viewer URLs to the OBS owner.

For policy wiring: **no machine-readable per-phone frame freshness has been integrated**. The direct-URL OBS sources do not deliver VDO.Ninja iframe stats into Python. Built-in vendor Stats UI plus fresh per-phone visual challenge is available to Tester; OBS active/scene state and screenshot receipt time must not populate a source-freshness timestamp. Root must retain unknown/stale if physical freshness is not established and should not claim a background freshness monitor from this preparation.

No live effect, source edit outside the three owned files, staging, commit, deployment, Brain/audio restart or room message by this owner. Camera preparation is frozen; Root/Tester own the coordinated phone consent/placement ask and phase1 live gate.

## October 18 — H264 reconciliation; current freeze supersedes earlier hashes

Root relayed Tester's actual observation: BOTH real OBS feeds became visible with **Browser Hardware Acceleration OFF + viewer-only `codec=h264` + both camera inputs enabled (off-air input off-canvas)**. This is the combined observed working recipe; no single-setting causality was isolated. Earlier normal-browser wide-feed decoding established the publisher/normal-browser path, so a new phone Start/reconnect request was not justified. Physical lens-cover identity challenges and complete two-feed freshness/switch acceptance remain Tester's live gates, not a PASS from this owner.

At Root's explicit direction, private `cameras.json` now retains the SAME two entries, all source names, push URLs, stream IDs and passwords, with only each viewer URL's `codec=h264` field reconciled. Both existing QR PNG byte hashes were checked unchanged before/after. No phone URL or QR regenerated, no phone reconnect requested, no OBS API/UI call, source reload or settings mutation by this owner. Root's relay is the coordination evidence for the current H264 recipe; this owner did not independently query live OBS or claim a byte-for-byte live-settings audit. Root's adapter `configure` verification remains the exact live equality gate.

Validation now permits an OPTIONAL viewer-only `codec=h264` or `codec=vp8`, while preserving every other strict option/origin/query/identity constraint. Missing codec remains valid for original prepared manifests. Duplicate, blank, unsupported, uppercase or codec-list values are rejected; codec on a phone push URL is rejected. Existing manifests with a supported codec load and prepare idempotently without losing that option or changing the phone invitation/QR payload. Default creation is otherwise unchanged. This is not a phone-side codec configuration or a guaranteed negotiated codec: the vendor documents `codec` as a viewer preference. [Primary codec reference](https://docs.vdo.ninja/advanced-settings/video-parameters/codec).

Focused final command `.venv/bin/python -m unittest discover -s tests -p test_film_crew_cameras.py -q`: **14 tests PASS**,0 failures/errors,0.341s. Three additional tests cover both optional codec values, invalid/sender/duplicate codec rejection and load/prepare preservation of credentials/QRs. No network, phone or OBS involved. Current source hashes:

- `film_crew/cameras.py`: `e062e2c8fd5738657d0d4011a5fb8e63b178c04128bad6f1e4cb2470d97d1fe5`.
- `tests/test_film_crew_cameras.py`: `e3875c03d470fe4525f4d380351bb7b0e182074f66fad8ac832a9c09857f5ce8`.

No automated phone-frame freshness telemetry was added. Do not promote OBS enabled/off-canvas state or screenshot receipt times into fresh sensor timestamps. No URLs/credentials/media appear in this note. Only the three owned camera files and the explicitly authorized private camera manifest were changed; no central/other-owner source, commit, deployment, Brain/audio restart or room message.

Final independent read-only review confirmed the current module/test hashes and found no material defects in the codec restriction, preservation tests or observed-recipe/freshness qualifications. No private artifacts were opened or live actions performed by the reviewer. Camera candidate is frozen for Root's adapter verification.

### Immediate orientation option — Root-authorized narrow addition

Verified viewer-only `forceviewerlandscape=90` or `forceviewerlandscape=270` rotates incoming portrait video toward landscape; choose the visually correct quarter-turn on OBJECT only. This option is now accepted by the strict parser only on viewer URLs, with exactly90/270 permitted; blank/other/duplicate/sender-side values remain rejected. Existing H264, identities and all phone push pages/QRs stay intact. This owner did not choose a direction, change the private manifest, reload OBS or alter the live mapping. Tester owns the already-authorized role swap and exact OBJECT orientation selection. Primary docs: https://docs.vdo.ninja/advanced-settings/mixer-scene-parameters/and-forceviewerlandscape ; vendor parsing code: https://github.com/steveseguin/vdo.ninja/blob/master/main.js#L1719-L1721 . It operates on incoming portrait orientation, rather than an unconditional whole-page rotation; actual framing/uprightness still needs the live check. No broader refactor or new platform.
