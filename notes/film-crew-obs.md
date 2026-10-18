# OBS adapter handoff

Public API being implemented in `film_crew/obs_control.py` (offline only):

```python
ObsControl(config=None, *, password_file=None, client_factory=None,
           event_factory=None, authorize=lambda: False, on_override=None,
           clock=time.monotonic, host='127.0.0.1', port=4455, timeout=3,
           label_font_size=72)
control.connect()                 # persistent authenticated request + event sockets
control.discover()                # safe names, source kinds, current program
control.configure(manifest, adopt_empty_owned=False, adopt_verified_owned=False)
control.switch('wide' | 'detail', not_after=None) # cut + program readback
control.observe_program()        # safe dict; manual changes latch override
control.status()                 # alias for observe_program
control.snapshot(role, width=320, height=180) -> CameraSnapshot
control.close()                  # disconnect alias; no OBS scene/output mutation
control.override_event           # threading.Event; immediately set on manual change
control.manual_override          # bool; latched until a new adapter is explicitly made
```

`config` is Root's `film_crew.config.ObsConfig`; password stays in memory. For
isolated tests, a private plain text `password_file` is also accepted. Every OBS
write checks `authorize()` immediately before sending. `on_override()` is an
optional no-argument callback for canceling a pending autonomous dwell; it must
not perform blocking work. No automatic retry/reconnect after an uncertain write.

`COLLECTION = 'Tenant Film Crew'`, `SCENES = {'wide': 'WIDE', 'detail': 'OBJECT'}`.
Camera inputs use canonical `cameras.SOURCE_NAMES`. Configure creates the
dedicated collection itself; **do not precreate that collection**, because an
existing same-name collection without this adapter's ownership marker is refused.
For a fresh empty dedicated collection, use
`control.configure(manifest, adopt_empty_owned=True)` for that first setup only.
This accepts only the currently active dedicated collection with zero inputs
and at most one empty default scene; it preserves that empty scene.
**Tester has now populated the real collection: use
`control.configure(manifest, adopt_verified_owned=True)` for its first attach.**
This verifies the complete four-input inventory, both camera scenes, at most one
empty bootstrap scene, matching private URLs, warm/muted/unmonitored cameras,
geometry, labels and Cut overrides before writing only the ready ownership
marker. It does not switch program, create, replace, reload or reposition any
source. A foreign/partial marker or a mismatch is refused without writes.
Geometry accepts either two covered full-canvas sources in the correct stack
or the nonselected warm camera parked one canvas width to the right. The working
H264 viewer parameters must first match Camera owner's canonical manifest.
Both browser sources appear enabled in both scenes. Text labels are WIDE/OBJECT.

Snapshot fields: `png` (bytes, omitted from repr), `observed_monotonic`,
`request_started_monotonic`, `source` (safe source name), `source_active`,
`source_showing`, `frame_freshness_verified=False`. Observation time is the local
screenshot receipt time, not the phone's capture time. OBS active/showing state
does not establish that a camera is connected or its pixels are fresh.

Implementation/testing status: source ready; **51 isolated fake-protocol tests
pass**. No live OBS changes, camera access, output changes, or physical feed
claims made by this owner. Independent review reproduced and verified fixes for
swapped camera stacking and delayed own scene acknowledgements, including the
initial WIDE selection from Tester's retained default Scene.

Root integration: constructor accepts `ObsControl(load_obs_config(...),
authorize=...)`; current CLI uses that contract. **Its first setup call needs
`configure(manifest, adopt_verified_owned=True)` for Tester's populated collection.**
Subsequent `configure(manifest)` calls verify the marker and source settings
without rewriting sources. `status()` / `observe_program()` keys are
`collection`, `scene`, `expected_scene`, `override_detected`,
`observed_monotonic`. The latched override bit also catches a manual round trip
between polling observations. `switch()` adds `role` and
`request_started_monotonic`. A request for the already active role is read-only.
Every mutating call remains individually gated by `authorize()`; there is no
automatic retry. `ObsError.code` is constant public error metadata.
For evidence-driven cuts, pass the monotonic evidence expiry as
`switch(role, not_after=min_paired_request_start + .5)`. A finite deadline is
checked again inside the SDK call lock immediately before the final write,
after authorization and all preflight requests. Authorization and manual
override are also rechecked after waiting for that SDK lock. Expiry sends nothing and leaves
the prior expected scene intact; explicit manual cuts may omit the deadline.
The independent reviewer reproduced the lock-wait revocation race and confirmed
the final fix sends zero cuts, restores pending state and preserves the socket.

Source/plugin assumptions checked against installed obsws-python 1.8.0 and
staged OBS 32.2.2. Camera browser inputs are muted with monitoring disabled;
setup refuses enabled global microphone/desktop inputs, active outputs, and
Studio Mode. It does not alter system audio or other scene collections.
Closing disconnects control sockets and leaves the last program scene intact.
Per-scene Cut overrides are checked immediately before switching. The request
socket serializes operations; the separate event socket latches operator scene
or collection changes. Delayed own acknowledgements are consumed once, in
server order, so subsequent genuine manual changes remain visible.

Live limitations: a local PNG receipt, changing pixels, or OBS active/showing
flags cannot prove phone capture freshness. Physical feed identities, opaque
camera fill/label visibility, both feeds remaining live off-air, and end-to-end
cut latency still require the released live test. OBS events do not identify
the originating client; event/readback checks cannot give an atomic guarantee
against an operator cut in the final network race window. No capture timestamp
is invented. PNG bytes are memory-only and omitted from repr; the adapter does
not write or print frames.

Primary references: [OBS WebSocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md),
[OBS browser source settings](https://obsproject.com/kb/browser-source),
[browser source implementation](https://github.com/obsproject/obs-browser/blob/master/obs-browser-source.cpp),
[installed SDK upstream](https://github.com/aatikturk/obsws-python).
