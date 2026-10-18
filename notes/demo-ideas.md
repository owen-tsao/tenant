# Tenant demo ideas

Owner: demo planning. Current through reviewed runtime89a0b4c; consolidated October17, 18:31 PT.

Keep all candidates here and choose the final demonstration with Jay and Owen. Listing an idea does not authorize implementation or establish that it works. Current acceptance and test cards are in notes/demo-testing.md; scope/channel decisions are in notes/demo-alignment.md.

## Current product direction

Public QR -> temporary guest conversation with Jay's signed-in agent -> permitted computer and room actions.

Keep web chat. Photon is an authorized SECOND channel only into the SAME fixed native Tenant room conversation, not a second model or separate assistant. Same-enrollment web linking preserves identity, working context and original expiry. A new guest must receive fresh working context with no inherited pending commands.

One visible native room chat is requested. Thread storage/readback is proven; actual native app visibility remains unaccepted. Voice input must reach this genuine conversation, not a small command-word interpreter.

## Candidate: build a room performance

Jay's idea: compose an impromptu performance by adding devices as conversation develops.

1. Say “Can you start a beat on my computer?” and demonstrate a rhythm such as “dum, dum, dum, dum.”
2. Let the beat continue and ask for a change.
3. Say “Sync my phone flashlight with that.”
4. Ask for a matching computer visual, projected if a projector is actually connected.
5. Continue developing the performance naturally.

The appeal is continuity: each request builds on the last, and another device joins the same activity.

Status: CANDIDATE ONLY. Historical prepared music, Mac speech and phone torch passes do not establish rhythm interpretation, generated beats, synchronization, visuals or projector output. A private native-shell helper now connects the existing Bus in source-reviewed runtime89a0b4c (296 Python+12 Node checks); actual native-to-device effects are still unaccepted.

### Smallest timing experiment, after baseline acceptance and demo selection

First test rhythm interpretation separately: supply a four-beat rhythm, hear the resulting beat and confirm whether it matches. Prepared music cannot pass the generated-rhythm claim.

Only if an existing reusable timing path is available, test a fixed eight-beat loop for two 20-second takes with Mac audio and phone torch. Capture distinguishable audible beats and visible pulses in one recording with known frame/audio resolution. Record each onset offset, missing/extra pulses and change in offset from first to last beat. Model dispatch or WebSocket acknowledgement times are not physical onset evidence.

Predeclare this proposed feasibility criterion before testing: each measured offset <=100 ms, first-to-last offset change <=100 ms, no missing/extra pulses or catch-up bursts. An inconclusive recording is BLOCKED. Two takes are a feasibility screen, not reliability evidence. Do not build a scene engine or scheduler to rescue a failed spike.

Test a matching Mac visual separately. Projector claims require observing the actual projected output; no projector is a dependency.

Fallback: beat plus Mac visual only if both pass; otherwise prepared music with separately requested torch actions, explicitly described as sequential, not synchronized; otherwise the bounded QR/text/light/speech path after final-revision retest.

## Other candidates to preserve

| Idea | Spectator experience | Current position |
| --- | --- | --- |
| Borrow the room | Scan, ask naturally, control an enrolled light, hear the Mac, then end access. | Historical bounded physical core PASS; current genuine-conversation device actions and automatic audio need acceptance. |
| Keep going when a device disappears | Ask for a disconnected light, receive alternatives, explicitly choose one, and watch only that device respond. | Historical physical smoke PASS after one retained disconnect failure; no silent substitution or retry after UNKNOWN. |
| Show access ending | End access, try another action and see denial; host reset restores explicit defaults. | Historical core expiry/reset PASS; genuine-conversation final-path checks remain open. |
| Talk and improvise with the computer | Make a free-form request, let the existing agent use computer tools, then involve a phone. | Human free-form conversation and native local-read/web tools observed; intended interactive Mac/phone effects remain unaccepted. |
| Coordinate one room scene | One request produces an explicit light state plus a short spoken response. | Earlier planning recommendation, not selected or authorized for implementation. Exact scene belongs to Jay/Root after rehearsal. |
| React without another prompt | “Whenever someone joins, flash green and say welcome,” then stop future firing when the rule owner's authority ends. | Feature 7 planning only; one rule per guest, bounded existing events, cooldown and dispatch-time authorization. |
| Photo -> screen | “Take a picture of me and show it”: enrolled iPhone captures a still and a Mac renders the new image. | Feature 5 planning only; camera consent, torch contention, authorized upload/read lifecycle and display handoff need resolution. |
| Camera/perception interaction | A contributed camera supports a room interaction. | Future candidate only; perception, tracking, video and musical-chairs adjudication remain excluded from the current build. |

## Final-choice shortlist

1. Genuine computer/room conversation: QR, natural request, visible useful result, phone involvement, one unscripted follow-up and access ending. Prefer only after its actual gates pass.
2. Bounded room borrowing: QR/text/light/short speech/denial. Strongest historical physical evidence; retest final deployed behavior before using it as fallback.
3. Progressive performance: strongest expressive candidate; choose only after the rhythm, device-tool and timing checks pass.

No final demo selected. Choose the smallest sequence that works visibly, fits the agreed presentation budget and permits an unscripted follow-up. Keep unbuilt portions out of working-demo claims.

Features 5–7 IMPLEMENTATION GATE CLOSED. Beat/light/projector and guest-supplied agents remain candidates/deferred work. Backend test counts do not open these gates.
