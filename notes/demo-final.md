# Final demo — one script for the table and the video

Decided Owen 21:55, from Jay's log through 21:45 (`origin/codex/tenant-core-integration`), `notes/demo-ideas.md`, `notes/customers-and-moat.md`, `notes/tester.md`. Beats are **in** only if a human has confirmed the physical result tonight. Title track: Community Kitchen. Judge is the guest; we touch the keyboard once, for reset.

## Spine (2:15, both the live demo and the video's first half)

| # | Who | Says / does | Physical result | Evidence |
|---|---|---|---|---|
| 0 | Owen | "Picture a hospital bed at 2 AM. The light switch is on the wall, the nurse is three rooms away. Here's the card on the bedside table. Scan it." | — | — |
| 1 | Judge | Scans the printed card → **Chat here** | Display: guest appears, lease ring starts | 20:08 display acceptance |
| 2 | Judge | "turn on a light" | Owen's phone torch on; one-sentence reply | 17:25 → 20:08, repeated |
| 3 | Judge | "play Cyanide" | The actual song from the speaker | 21:15 Batch 4 |
| 4 | Judge | "say the nurse is on her way" | Mac speaks the sentence | 17:24, 19:17 |
| 5 | Judge | "leave" → then "turn off the light" | Denied. Torch stays on. | 17:23 / 17:25, 19:37 |
| 6 | Owen | Presses reset. "One key. The next patient gets a clean room." | Torch off, music stops, code rotates | 17:31, 19:37, 19:46 |
| 7 | Owen | "Two phones and a laptop today. A hotel TV or a hospital bed joins the same way. Rooms you don't own, without apps or accounts." | — | — |

## Bonus beats — each gated on rehearsal #3 (Sun 8:30)

1. **Phone follows the song.** Between 3 and 4: "make my phone flash with the song." One human-perceived alignment (21:15); generated-beat pulses and stop PASS repeatedly (19:29, 19:46, 20:08). Jay 20:49: not a main-demo dependency.
2. **Lend the room your flashlight.** A second judge scans the one-time device link (setup step 2, `8dc399a`); their phone appears on the display as a device; the first judge says "turn on all the lights." Zero new code; this is Jay's queued Q-PHONE-SHARE. Gate: one pass with a *stranger's* iPhone (iOS version, HTTPS, two permission prompts).
3. **The second judge.** After reset, a new judge scans and asks "what did the last person ask for?" The room doesn't know. Fresh context per guest verified (18:11). Costs nothing; best proof of "it forgets you." Use as the closer when there are two judges at the table.
4. **One unscripted command.** Let a judge ask something we didn't script. Fallback line if slow or wrong: "and that's why the host's screen shows exactly what it did."
5. **Let the room answer.** In Q&A, when a judge asks what the room can do or who's in it: "ask it." Judge dictates into the chat box with the iOS keyboard mic (what Jay used all night, 18:43); the Mac speaks the reply because the guest opted in earlier with "talk to me out loud" (verified 20:08). Do the opt-in during beat 4 so it costs no extra turn later. Steer toward questions about the room (devices, who's here, what happened), not our architecture. Speech turns run ~7 s; one hung 54 s tonight. No code.

**Rule for all four:** if it doesn't pass at rehearsal #3, it leaves the script and becomes a Q&A answer. Never a beat the demo can fail on.

## Q&A answers (not scripted)

- "What else can it do?" → "Leave a note for the day shift: the light's been flickering." The agent writes and opens a note on the Mac. (Batch 4 PASS; Batch 3 hung 54 s. Answer, not promise.)
- "What if a device dies?" → Ask for the unplugged phone; the room offers the other one and waits for the choice. (17:23/17:25.)
- "Can I text it instead?" → Only if Jay confirms a Photon reply *arrived on a handset*. Until then: "Yes, it has a number through Photon 2.0; we're showing chat today because the ballroom Wi‑Fi is kinder to it."
- "Isn't this Home Assistant / Google Home MCP?" → Those give the *owner's* agent permanent authority. Tenant gives a *stranger* temporary, verified, revocable authority, and the host's screen shows every action in a sentence.

## Cut from the script, with the reason

| Idea | Reason |
|---|---|
| Group-photo finale with the judges | Correction 23:55: Owen's UI is small (phone capture ~40 lines on Jay's device page + a Mac viewer page ~30 lines, see `notes/photo-handoff.md`). The blocker is that the photo backend is unmerged/undeployed and the phone page is Jay's file. **Jay's call:** if he can merge, deploy and pass one real capture before 8:30 AM without touching anything else, Owen builds the viewer in 30 min and it becomes bonus beat 6. Until a real photo lands on the Mac it is a roadmap line, no slide. |
| Host setup / onboarding flow | Our chore, not the judge's experience. Out of the live demo and out of the video's built half (shot 6 cut). The printed card appears in Half 1; the display stays because it shows the lease, which is the thesis. |
| Phone video + voice → Blender/projection changes as you describe a building (partner's idea) | Four unbuilt subsystems (video streaming, perception, 3D renderer, generative pipeline), each deliberately cut in `PLAN.md`; also a different product. One sentence in the "where multimodal agents take this" line. The kernel worth keeping, "the guest contributes a device," is bonus beat 2. |
| Broad "talk to the computer" beat | One hang tonight; invites the security question in the wrong moment. Q&A only. |
| Photon "Text the room" for judges | Replies accepted by Photon, none confirmed on a phone. Join page keeps both buttons; we point judges at Chat here. |
| Expiry claim | New agent path's 600 s run was interrupted at 522 s (NOT PASS). Say "ten-minute lease"; demonstrate "leave" and "reset". |
| Album cover / band | Rejected by Jay 20:49. |
| Projector, perception, rules, guest-supplied agents | Not built. |

## Before any judge sees a screen (Owen's files)

1. `join.html`: remove the "photo" promise (Jay 20:08 finding). Hide "Text the room" unless handset delivery is confirmed.
2. `display.html`: headline/rail should read newest rows first so a later stop/Leave isn't hidden (Jay 20:08 finding).
3. Deck slide 2 opener should match the hospital framing above.

## Video mapping

Half 1 (live, iPhone) = beats 0–7, three takes tonight after the run-through. If the bonus beat lands cleanly in a take, keep it; if not, cut around it.
Half 2 (built) = `notes/video-shotlist.md` shots 1–10; shot 7 (Photon) only on handset confirmation.
Music note: CYANIDE in the video audio will draw a YouTube Content ID claim. Upload to Drive (unlisted) rather than YouTube, or duck the song under VO and keep it short.

## Reply owed to Jay (21:15 customers-and-moat request)

Owen's strongest customer problem: a short-term-rental operator with twenty dispersed units whose guests can't work the smart TV at 11 PM and call the only on-call person. Strongest competitive objection: "Home Assistant and Google Home already expose devices to AI agents over MCP." Our answer: they grant the owner's agent permanent authority; Tenant grants a guest temporary, verified, revocable authority with a host-visible record. Recorded in `notes/owen.md`.
