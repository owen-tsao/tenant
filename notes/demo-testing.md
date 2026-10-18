# Tenant demo acceptance

Owner: demo planning. Updated October17,18:47 PT.
Main inspected for this planning revision: b748ca15a3bdaf4fabf2c88388d78e02ba151594.
Latest evidence updates below are attributed to Root; planning has not independently rerun live checks.

Root schedules all live tests and human questions, one at a time. Audio owns music/timing; Lighting owns execution/permission acceptance; Owen owns ALL web files. Planning evaluates experience and records claims, not implementation.

## Evidence rules

PASS = named check passed within recorded scope/revision.
FAIL = completed check violated its criterion.
BLOCKED = missing implementation, decision, equipment or evidence.

Reviewed source, automated tests, live transport, human experience and physical timing are separate evidence. HTTP202, ACK, waveform or navigate=true do not prove delivery, audibility, physical onset or visible chat. Historical passes do not accept changed runtime. Local test counts are not final integrated acceptance.

## Current matrix

Root update, October17 19:13 PT: Brain6cb644a and Mac audio af6f8be were used for the latest live music trial. Jay confirmed a continuous 90 BPM beat and the spoken tempo answer. First longer narration returned UNKNOWN; reviewed player-budget fix4198998 is committed but not yet deployed. Phone attachment FAILED at its first ON after a166 ms acknowledgement window; no retry. Explicit host reset rotated the room to0C4C, confirmed context/program cleanup and acknowledged OFF/pause, but aggregate cleanup remained unconfirmed. Audio/core owners are reviewing a60 BPM/500 ms pulse baseline and truthful first-cycle receipt before the next physical check. These outcomes supersede pending-only statements in the historical rows below; no synchronization claim passes.

| Check | State and evidence | Owner/blocker |
| --- | --- | --- |
| Historical bounded core | PASS at evidence6075a3a, runtime4c4b474/QR ba6248c: three physical guest runs, explicit alternatives, light/audio, access-ending denial, actual600s expiry, two resets OFF+pause and four queued turns denied. | Root; historical scope only. |
| Genuine conversation | PASS: ff6ab19 natural public guest request/reply verified in fixed native thread; human phone conversation and native local-read/web tools observed. Old restricted planner not used/fallback. | Root; not all physical tools. |
| Dictation + automatic Mac speech | PASS human-confirmed on genuine native web conversation. Root published actual voice/helper inventory evidence atb058309. | Not full music/native-phone acceptance or long-answer narration. |
| One real guest replacement | PASS: earlier working context cleared; stale request denied without native turn. | Lighting/Root; broader final-path lifecycle still open. |
| Deployed helper baseline | PASS reviewed source89a0b4c,296Python+12Node,19 private helper tests. Per-turn Unix helper via additionalContext, not dynamically registered MCP. | Historical deployed baseline, not final multi-action acceptance. |
| Native inventory | PASS observed Mac and Jay phone; evidence publishedb058309. | Inventory is not a physical effect. |
| Requested multi-blink | Historical refusal and two incomplete trials retained. Fresh-enrollment trial at6cb644a:10 phone ACKs and Jay confirmed visible blinks; Mac speech FAILED before playback. | Phone smoke only. The combined phone/speech trial did not pass. |
| Photon enrollment | PASS actual enrollment occurred. Verified native iMessage inbound/delivery remains BLOCKED on evidence supplied here. | Root owns live card. |
| Same-browser Photon recovery | Earlier PHONE_IN_USE reproduced. Fix9c479c6 is included in deployed8f1b7ee; original secret/expiry preserved in reviewed tests. | Actual fresh phone recovery, native inbound and delivered reply remain pending. |
| Photon live card/test | Root reportsf1fc5b2 locally. | A test/card artifact is not a delivered reply or human audio observation. |
| Multi-action source | PASS reviewed/deployed8f1b7ee:324Python in isolated current-base snapshot plus12 unchanged phone-runtime checks. Both same-device sequencing and receipt findings fixed; local access and Lighting owners reviewed. | One real request produced10 phone ACKs and explicit Mac speech ACK; human observation pending. Audio programs excluded. |
| Music/timing | AUTHORIZED. One live continuous beat plus conversational spoken answer human-confirmed. Phone attachment FAILED first ON/UNKNOWN; no replay. | Physical synchronization and final-revision adjustment/stop remain BLOCKED. Next baseline60 BPM,500 ms ON/OFF after reviewed fix. |
| Native visibility / interactive effects | BLOCKED: navigate/readback not visible rendering; intended native Mac/phone effects need observation. | Root/Lighting. |
| Same-enrollment continuity / final lifecycle | Post-leave old-guest request PASS: denied with0 native/device commands. Linking, real expiry/reset, queued work and second guest on final integrated program runtime remain open. | Root/Lighting. |
| Adapted UI / unbriefed evaluation | Owen main9c5e6fa guest/setup pages integrated as8cdeb82; his exact display retained. Final selected unbriefed journey remains BLOCKED. | Owen/Root/E1. |

