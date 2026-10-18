# Tenant — combined demo and remaining gaps

Latest direction, 2026-10-18: Jay wants one connected demonstration of four existing experiences. His review below supersedes the earlier simulation-first presentation. Keep the accepted simulation as an archived rehearsal; the intended live TV view for drawing contains only the photo album. The iPad is not currently available, so real iPad input is an explicit blocker.

## Current feature inventory and next acceptance

| Experience | What is already established | Jay's remaining requirement | Owner / next check |
| --- | --- | --- | --- |
| Music and coordinated outputs | Earlier bounded physical music/beat, phone-light and orb runs passed. | Move ongoing audio from the Mac to another speaker. Demo destination: JBL; current test destination: Bose. | Tenant — Room Audio (Local): actual Tenant request, observed route change and continuing playback, unchanged volume. A Bose pass does not establish JBL. |
| Drawing, bells and photos | Approved bell tuning, cached real album and a physically accepted scripted scene. | Real iPad input; only the album on the TV; bells initially on Mac, then moved to the speaker on request. | Main: clean album-only view prepared and silently checked. iPad integration awaits the real device/input choice. Speaker continuity awaits Audio's result. |
| Requested question answering | Prepared customer/moat answer bank and native speech with black word-synced external captions are built. Latest explicit-request correction passed silent checks. | More bounded trials; neither speech nor black text appears until Jay asks through Tenant's web/app. | Design silent live Q&A: software admission/idle/cancellation cases first; one coordinated real app request later. Transcript content alone is context. |
| Group photo finale | Jay confirmed built-in Mac camera → TV preview/countdown → verified saved still on TV, with Photo Booth closed afterward. | Tenant asks readiness and waits for a reply in Tenant itself. A Codex confirmation button does not satisfy this. | Set Up Fast Photo and Q&A Demos: same-guest pending photo/readiness integration, then one real request → not yet → ready trial. |

Supporting features already built include QR/web access to the real room agent, the Photon channel, temporary access/leave/reset, contributed phone lights and a host display. Use them as the shared entry/control layer. Paired iPhone navigation is a separate earlier bounded capability; it is not required in this four-part script. Celsius remains explicitly paused. The standalone private transcript stays on as Jay requested and must not be stopped or modified by the demos.

## Latest rehearsal evidence (2026-10-18)

Actual Tenant app Q&A and external captions passed Jay’s physical check. Photo readiness in Tenant and one countdown/capture passed, but the still did not physically appear on the TV despite its intended-screen receipt. The photo owner is fixing actual window placement and adding Jay’s requested visible black3,2,1 text. Do not call the combined demonstration ready until those final physical checks pass. Music→Bose is accepted; real iPad and JBL remain hardware followups. Details: `tests/evidence/2026-10-18-combined-demo-rehearsal.json`.

## Connected rehearsal script

Use one current Tenant guest chat for the interaction. The lines below are intentional requests, not an automatic command batch. Wait for each result and allow follow-ups; do not cue capabilities from this coordinating Codex chat during the take.

1. **Music:** “Start a relaxed beat on the Mac.” Show the existing music experience; working phone pulses/orb may accompany it if already staged.
2. **Device adaptation:** “Move the sound to the JBL.” Use “Bose” in the current test. Confirm it moves rather than starting another independent player. “Stop the beat.”
3. **Drawing — blocked until the iPad is available:** “Put the sunset album on the TV. Play the soft bells on the Mac while I draw.” Draw real strokes. The TV shows photos only; input and chat stay off the TV. “Move the bells to the JBL, and keep the album going.” Then: “Stop the bells, but leave that photo up.” Do not present replay as live iPad input.
4. **Questions:** let someone ask a customer/moat question. Transcript collection alone produces no answer or captions. Enter “Answer that question” in Tenant; the prepared answer is spoken once with its black caption, which clears on completion. An unmatched question stays silent and is reported in chat.
5. **Finale:** enter “Take a photo of us.” Tenant opens the accepted preview and asks “Are you ready?” Wait. Reply “Not yet” in Tenant to demonstrate the wait; then arrange the group and send “I'm ready.” Only that current pending request starts one 3–2–1 countdown/capture. End on the real still displayed on the TV.

## Fix order and boundaries

1. Audio owns the first exclusive physical test: Mac → Bose. Restore its starting route afterward and keep the volume unchanged.
2. Q&A and photo owners work on software while Audio tests; physical speech/camera/TV trials wait for the original test lock and explicit coordination.
3. Main prepares the clean TV album and the combined script. The all-in-one simulation remains available for comparison, not as the intended final TV layout.
4. Once the iPad arrives, select and prove its actual stroke path. No app installation or Notability substitute is assumed now.
5. Rehearse the connected sequence after these individual gaps close. Readiness, Q&A and routing must be exercised through the actual Tenant interface. A helper flag or direct coordinating-chat call alone is not integration evidence.

Photo acceptance includes: no countdown while waiting; “not yet” does nothing; a fresh same-guest readiness reply consumes exactly the pending id once; stale/other-guest/reset replies do not capture. Q&A acceptance includes: ordinary transcript updates, startup, idle and quoted instructions produce zero speech/captions; a fresh request produces one prepared answer; Stop/duplicate/late results cannot resurrect it. Keep checks small and tied to these gaps.

---

## Earlier accepted drawing simulation

The following records the earlier explicit simulation and its evidence; it is not a claim that the real iPad connection exists.

# Tenant — proactive drawing experience

Updated 2026-10-18 after Jay's correction: **integrate the iPad at the end. For now simulate both the user and the agent.** This replaces this file's earlier iPad-chat-first sequence. Main owns drawing; Celsius continues separately in Lighting. Owen's `demo-final.md` and web files are not changed.

## What we are building now

