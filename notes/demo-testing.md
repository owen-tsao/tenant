# Tenant demo acceptance

Owner: demo planning. Current through reviewed runtime89a0b4c; consolidated October17, 18:31 PT.

Root coordinates every live host/device test and consolidates notes/jay.md. Owen owns ALL web files. This workstream maintains evidence and test cards; it does not run competing hardware tests, restart services or implement extensions.

## Evidence rules

PASS: the named check passed within its recorded scope and revision.
FAIL: a completed check violated its stated criterion.
BLOCKED: implementation, authorization, evidence, hardware or a decision is missing.

Separate reviewed source, automated tests, live transport observations and human physical observations. A mock, subprocess success, HTTP202, WS acknowledgement or native navigate=true does not prove a delivered message, visible window or audible effect. A historical PASS does not accept changed code.

Current facts below come from Root's verified handoffs and previously inspected repository evidence; this documentation workstream has not independently rerun the live checks.

## Current matrix

| Check | State | Evidence / limit | Owner or next unblock |
| --- | --- | --- | --- |
| Historical bounded room core | PASS, historical | Evidence published6075a3a; runtime4c4b474, QR ba6248c. Three fresh physical guest runs; explicit alternative choice; light/speech/music; access-ending denial; actual600s expiry denied in14ms; two physical resets OFF+pause and four queued guest turns denied. | Root; final changed path must pass separately. |
| Genuine native conversation wire | PASS | ff6ab19 public HTTPS/WS natural question -> “What would you like to create on this Mac?” about3555ms. Supported read_thread verified exact request/reply on sole native room thread. Conversation mode does not use/fall back to old restricted planner. | Root. |
| Human free-form phone conversation | PASS, bounded | Jay confirmed natural phone conversation; request/reply stored in fixed native thread. | Not general device/voice acceptance. |
| Native local-read/web tools | PASS, bounded | Actual local read and web tool execution observed in genuine conversation. | Does not establish intended interactive Mac/phone actions. |
| One real guest replacement | PASS, bounded | Earlier working context cleared; stale guest request denied with no native turn. | More final-path lifecycle checks required. |
| Explicit guest speech | PASS, historical human | At80358f2 an explicit speech request produced the heard phrase. Earlier noun-only input had no action verb; no planner fix is pending for it. | Not automatic conversation read-aloud or mic-input proof. |
| Speech/cleanup source | PASS, reported | c3ef922 reviewed/deployed;239 Python+12 Node. Cleanup queue-before-interrupt, bounded overall deadline and history traversal reviewed. Automatic speech hook exists. | Current audible result still pending. |
| Latest source suite | PASS, reported | Latest reviewed runtime89a0b4c has296 Python+12 Node checks; Photon was introduced atd8fef91. | Counts prove source checks, not physical outcomes. |
| Photon adapter source | PASS, reported | Same exact core.agent/native room conversation, no second model; optional authenticated web linking preserves credential/expiry. No web edits. | Live channel acceptance pending. |
| Photon credential preflight | PASS, read-only | HTTP200; ONE external pre-existing assignment under assignments, not items. No preflight assignment/message changes. | Preserve external assignments. |
| Actual Tenant Photon enrollment/inbound | BLOCKED | Zero actual new Tenant Photon enrollments and zero native inbounds through that channel so far. Existing external assignment is not ours. | Root's pending Text the room trial. |
| Messages delivery / automatic audio | BLOCKED | Current dictated Photon greeting question is pending. No new human delivery or audio result yet. | Root owns next question; no duplicates. |
| Same-enrollment web continuity | BLOCKED | Existing Text the room enrollment's Chat here fallback must retain context/credential/expiry without a fresh join. | Root card C2. |
| Final-path end access / second guest | BLOCKED | Need denial, no stale native turn/device dispatch, owned-assignment cleanup and clean second-guest context. | Root cards C3/C4. |
| Native app visible rendering | BLOCKED | Storage/readback proven; navigate=true did not make Jay see the chat. | Actual human screen observation. |
| Native enrolled-device Bus tools | BLOCKED | Existing-thread dynamicTools registration unsupported by installed schema; private native-shell Bus helper reviewed/deployed at89a0b4c (296 Python+12 Node). Actual live helper use remains unaccepted. | Computer owner + Root. |
| Intended interactive Mac/phone effects | BLOCKED | Old restricted-path effects do not establish genuine conversation tool wiring. | Root card C5 after implementation. |
| Voice / lighter guest UI / cold rehearsal | BLOCKED for complete journey | Keyboard dictation input, meaningful automatic response, adapted live UI and unbriefed use need final evidence. | Audio, Owen and Root. |
| Features5–7 / performance | BLOCKED, CLOSED | No photo/scene/rule unlock. Rhythm generation, synchronization and projector untested. | Explicit selection/authorization plus relevant evidence. |

## Retained limits

- Earlier physical alternative attempt lost its selected phone and returned UNKNOWN without retry. Later successful runs do not erase it; its physical root cause was not proven by duplicate-registration unit tests.
- Original1.5s latency target FAIL; reported model turns were roughly3.6–3.7s and speech can take longer. Ack/response timing is not acoustic or optical onset.
- Long speech previously became UNKNOWN despite audibility. Current automatic speech is a brief whole first line up to12words/100chars, otherwise a short first sentence or on-screen fallback; do not claim full narration.
- Three smoke runs and one replacement do not establish field reliability.
- Preserve Mac's selected default output/current volume. Ordinary access ending preserves produced effects; host reset has explicitly configured light-OFF/music-pause cleanup. Report unconfirmed cleanup honestly.
- Requested unavailable device: explain, offer alternatives and wait for choice. UNKNOWN outcome: never automatically retry or substitute.