## Retained limits and invariants

- Earlier physical alternative attempt lost its selected phone and returned UNKNOWN without retry. Later successes do not erase it; its physical root cause was not proven by duplicate-registration tests.
- Original1.5s latency target FAIL; reported model turns about3.6–3.7s are not acoustic/optical onset.
- Long speech previously timed out despite audibility. Current automatic speech is a brief excerpt, not full narration.
- Preserve Mac's selected default output/current volume.
- Ordinary Leave ends authority and preserves produced effects. Host reset has explicit light-OFF/music-pause defaults; report unconfirmed cleanup honestly.
- Unavailable requested device: explain, offer alternatives and wait for the guest's choice.
- UNKNOWN outcome: never automatically retry or substitute.
- Known-unsent and UNKNOWN must be distinguished from actual send evidence. A pre-dispatch denial/validation failure must not be misreported as an attempted physical action.
- Same-device program actions must follow the reviewed serialization/cancellation contract. Do not accept overlapping blink programs merely because each individual call passed a unit test.
- Multi-step natural requests are authorized. Do not restore arbitrary one-action or three-blink ceilings; real authority, cancellation, resource deadlines and no-replay rules still apply.

## Engineering acceptance cards — Root coordinates

These are owner procedures and prerequisites, not competing instructions to Jay. Root selects the exact deployed revision and supplies links/device names privately.

### C1 — Photon and same-enrollment channel continuity

Complete actual enrollment -> native inbound -> SAME native room conversation -> delivered Messages reply. Record audibility separately. Then use that SAME enrollment's existing Chat here fallback for a natural contextual follow-up.

Require unchanged identity/secret/original expiry and no duplicate native turn. Re-enrollment/recovery must not silently grant fresh authority. Verify recovery from the same authenticated browser after the PHONE_IN_USE fix.

PASS components independently: enrollment, inbound, same-thread reply, delivered message, human-heard response and linked-context continuity. HTTP acceptance and speech ACK cannot pass delivery/audibility. Dictation counts as observed input only when recognized/sent words are confirmed.

Preserve external assignments. Cleanup deletes only assignments durably owned by the adapter. The earlier read-only preflight found ONE external assignment under assignments, not items.

### C2 — access, cleanup, restart and guest replacement

Exercise Leave, expiry, reset, reconnect and NEW guest on the final integrated path. Include work waiting before native turn/device dispatch and an active program where the approved lifecycle contract permits testing.

Inspect identity/context/queue records, not model memory alone. Old work must not be reassigned to the next guest. Same-enrollment linking preserves context; a new guest clears working context and pending commands. Reconnect renews neither authority nor TTL.

PASS: stale requests produce no unauthorized native turn/device dispatch; cleanup is bounded and accurately reported; unconfirmed required cleanup blocks a fresh grant; restart does not replay requests or lose assignment ownership/deduplication guarantees.

