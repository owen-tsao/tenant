# Tenant — chat-led demo draft

Updated 2026-10-18. Jay controls the genuine room agent from **Tenant chat on the iPad**. No handwriting commands or Notability connection are implied. This draft supplements the earlier `demo-final.md`; it does not overwrite Owen's recording script or turn untested scenes into accepted features.

## The story

“Tenant gives an agent temporary access to the capabilities around you. I can start with one thing, add another while it is running, and change my mind through the same conversation.”

Use the strongest accepted sequence as the core. The creative scene is optional until its current chat-to-display path is checked. Don't squeeze every experiment into the presentation.

## Core sequence — about 90 seconds, plus actual agent response time

| Jay says in iPad chat | Expected real action | What the audience sees or hears |
| --- | --- | --- |
| “Play Cyanide on the room computer.” | Agent checks current playback and starts the existing managed recording if nothing is already playing. | The actual song begins. No generated substitute. |
| “Make the connected phone light pulse along with this song.” | Agent attaches the selected online phone to the current song program. If more than one target is ambiguous, Jay chooses. | The phone joins the running song; the song is not restarted. |
| “Put the reactive orb on the TV. Keep the music and phone going.” | Agent updates only the current program's visual flag. | The live orb appears while the other effects continue. It reacts to audio energy; don't describe it as an exact beat detector. |
| “Turn off just the phone light. Keep the music and orb.” | Agent detaches the phone and confirms OFF without stopping the song. | Light stays off; the rest continues. |
| “Stop the song and hide the orb.” | Agent stops the same program and verifies its outcome. | Music and orb stop. |

Present-tense claim: earlier physical trials showed these combinations working on this Mac and phone. A fresh combined iPad run is still required before calling this exact script ready. Don't describe general device compatibility or precise synchronization as proven.

## Creative scene — about 45–60 seconds, only after its chat check passes

Transition: “I can also use the room for something creative.”

| Jay says or does | Expected real action | Visible or audible proof |
| --- | --- | --- |
| In iPad chat: “Show the sunset photo album on the TV.” | Agent reuses the prepared local album/control pages in the same Chrome profile and shows the album in the TV's normal window. | A real sunset photo fills the album window. |
| In chat: “Enable the soft drawing bells. Keep those long echoes.” | Agent clicks Enable quiet sound; keeps the accepted tuning and current output. | Enabled status. No claimed sound until an actual stroke. |
| On the **Mac**, draw two or three mouse/trackpad strokes, starting at different horizontal positions. | Existing local stroke routing sustains one bell per stroke; lifting starts its eight-second tail. Each new stroke advances the album. | Lower/higher bells overlap, and real photos crossfade on the TV. State plainly that the current input is the Mac trackpad. |
| In chat: “Stop the bells, but leave that photo on the TV.” | Agent clicks Stop sound, without Start over. | Echoes stop; the same photo remains. |

If showing only a sample, say “Here is the prepared sample drawing,” and explicitly request sample replay. Do not present sample replay as live iPad drawing. A Notability/Pencil version remains a separate future input connection.

## Optional Celsius ending — reserved, not yet accepted

The side lab is preparing an actual camera/OCR mismatch observation. Only add it after a separate handoff and physical acceptance: visible captured label, evidence-based short interruption, no invented medical assessment, and a clear camera start/stop. Until then omit it from the live script; mention it only as work in progress if asked. No camera is used by the drawing scene.

## Optional co-drawing scene — Jay's new idea, queued

Jay draws a divider down the middle, then asks in chat: “Draw with me. Keep your drawing on the right side of this line; I'll draw on the left. Draw whatever you feel like.” The agent contributes its own drawing while respecting the shared boundary. The desired interaction is collaborative drawing, not handwriting recognition as a prerequisite.

This needs a shared writable canvas or a verified Notability control/input path. Neither is established by the existing mouse-to-bell demo. Keep it as a candidate scene; don't claim two-way drawing or trigger a sample as though the agent observed the line. A later acceptance should show the actual divider, the agent's new strokes entirely on its assigned side, preservation of Jay's strokes, and stopping when asked.

## Close — about 10 seconds

“The agent chose how to use the available tools, while the computer handled the timing and device connections. The next step is making those connections repeatable across rooms.”

If demonstrating permission ending, use the existing visible Leave/host reset path as a separate accepted closing beat. Do not imply that arbitrary native applications are forcibly stopped by every guest leave: managed programs and broad native app effects have different cleanup guarantees.

## Before the take

1. Open the current room join page on the iPad and use **Chat here**. Keep one phone's light page open, awake, enrolled and online. The iPad sends ordinary chat; the Mac runs the agent/tools.
2. Keep the TV in extended-display mode, with a **normal Chrome window**. No fullscreen. Preserve the system audio output and volume **20**. Don't mix drawing bells with the song unless explicitly desired.
3. Confirm the current managed song and phone are actually available. Check the photo controller and matching TV preview; never invent their session URL. The drawing server currently uses `http://127.0.0.1:57633/`.
4. The room agent receives a capability-guide reference to `notes/live-demo-agent.md` on each new turn after the backend loads the change. It must interpret actual requests, execute real controls, and verify results. It is not instructed to auto-run this script or prewrite answers.
5. Do one bounded rehearsal of the selected sequence, with a physical confirmation of TV and sound. If a beat fails, remove that beat for the take; don't debug or secretly cue it off-camera.

## Current readiness

- Earlier music/light/orb trials: bounded physical passes already recorded; the complete current iPad script is not freshly accepted.
- Drawing engine, shuffle and browser-to-browser photo channel: prior software checks passed; revised bell sound accepted by Jay.
- Current album: Jay confirmed it is visible on the TV after manually moving the normal Chrome window; automatic window movement did not work in this connection.
- New room-agent capability guide: deployed in981bb90. One genuine guest-chat request to stop drawing bells passed: the agent read the guide, clicked the actual Stop sound control, and fresh independent page state showed “Sound stopped, including echoes” with the same Coastal dusk photo and stroke0. Sound was already off, so this establishes control wiring/preservation, not audible interruption of active bells or full-script reliability. Browser-session contention forced a native-control fallback; do not promise instantaneous responses.
- iPad: chat only by Jay's choice. Actual drawing remains Mac mouse/trackpad; Notability is not connected.
- Celsius: separate owner, separate acceptance. No implicit launch or camera reservation here.