## Root-only cards, in coordinated order

These are procedures for Root when prerequisites exist, not requests for simultaneous tests. Root supplies actual links and names; never publish credentials.

### C1 — pending Photon greeting / automatic reply

Prerequisite: deployed d8fef91 and Root's already-pending dictated greeting trial.

Use Text the room, complete the intended enrollment, send the greeting in Messages. Confirm the real delivered reply and, separately, whether the meaningful brief response is heard on the Mac. Correlate inbound ID -> guest/lease -> exact fixed native thread/turn -> outgoing reply and speech request.

PASS components independently: correct enrollment/inbound, correct same-thread reply, actual delivery, actual audibility. HTTP acceptance or a speech ACK alone cannot pass the latter two. Dictation confirmation proves input method only if the human reports the recognized/sent words. Record zero/one native turn and duplicate handling. Do not resend an uncertain action.

### C2 — same enrollment, second channel

Prerequisite: C1 enrollment exists. Use that enrollment's existing Chat here fallback; do not create another guest.

Ask a natural follow-up referring to an innocuous detail established in Messages. Observe correct conversation continuity and exact same native thread. Verify linking is authenticated and guest identity/credential/original expiry unchanged; reconnect must not renew TTL or replay requests. New enrollment must not be confused with linking.

PASS: meaningful contextual reply plus identity/deadline/turn records, no duplicate native turn. A new lease with a copied transcript is not a pass.

### C3 — ending access, stale input and assignment ownership

End the active enrollment, then attempt a harmless further request from both linked channels. Observe denial/no new native turn or device dispatch. Exercise expiry and host-reset paths on the final integrated revision, including work waiting before dispatch.

PASS: original expiry enforced; authority rechecked at dispatch; old/pending commands cannot run under another guest; owned Photon assignments cleaned according to lifecycle; external pre-existing assignments untouched. If deletion/result is UNKNOWN, retain ownership/error evidence and do not claim confirmed cleanup.

Already-started effects are not promised to be undone by ordinary Leave. Host-reset explicit defaults require their own physical confirmations. Repeat after restart to check durable dedupe/ownership without replay.

### C4 — new guest and context reset

Root specifies admission/takeover boundary and treatment of already-running work first.

A establishes harmless working context and queues an observable safe action; B becomes a new guest before queued dispatch. Inspect new working context/authority and old queue records. B makes an unrelated request; stale A input is attempted.

PASS: B starts fresh; A commands/proposals/tool outputs are canceled or denied under A, never reassigned; stale A input produces no native turn/action; B works. One visible room chat may retain presentation history, so a visible nonce is not proof of isolation: inspect actual supplied context and dispatch identity. Reconnect grants no renewed authority. Unconfirmed cleanup of room-owned jobs blocks the next grant. Already-started OS/file effects may remain; this is not OS isolation.

### C5 — visible chat and actual computer/phone work

Prerequisite: reviewed runtime89a0b4c; first verify native inventory and an invalid-device request produce zero device sends, then coordinate an actual phone effect.

Human visibly opens the sole native Tenant chat and watches a fresh guest turn. Through genuine conversation request one harmless computer task, such as creating/opening a disposable text artifact with a unique marker in an agreed demo location; inspect actual content/window. Separately request an enrolled phone effect and observe it physically.

PASS: correct visible turn and intended effects, exact tool/request correlation, permission checks and honest errors/UNKNOWN. Text claiming completion does not prove the artifact/effect. Read/web tools alone do not pass interactive controls. No unrequested account actions, settings changes or installations.

### C6 — actual conversation voice and failure paths

Use supported phone/browser dictation or voice entry into the SAME conversation. Speak a fresh short request; observe recognized words, meaningful reply and brief audible response. Follow up naturally. Separately deny mic permission and use typing.

PASS: actual input -> same conversation -> correct response/effect, audible once, typed fallback works. No phantom command, stale audio replay or reconnect replay. End/revoke authority before queued speech dispatch and confirm denial. Source-level once-per-native-turn behavior and human hearing are separate checks.

### C7 — guest UI and unbriefed rehearsal

Prerequisite: Owen's adapted live revision integrated; selected journey's relevant cards pass.

First inspect real permitted controls, TTL, suggestions+free input, Leave and unavailable/ended behavior. Details may be one tap away; copy need not be a terms sheet. The displayed grant must match backend authority; reconnect cannot extend it.

Then give a fresh unbriefed participant only the public QR, necessary consent and goal: use the room/computer for something useful, then end access. Allow an unscripted follow-up. Do not teach command wording or repair navigation.

PASS: selected journey completed without coaching, intended effects observed, participant understands access ending, subsequent control denied, no hidden manual cues. Record raw feedback/help/errors and scan-to-first-effect timing against a preselected presentation budget. Assisted completion FAILS unassisted acceptance; fix and use a fresh trial.

## Evidence record

For every card: full deployed revision, UTC start/end, device/OS/browser, guest pseudonym, exact request, inbound/outbound/native-turn/device-request IDs, original/current expiry, native-turn/dispatch counts, machine result, human visible/audible observation, expected vs actual, PASS/FAIL/BLOCKED, owner/next unblock. Keep tokens, phone numbers, assignment identifiers and private content in private evidence, not public copy.

Implementation acceptance requires reviewed exact source, reproducible final-revision checks without unexplained failures/skips, intended integrated physical effects and correct negative paths. Historical commands: .venv/bin/python -m unittest discover -s tests and node --test tests/device-runtime.test.cjs; owners supply additional final checks.

Root publishes evidence and opens gates. No backend test count alone opens features5–7. Performance timing proposal remains in demo-ideas.md and requires separate authorization.