Already-started OS/file effects may remain; this is not OS isolation. Ordinary Leave does not promise undo. Host-reset explicit defaults require actual physical confirmations.

### C3 — corrected multi-action execution and receipts

Basic prerequisite PASS at8f1b7ee: both review findings fixed and independently reviewed,324Python+12 unchanged phone checks. Background program changes require their own final combined review/checks. Earlier318 count is intermediate.

Execute supported multi-step natural requests without the arbitrary guard. Check authority at every actual dispatch after queue waits. Test sequential calls, concurrent same-device requests, program replacement/stop, expiry/cancellation, partial failure and disconnect.

PASS: intended ordering/serialization matches the reviewed contract; stop prevents queued old pulses from appearing afterward; completed subactions reported independently; known-unsent cases have zero sends; uncertain dispatched outcomes remain UNKNOWN without retry/substitution.

No aggregate “done” when only part succeeded. Source checks do not pass physical blink behavior.

### C4 — music, conversation, synchronization and stop

Audio/Root prove an audible beat continues while the guest converses, the phone joins in time, a requested change takes effect and explicit stop ends the requested performance.

Stop covers both requested outputs and queued pulses. Record initial/final skew, per-pulse offsets, drift, missing/extra pulses and catch-up bursts with known recording resolution. Do not infer synchronization from command/ACK times.

Use demo-ideas.md's predeclared timing screen, agreed before testing. Two20-second takes are a feasibility screen, not reliability. An inconclusive recording is BLOCKED. No projector dependency and no output/volume changes.

If only prepared audio works, label it prepared. If synchronization fails, sequential actions must not be described as synchronized. A reduced demo needs Jay/Root's explicit choice.

### C5 — native visible chat and useful interactive work

Human visibly opens the sole native Tenant chat and watches a fresh guest turn. Through genuine conversation request one harmless computer task, such as creating/opening a disposable text artifact with a unique marker in an agreed demo location; inspect actual contents/window. Separately request an enrolled phone effect and observe it physically.

PASS: correct visible turn and intended effects, exact tool/request correlation, permission checks and honest failure/UNKNOWN handling.

Text claiming completion does not prove a file/effect. Native read/web tools and inventory do not pass interactive controls. No unrequested account actions, settings changes or installations.

### C6 — voice and response coexistence

Use supported phone/browser dictation into the SAME conversation. Speak a fresh short request, observe recognized words and meaningful reply, then follow up naturally while the beat is actually running.

Observe whether the brief response is audible and understandable without changing output/volume. Distinguish music masking speech from absent playback; no automatic output switching/ducking is assumed.

Test typed fallback and mic denial where applicable, authority ending before queued speech dispatch, and reconnect without replay. Source-level once-per-native-turn behavior and human hearing are separate checks.

Preserve the existing human-confirmed web dictation/speech PASS; these additional coexistence/failure checks are not implied passed by it.

## E1 — short unbriefed performance journey

Planning owns evaluation design/results; Root conducts one participant at a time after engineering acceptance. No overlapping live test or competing human question.

Prerequisites: final integrated source reviewed; relevant automated checks pass without unexplained failures/skips; Audio timing/stop and Lighting authorization/execution acceptance pass; required devices online; Owen's actual entry path available. Test web first; Photon separately after its channel passes. Do not silently enroll a tester twice to fix continuity.

Sample: TWO fresh first-use participants individually. If only one is available, report1/1 observed and second trial BLOCKED. Retain failures in the denominator; repaired reruns are separate attempts. This is a small experience sample, not reliability evidence.

Predeclare a proposed three-minute budget from opening invitation through explicit stop/Leave. Jay/Root may choose another budget BEFORE trials. Record functional completion separately from meeting the budget.

Give only necessary consent and this goal:

“Use the room to make a short performance with computer sound and the phone light in time with it. Change it while it runs, then stop it and end your access.”

No command wording, architecture explanation, navigation coaching, hidden cues or narration. Observer silently records raw requests and visible/audible results. The goal asks for coordination: success does NOT prove spontaneous discovery of synchronization.

### PASS criteria

1. Entry without help.
2. Natural request produces an audible beat.
3. Follow-up is understood while output is actually running.
4. Phone visibly joins in time, supported by engineering timing acceptance.
5. Adjustment observed during output without unintended restart/duplicate playback.
6. Explicit stop ends requested audio/light program with no delayed pulses.
7. Leave ends authority; subsequent harmless control attempt denied with no dispatch.
8. Completion within predeclared budget; otherwise report functional outcome and budget FAIL separately.

Do not require a specific mood, rhythm, phrase or action count. One request may contain multiple steps.

### Failure and blocked criteria

FAIL: coaching/hidden cues, missing/wrong effect, lost context, refusal of supported multi-step request, false completion, silent substitution, retry after UNKNOWN, continued program after explicit stop or stale authority dispatch.

Safety intervention is allowed but makes unassisted completion FAIL. A budget miss is a budget FAIL even if functional completion succeeds.

BLOCKED: implementation/device/evidence missing, unresolved lifecycle contract or timing inconclusive. Do not average away a component failure.

Ordinary Leave preserves effects; explicit stop comes BEFORE Leave. Authority expiry mid-program must follow the owner-approved program lifecycle contract. Lighting/Root test expiry/interruption races separately.

### Observation record and claims

Record each participant's deployed revision; entry/first-effect/adjust/stop/Leave times; raw requests; turn/program/device IDs privately; assistance/errors; actual output; expected/actual results; functional and budget outcomes.

Afterward ask “What did you control, and what did ending access do?” Retain their words.

If2/2 pass, claim only these two people completed this final-revision journey without narration, with observed composition, continuity, adjustment, stop and bounded denial.

Do NOT claim field reliability, arbitrary devices/rhythms, hard realtime, untested channels/projector, perception/photo, complete OS isolation or all failure modes.

## Concrete UI requests — Root routes to Owen

Preserve compact plum presentation and permission details one tap away.

- Truthful session/controller, TTL/Leave and actual device availability.
- Free input remains usable while audio runs.
- Same-enrollment Text the room recovery without new identity/expiry.
- Program starting/running/stopping/stopped/unknown only from authoritative backend evidence; never infer stopped from requested state or elapsed timer.
- A Stop affordance is contingent on a defined backend seam. Text stop also needs integrated acceptance. No new frame assumed.

Read Owen's main notes through17:52: QR only on printed card/deck last slide; operational display is not a judge QR surface. Do not restore a display QR or older API-key/Photon-absent assumptions. No web edits from planning.

## Evidence and gates

For every engineering card: full deployed revision; UTC timestamps; request/native-turn/message/program/device IDs; expiry before/after; native-turn/send/dispatch counts; machine outcomes; actual optical/acoustic/window observations; expected/actual; PASS/FAIL/BLOCKED; owner/next unblock.

Keep secrets, phone numbers and private identifiers out of public copy. Root publishes exact evidence.

Current local work must be reviewed, integrated and deployed before its results are called final. b058309 publishes voice/helper inventory evidence; localf1fc5b2 is a Photon live card/test, not a human delivery result. Earlier318 checks were intermediate; execution/receipt findings are now fixed in reviewed/deployed8f1b7ee. See tests/evidence/2026-10-17-native-multi-action.json. Automatic narration after explicit speech returned UNKNOWN at the legacy4s budget; Audio owns suppression/deadline fixes, not yet deployed. Do not replay that uncertain output.

Music coordination is OPEN for implementation, BLOCKED for physical acceptance. Photo, perception, proactive rules and guest-supplied agents remain CLOSED. Backend counts alone prove no working demo.
