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
