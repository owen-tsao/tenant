# Photon status — evidence audit, October 17, 2026

## Latest real run — October 18

The actual phone entered its own number through the normal Text the room flow. Eight real inbound claims for the same guest reached ACCEPTED and ran in the fixed native room conversation. The agent independently used installed Spotify to play Japanese Denim, then handled the user's request to add approximate phone pulses without interrupting playback. Jay heard the music and confirmed that the phone pulsed roughly with it and stayed OFF after the explicit stop. Approximation is accepted for this demo; precise beat phase was not measured.

The agent initially declined beat matching, then used Spotify position and an estimated tempo for a one-off sequence of existing phone commands after the user asked it to try. The loop exited on an unconfirmed OFF attempt; the subsequent explicit OFF was acknowledged, with no later light commands. Do not describe that as a reliable managed synchronization loop or guaranteed automatic cleanup. Spotify was preserved as the user's ongoing native-app effect.

The eighth genuine Photon request asked for a phone photo. It was rejected before dispatch with PERMISSION because current photo/source readiness was missing; the phone advertised only light. There is no real photo/display pass. Backend/device completion is now separately authorized and underway. Native iPhone-app control was not exercised by these eight Photon turns; the separate Mac TextEdit/Calculator pass used a genuine guest web chat.

This guest's original creation+600s lease expired naturally at00:14:31.818 PDT, its local binding detached, and the reused external provider assignment remained. Activation does not extend the original deadline. Public display history retains ten bubbles and clears with the ended guest; the recorded native conversation and sanitized test evidence preserve the observed sequence.

Evidence: `tests/evidence/2026-10-18-photon-existing-capabilities-live.json`, with physical observations and correlated claim/native/reply timestamps. This supersedes the earlier fresh violet-case ambiguity, whose separate evidence is retained in `2026-10-17-photon-real-phone-retest.json` rather than retroactively labeled successful. Everything below is a historical audit or source-handoff checkpoint where it differs from this section.

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


## Terminal-failure feedback — software handoff (2026-10-17 20:54 PDT)

This additive change is software-only, not deployed or tested against a handset. It does not replace or downgrade the historical real inbound/shared-thread/provider-acceptance evidence above.

- Photon retains its existing successful-completion `_can_reply` predicate unchanged (AST comparison against HEAD passed). A separate typed `TerminalFailureFrames` route requires the exact current lease plus the central agent's issued-receipt/controller/thread/turn/generation authorization. Generic lists, unissued receipts and altered frame text remain ineligible.
- The same durable inbound claim, `SENDING`/`UNKNOWN` states, idempotency key and no-retry policy apply. Authority is rechecked immediately before the provider call. A cleanup-blocked notice may reach its still-current guest without reopening action authority.
- Terminal feedback never becomes a `CompletedReply` or automatic-speech-eligible result. Acceptance audit adds only a fixed `reply_kind` distinction (`terminal_failure` / `completed_reply`). Provider acceptance still does not establish phone delivery.
- Focused fake checks passed: 11 new terminal-composition tests plus 45 existing Photon tests, zero failures. They use the real conversation controller and public projection with fake native/provider inputs: confirmed/unconfirmed cleanup, one-send/no replay, separate next explicit request, revoke/expiry/reset/replacement before send, plain/unissued/tampered result rejection, unknown/cancelled send, no terminal narration or partial private output. No broad suite, live API/model/device/UI operation, restart, stage or commit was performed by this owner.
- Frozen Photon source: `brain/channels/photon.py` SHA256 `b14a991215249efe17766ac583187b4b62d557bd3b3ff0638e8a2f803c8f46c8`; new `tests/test_photon_terminal_failures.py` SHA256 `188ecec607523bb98612b032685b29e25655d0f9686d7070b0e677ab60f7e299`. Diff and whitespace checks passed. The central integration owner supplies the additive neutral receipt/controller and projection contracts and owns the final combined snapshot/review/release.

All live verification remains paused under central integration. Any later phone observation must be recorded separately from these fake-provider software checks.
