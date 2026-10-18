# Photon status — evidence audit, October 17, 2026

Photon is already verified through Tenant for real inbound messages, the shared native room conversation, and provider acceptance of replies. Earlier notes describing native inbound as unverified are stale. Actual handset receipt is a separate observation; a missing confirmation is not a demonstrated failure.

This was a read-only audit of existing records. No new join, message, API poll, native turn, device action, restart, or test-suite rerun was performed.

| Check | Evidence and time (Pacific, October 17) | Conclusion |
| --- | --- | --- |
| Credentials and project access | Existing private assignment-response artifact and sanitized inbound-schema artifact; root recorded successful HTTP 200 read-only checks around 18:14–18:16. Later successful sends also require project access. | Verified. No keys or phone handles reproduced. |
| Standalone Photon spike | `ARCHITECTURE.md` §5.3 records the 16:11 real receive/send-acceptance round trip; `spikes/photon/test.py` is executable supporting code. Owen's 17:50 notes corroborate the spike handoff. | Documented live pass for the spike. A separate raw spike transcript or handset observation was not found in inspected assets. |
| Tenant enrollment | Production event log records a Photon guest joining at 18:35:29. The same guest owns both durable Photon claims. | Verified real enrollment, beyond credential validation. |
| Real Photon inbound → native agent | Production SQLite claims at 18:35:34.020738 and 18:36:07.594471 both reached `ACCEPTED`. Corresponding native `cmd`/`ok` pairs follow for the same guest. | Verified twice for one guest. |
| Same fixed room conversation | Both native pairs use configured thread `01a14c77-6542-7e42-9067-bb1d28aec72b`, generation 2. Native turns are `01a14ca6-5ef6-77d2-a04b-c45f1bd87637` and `01a14ca6-e1af-7b82-9b5d-a35aab3d0cf5`. Current Photon source calls the same `core.agent.turn`; no separate model/chat is constructed. | Verified real same-thread execution. This does not establish native-app visual rendering. |
| Provider acceptance of Tenant replies | Production `ACCEPTED_NOT_DELIVERED` events at 18:35:37.645473 and 18:36:13.822983; both durable claims are `ACCEPTED`. Client code emits this after Photon HTTP 202. | Verified two accepted reply submissions. Acceptance does not establish handset receipt. |
| Handset receipt | No explicit phone-delivery result or human handset-receipt confirmation found in inspected assets. The recent statement that Photon was verified does not specify which stage was observed. | Missing record, not a proven failure. If Jay already saw both replies, record that observation without rerunning the channel merely to recreate paperwork. |
| Spoken Photon replies | Same-turn speech status is `ACKNOWLEDGED` at 18:35:40.742979 for the first reply, `UNKNOWN` at 18:36:17.824323 for the second. Human-heard Photon-specific confirmation was not found. | Mixed machine outcomes; do not label both audible or silently replay the uncertain speech. Later web-voice passes are separate evidence. |
| Same-enrollment linked web context | Authenticated linking, unchanged credential/deadlines, and shared history are covered by reviewed offline tests. A real Photon-to-web contextual follow-up for this exact guest was not found in inspected assets. | Backend behavior tested; live cross-channel memory observation not recorded. Two Photon turns on the same native thread are already verified. |
| Ended access | Production `DETACHED_PREEXISTING` at 18:45:30.644335 confirms this guest's reused external assignment binding was detached. No fresh post-end Photon message paired with a native-denial/no-action observation was found. | Detachment verified. Photon-specific ended-access denial and the exact end reason are not established by this event alone. Existing web/historical lifecycle tests remain separate. |
| Same-browser enrollment recovery | Repeated form submission defect was reproduced offline, fixed in `9c479c6`, independently reviewed, and included in later deployments. Tests preserve the original guest, secret and deadlines without a new native call/allocation. | Reviewed source/test pass; an explicit real retry-recovery observation was not found in inspected assets. |

## Primary timeline

| Stage | First Photon input | Second Photon input |
| --- | --- | --- |
| Durable inbound claim | 18:35:34.020738 | 18:36:07.594471 |
| Native turn starts | 18:35:34.139133 | 18:36:07.616156 |
| Native reply completes | 18:35:37.437682 | 18:36:13.584158 |
| Photon accepts reply | 18:35:37.645473 | 18:36:13.822983 |
| Speech status | 18:35:40.742979 — acknowledged | 18:36:17.824323 — unknown |

These are stage timestamps, not phone-delivery or acoustic-effect latency measurements. The production Photon database currently contains two accepted claims and zero active bindings. No message bodies, phone numbers, tokens, cookies, or private URL fragments were emitted during this audit.

## Inspected assets

- `log/events.jsonl`: parsed JSON with strict metadata allowlist; all four Photon events and same-guest native/speech events inspected. Message text and arbitrary command/error content excluded.
- `.venv/tenant-runtime/photon.sqlite3`: opened read-only; claim counts, outcomes and correlation identifiers inspected. Guest handles, assigned phone numbers and other private values excluded.
- `.venv/acceptance/photon-assignments-private.json`: structure/count evidence only; no assignment values disclosed.
- `.venv/acceptance/photon-inbound-schema.json`: sanitized schema evidence.
- `ARCHITECTURE.md` §5.3 and `spikes/photon/test.py`: original spike contract and recorded live result.
- `notes/owen.md`, `notes/jay.md`, `notes/demo-testing.md`: chronology and prior claims; older and later “inbound pending” statements reconciled against actual production records.
- `tests/evidence/2026-10-17-photon-shared-channel.json`, `2026-10-17-photon-enrollment-recovery.json`, `2026-10-17-photon-live-verification-card.json`: prior source/acceptance records. The card is a plan, not proof its full sequence ran.
- `tests/evidence/2026-10-17-conversation-speech.json`, `2026-10-17-native-device-helper.json`, `2026-10-17-local-e2e.json`, `2026-10-17-audio-local-acceptance.json`: inspected for overlapping evidence; later web/audio/device passes do not establish Photon handset delivery.
- Latest available main-chat and End-to-end Tester summaries: no additional explicit Photon handset-delivery confirmation found; no exhaustive history search or new test requested.
- Current `brain/channels/photon.py`, `brain/api/join.py`, integration source, and allowlisted runtime settings: conversation mode and Photon enabled; configured thread matches both real native turn records. Local HEAD at audit: `e7695d1` with other owners' work in progress; no source change made by this audit.

Only genuinely unrecorded observations remain conditional: handset receipt, Photon-specific human audibility, a same-enrollment web memory follow-up, real browser retry recovery, and a Photon post-end denial. Preserve the existing positive inbound/shared-thread/acceptance evidence and do not repeat those checks by default. Root coordinates any remaining observation with the single active tester.
