# Final demo — one script for the table and the video

Decided Owen 21:55, revised **02:56 Sun** from Jay's log through 23:06 (`origin/codex/tenant-core-integration`). Beats are **in** only if a human has confirmed the physical result. Title track: Community Kitchen. Judge is the guest; we touch the keyboard twice (`D`, `R`). Laptop mirrored to the TV; projector dropped. Video plan: `notes/video-shotlist.md`.

## Live demo at the table (3:20 + Q&A)

| Time | On the TV | What happens | Owen says | Evidence |
|---|---|---|---|---|
| 0:00 | `slides.html` 1 | | "Tenant lets a guest use a room's devices by talking to it. No app, no account, and it forgets you when you leave." | — |
| 0:10 | slide 2 | | "Picture a hospital bed at 2 AM. The switch is on the wall, the nurse is three rooms away, and the last thing you want is another app and another password." | — |
| 0:22 | slide 3 | | "You scan a card, you ask like a person, the room does it." | — |
| 0:32 | slide 4 | | "Access is a lease, not an account. Leave and it's gone." | — |
| 0:45 | slide 5 | Hand the judge the printed card | "Scan this." | — |
| 0:55 | switch to the `display.html` tab (⌘-Shift-]; `D` is not bound) | Judge taps **Chat here**; guest appears, ring starts | "That's you, on the TV. Ten minutes." | 20:08, 22:15 |
| 1:05 | display | **"turn on a light"** → phone torch on | "It picked the device that could do it." | repeated all night |
| 1:20 | display | **"play Cyanide"** → speaker | | Batch 4, 5, 6 |
| 1:35 | display | **"say out loud: I need some help in here"** → TV speaker says it | "The room can speak for someone who can't." | 17:24, 19:17, 22:15 |
| 1:50 | display | **"leave"** → guest gone. **"turn off the light"** → refused, torch stays on | "Same phone, same request. The light was never theirs to turn off." | 17:25, 19:37, 22:15 |
| 2:10 | display | **`R`**: torch off, music stops, code rotates | "One key. The next patient gets a clean room." | 17:31, 19:46, 22:15 |
| 2:25 | display | **Finale, only if it passed at 8:30:** "take a photo of us" → photo on the TV | | backend deployed 21:04; Owen viewer pending |
| 2:45 | display | | "Two phones and a laptop today. A hotel TV or a hospital bed joins the same way. Rooms you don't own, without apps or accounts." | — |
| 3:00 | | Q&A | | |

Corrections since 21:55: the 10-minute natural expiry **passed** (22:15), so "ten-minute lease" is a defensible claim; the "nurse is on her way" line is replaced (it made no sense from the guest's seat); the photo backend is deployed, only the web viewer is missing.

## Q&A extras — each gated on the 8:30 rehearsal

1. **Phone follows the song.** Between 3 and 4: "make my phone flash with the song." One human-perceived alignment (21:15); generated-beat pulses and stop PASS repeatedly (19:29, 19:46, 20:08). Jay 20:49: not a main-demo dependency.
2. **Lend the room your flashlight.** A second judge scans the one-time device link (setup step 2, `8dc399a`); their phone appears on the display as a device; the first judge says "turn on all the lights." Zero new code; this is Jay's queued Q-PHONE-SHARE. Gate: one pass with a *stranger's* iPhone (iOS version, HTTPS, two permission prompts).
3. **The second judge.** After reset, a new judge scans and asks "what did the last person ask for?" The room doesn't know. Fresh context per guest verified (18:11). Costs nothing; best proof of "it forgets you." Use as the closer when there are two judges at the table.
4. **One unscripted command.** Let a judge ask something we didn't script. Fallback line if slow or wrong: "and that's why the host's screen shows exactly what it did."
5. **Let the room answer.** In Q&A, when a judge asks what the room can do or who's in it: "ask it." Judge dictates into the chat box with the iOS keyboard mic (what Jay used all night, 18:43); the Mac speaks the reply because the guest opted in earlier with "talk to me out loud" (verified 20:08). Do the opt-in during beat 4 so it costs no extra turn later. Steer toward questions about the room (devices, who's here, what happened), not our architecture. Speech turns run ~7 s; one hung 54 s tonight. No code.

