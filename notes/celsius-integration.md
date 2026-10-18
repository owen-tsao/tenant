# Celsius — main / Lighting interface agreement

2026-10-18. This is an ownership and integration contract, **not a connected model bridge or an accepted live scene**. Read the sibling `tenant-celsius-lab/README.md` and `TRANSFER-TO-LIGHTING.md` for the source and acceptance inventory.

## Ownership and resources

- **Lighting & Device Runtime (Local):** isolated capture app, camera/OCR, local ASR/transcript, lab commands/receipts, input calibration and lab-side event reader/coalescer/cursor. Do not edit shared Tenant conversation/session seams without main's agreement.
- **Main / Access & Device Adaptation:** the entry into the same existing room conversation, controller/lease/room-generation checks, observation context, native turn ordering/steering, model selection and integrated effects acceptance. No new chat or separate model process.
- **Tester:** independent review and one coordinated live test at a time. Finish/release its exact stale old test lock before Lighting acquires a new one; do not unlink an actively locked file.
- **TV:** stays on main's accepted drawing/photo album until separately released. No evidence projection or window movement in the first input-only check. Main is not using the camera or microphone.

Read-only OS metadata on this handoff reports: MacBook Pro Camera not exclusively used by another app; MacBook Pro Microphone hardware idle; current default input **Bose NC 700 HP**, also idle. This is an availability reading, not proof that capture/ASR works. The prototype currently uses the default input: Lighting must explicitly select the built-in microphone inside its own capture setup for Jay's requested scene. Preserve system default, output and volume.

## First gate — input only

After the stale test lock is confirmed released, acquire the live lock for exactly one finite Start → still readable can → movement + a fresh naturally spoken phrase → Stop trial. Explicit Start and any real OS permissions remain visible. Verify the actual frame, event identity/order and live transcript. Keep the TV, other apps, music/lights and model bridge idle. Record stage times individually; report camera/mic released at the end. Any permission or object-positioning dependency gets one clear request to Jay, not an assumed pass.

## Adapter → main observation contract

No new main callable is implemented yet. The planned receiver belongs alongside `ConversationAgent` in main; **do not send observations as synthetic guest commands through `agent.turn()`, `codex queue`, cross-chat messages, or a parallel `RoomSession.start_turn()`**. Main must admit observations under an explicitly armed scene and the existing controller/lease, room epoch and native-turn ownership.

The lab-side adapter supplies one immutable envelope per accepted observation revision:

| Field | Required meaning |
| --- | --- |
| `session_id`, `event_id`, `kind` | Exact source JSONL values; deduplicate by session + event ID. |
| `unix`, `monotonic` | Exact source event timestamps; distinguish source receipt time from physical exposure. |
| `segment_id`, `provisional`, `text` | Speech revision metadata where present. Preserve negation/revisions; microphone speech is not speaker-identified. |
| `latest` | Snapshot from this same capture session, with frame ID, source, original label bounds and observation timestamps; identify if it changed during the read. |
| `frame_ref` | Real local frame from the same private session folder, never an invented or previous-session image. |
| `transcript_tail` | Bounded current-session text, marked as observed speech rather than instructions or verified truth. |

Tail `events.jsonl` with a persisted session-specific cursor. `agent-inbox.json` is replaceable and is not a lossless queue; `control.py watch` currently starts at EOF, so it alone cannot recover startup or missed events. Reset the cursor explicitly on a new Start and never replay old effects on bridge restart. Preserve adjacent movement and speech observations; coalesce partials by segment/revision and avoid executing both a pause and an identical final twice. A changed final/negation must remain visible to the agent as a correction, not be silently dropped. Failures with an unknown effect outcome are not automatic retries.

`capture_stopped`, changed session, lost scene authority, expired/revoked lease or room reset invalidate pending observations and effects before dispatch. Main supplies the precise receiver implementation only after the input gate passes. Lab source records and private transcripts remain on disk; don't commit or expose them through public pages.

The lab now provides `reader.SessionReader(root, session_id).poll()` and `still_current(envelope)`. Main independently reran its 11 synthetic file checks successfully. `still_current` fences capture Stop/session replacement; it does **not** refresh a pinned observation's age. Main must separately recheck observation age at use after any queue/model delay, require a real `frame_ref` and consistent snapshot, and obtain new evidence or decline when stale. `observation_fresh` describes the poll-time snapshot only. Claim-before-return is at-most-once delivery: a crash after a durable claim may lose an observation, and is not evidence of guaranteed delivery or exactly-once physical action.

## Main conversation / effect behavior

Main will use the existing `ConversationAgent` ownership and native-turn/steer machinery, plus separate application context for observation data. Normal guest input stays exact; OCR/ASR is untrusted source material and cannot grant arbitrary computer authority. The finite scene permit covers a brief question and fresh evidence presentation. It does not re-enable automatic narration for ordinary chat or authorize broader actions from overheard speech.

Use the existing same chat, with a supported fast model / low reasoning setting only for the scene if the setting can be managed and restored. [Official App Server documentation](https://learn.chatgpt.com/docs/app-server) states that model/effort overrides become defaults for later turns on the thread; they are not automatically transient. Main must read/save the baseline, explicitly restore and verify it before normal chat resumes, or preserve the existing setting until that restoration path is proven. Do not alter global config. Keep the event worker warm; do not call a model on every camera frame. Measure stage and full-loop times before promising the provisional 1.5 s question / 2 s evidence targets: a full coding-agent tool loop may miss them.

The agent composes each actual response. Label movement is only a candidate attention event, not proof of drinking intent. Read the actual evidence and spoken context; a known/joking/negated statement should not receive a canned medication warning. Visible CELSIUS packaging alone does not establish actual contents or individual health effects.

Use the lab's real session-bound `say` / `present-label` operations and inspect their receipts. Presentation requires a newly checked readable label within the app's two-second fence at execution time, and an explicitly selected display. Handle missing/unreadable/changed evidence by saying it is unavailable. A receipt is not a physical TV/audibility pass. Initial speech is half duplex, with no supported barge-in; test speaker feedback before accepting a conversation loop.

## Current status

The owner's 22 native checks and six synthetic OCR checks remain separately reported; main has not rerun those app checks. Main independently ran all 11 event-reader checks against synthetic temporary session files only. Lighting then verified its exact input-test lock holder released/exited and the original lock inode is free; its gate is waiting-for-user, with Start unclicked and no capture session created. Physical input, Speech permission/live ASR, agent integration, TV evidence presentation, speaker feedback and full-loop latency remain unaccepted. No capture, microphone, model invocation, speech or TV action was started by main during this handoff.
