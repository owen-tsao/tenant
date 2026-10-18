# Device runtime — local Mac owner

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