6. **Goodnight.** "turn everything off, I'm going to sleep" stops torch and music in one sentence (combined stop confirmed 22:32). Second judge's closer only; in the spine it would steal the reset's payoff.
7. **Unlock the door.** Ask for a device the room doesn't have; the agent answers honestly from the live inventory (capabilities answer verified 18:11). Shows the registry can't invent authority.

**Rule for all of these:** if it doesn't pass at rehearsal #3, it leaves the script and becomes a Q&A answer. Never a beat the demo can fail on.

## Q&A answers (not scripted)

- "What else can it do?" → "Leave a note for the day shift: the light's been flickering." The agent writes and opens a note on the Mac. (Batch 4 PASS; Batch 3 hung 54 s. Answer, not promise.)
- "What if a device dies?" → Ask for the unplugged phone; the room offers the other one and waits for the choice. (17:23/17:25.)
- "Can I text it instead?" → Only if Jay confirms a Photon reply *arrived on a handset*. Until then: "Yes, it has a number through Photon 2.0; we're showing chat today because the ballroom Wi‑Fi is kinder to it."
- "Isn't this Home Assistant / Google Home MCP?" → Those give the *owner's* agent permanent authority. Tenant gives a *stranger* temporary, verified, revocable authority, and the host's screen shows every action in a sentence.

## Cut from the script, with the reason

| Idea | Reason |
|---|---|
| Group-photo finale with the judges | **Not cut: gated finale** (see 2:25 above). Backend deployed 21:04 (`e4b8426`); the frontend chat is building the display viewer per `notes/photo-handoff.md`. In only if one real photo lands on the TV at 8:30. |
| Host setup / onboarding flow | Our chore, not the judge's experience. Out of the live demo and out of the video's built half (shot 6 cut). The printed card appears in Half 1; the display stays because it shows the lease, which is the thesis. |
| Phone video + voice → Blender/projection changes as you describe a building (partner's idea) | Four unbuilt subsystems (video streaming, perception, 3D renderer, generative pipeline), each deliberately cut in `PLAN.md`; also a different product. One sentence in the "where multimodal agents take this" line. The kernel worth keeping, "the guest contributes a device," is bonus beat 2. |
| Broad "talk to the computer" beat | One hang tonight; invites the security question in the wrong moment. Q&A only. |
| Photon "Text the room" for judges | Replies accepted by Photon, none confirmed on a phone. Join page keeps both buttons; we point judges at Chat here. |
| Expiry claim | **Reversed 22:15:** natural 600 s expiry passed with phone/audio confirmed and no command after. Say "ten-minute lease" freely; still demonstrate "leave" and "reset" rather than waiting ten minutes. |
| Album cover / band | Rejected by Jay 20:49. |
| Projector, perception, rules, guest-supplied agents | Not built. |

## Before any judge sees a screen (Owen's files)

1. `join.html`: remove the "photo" promise (Jay 20:08 finding). Hide "Text the room" unless handset delivery is confirmed.
2. `display.html`: headline/rail should read newest rows first so a later stop/Leave isn't hidden (Jay 20:08 finding).
3. Deck slide 2 opener should match the hospital framing above.

## Video mapping

See `notes/video-shotlist.md` (02:35): Clip 1 = iPhone take of 0:55–2:25 above; Clip 2 = one continuous Screen Studio recording of slides → setup → display → end card. No Remotion.

## Reply owed to Jay (21:15 customers-and-moat request)

Owen's strongest customer problem: a short-term-rental operator with twenty dispersed units whose guests can't work the smart TV at 11 PM and call the only on-call person. Strongest competitive objection: "Home Assistant and Google Home already expose devices to AI agents over MCP." Our answer: they grant the owner's agent permanent authority; Tenant grants a guest temporary, verified, revocable authority with a host-visible record. Recorded in `notes/owen.md`.