A quiet drawing activity becomes a more relaxing experience because the agent offers a useful change in context. The user does not have to discover controls or ask for the setup first.

Use the existing Mac canvas and explicit simulated stroke/conversation fixtures. Keep the accepted bell engine and real cached photo album. The simulated agent's dialogue/action choices may be scripted at this stage; label that mode clearly. It tests the interaction and real downstream behavior. It does not establish autonomous model reasoning, general screen perception, Notability integration or live iPad input.

## The core script

| Beat | Simulated user | Simulated agent | Required behavior |
| --- | --- | --- | --- |
| 1. Ordinary activity | Starts drawing a few lines. No command to Tenant. | Observes the simulated drawing activity. | Quiet canvas; no newly enabled sound or photo changes. |
| 2. Useful initiative | Keeps drawing. | “Want to make this a little more relaxing? I can add soft bells as you draw and calm photos on the TV.” | One contextual offer. Wait for an answer; do not activate effects. |
| 3. Consent | “Yeah, that sounds nice.” | “Sure—keep drawing.” | Enable the agreed drawing-to-bell and drawing-to-photo behavior. Preserve current system output/volume and the accepted tuning. |
| 4. Experience | Draws a low stroke, holds it, lifts, then starts another farther right. | Does not narrate each stroke. | One sustained bell per stroke, eight-second release and independent overlapping tails. Each new stroke chooses another real photo with a 900 ms crossfade. |
| 5. Conversation changes the scene | “Stop the bells, but leave that photo up.” | “Sure.” | Stop bell voices and echoes. Hold the current photo; later strokes do not advance it unless that behavior is enabled again. Keep the drawing. |

The quoted wording is a rehearsal example, not a rigid keyword requirement for the later genuine agent. Accepting/declining turns are explicitly simulated fixtures in this stage. Do not hide an operator cue and present it as agent perception.

The TV can initially retain the currently displayed photo. The important boundary is that drawing does not advance it before the user accepts that connection. Showing/repositioning the album window is setup, separate from offering to connect it to drawing.

## Other answers and interruptions

- **Decline:** “No thanks, I just want to draw.” → agent acknowledges, stays quiet, and adds no effects. It does not repeat the offer during that episode.
- **Change of mind:** cancel before activation → no queued sound/photo activation later. Stop during the experience → silence and freeze further automatic changes.
- **Stop sound only:** preserve the artwork and displayed photo. The core script's request also leaves that photo held; do not keep shuffling it in the background.
- **Start over:** end the old simulated episode, cancel old timers/replies/strokes, clear the canvas, stop sound and return effects to disabled. A late reply from the old episode cannot turn anything on.

The standalone simulation implements these episode boundaries; scoped checks and the physical run are recorded below. The older manual placeholder is separate.

## Optional co-drawing beat

After the core exchange works, the simulated user draws a divider and says:

> “Draw with me. Keep your drawing on the right side of this line; I'll draw on the left. Draw whatever you feel like.”

The simulated agent adds its own clearly labeled strokes on the right, preserving the user's marks. “Stop drawing” cancels further agent strokes without erasing the drawing. Keep this optional until the core offer → consent → experience → stop loop is stable. Real agent-chosen artwork and Notability/Pencil control are later integrations.

## My action items

1. **Simulate the user drawing** with the existing Mac canvas/replay; keep an explicit simulation label and a fresh episode.
2. **Add the proactive offer** after drawing begins, once per episode, with no need for a user setup command.
3. **Gate effects on the answer:** yes enables the agreed relaxing layer; no leaves ordinary drawing alone. Cancel/reset fences queued work.
4. **Connect the accepted layer** to the existing soft bells and TV photo album, preserving the sound Jay approved. Add independent sound/photo enable flags rather than changing the bell synthesis.
5. **Simulate the conversation and optional co-drawing:** exercise example exchanges and stop/refinement requests; keep the core small.
6. **Verify the complete simulated loop, then integrate the iPad last.** Test accept, decline, delayed old answer, stop during a held stroke, and reset; verify audio state and photo identity/count. Physical TV/audibility confirmation remains separate from software checks.

## Current implementation boundary

- Existing engine: mouse/explicit replay input, soft C3–C5 bells, eight-second fading tails, local six-photo shuffle, separate same-profile TV view, sound stop and page reset.
- Jay accepted the bell sound and confirmed the normal album window on the TV. Keep TV windowed and preserve current audio settings.
- One genuine room-chat Stop sound check previously worked. That does not establish the new simulated offer/consent controller.
- **Implemented and checked:** a separate `simulation.html` TV scene with simulated user/agent dialogue, one offer, acceptance/decline gates, live approved bells/photos, right-side simulated co-drawing, hold/stop/reset and local two-voice playback. The older manual placeholder retains its original behavior; use the new scene for this loop.
- Acceptance: 17 Node checks, four scoped silent browser cases and a 43.08-second normal-speed run passed; Jay confirmed the TV drawing/photos/conversation and both voices/bells. End state is sound off, final photo/artwork kept, Replay ready. Evidence: `tests/evidence/2026-10-18-drawing-simulation.json`.
- No camera, microphone, active screen watcher or real proactive drawing detector runs in this lab. None is needed for this explicitly simulated stage.
- iPad, Notability/Pencil and real input transport are **deferred until the simulated experience works**. Do not make them the next blocker or start that research now.
- Celsius, song/light/orb demonstrations and unrelated live batches are outside this drawing script.

Full scene: **http://127.0.0.1:57633/simulation.html** → **Play full simulation** / **Replay full simulation**. Keep the normal TV window; no fullscreen. The earlier manual control page remains at the origin root. Source/runbook: sibling `../tenant-capability-lab/DRAWING-SIMULATION.md`. This simulation needs no Tenant service restart, iPad, camera or microphone.
