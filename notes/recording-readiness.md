# Recording readiness — October 18

## Current staging

Room **F28D** is staged after the single final reset. There are zero guests and two online devices: Phone light and Room speaker. Reset cleanup, native context cleanup and room-program cleanup all returned confirmed. Both active devices acknowledged the reset defaults. The honest device count is2, not3: use the Mac guest chat, one phone as the light and another to film.

- Public base: https://writers-detector-strengthen-catalyst.trycloudflare.com
- Guest entry: https://writers-detector-strengthen-catalyst.trycloudflare.com/j/F28D
- Real current QR: /qr.svg on that base. Local printable SVG: outputs/tenant-room-F28D-qr.svg. Physical paper printing has not been verified.
- /health, /setup, /slides, /display, /qr.svg and the join route are served through the same Brain. Detached Brain/audio/tunnel launchers remain up. No refresh or restart occurred during final staging.
- Chrome has the correct host token privately installed; DevTools is closed. HOLD R for one second resets; X revokes. D is not bound. Do not expose the host token, private device QR or diagnostics in the video.
- **Do not use fullscreen on the TV.** Jay diagnosed the fullscreen transition and then physically confirmed Tenant visible in a normal window on the extended monitor to the RIGHT. Freeze that arrangement. No mirroring, resolution or Spaces change is needed.
- **MacBook Pro Speakers,20%, unmuted.** Tester verified the final setting following Jay's explicit instruction. Preserve it. The TV is picture only. Do not restore HDMI, headphones or the earlier3%/10% settings.
- Managed CYANIDE asset checksum and the existing mpv path are ready; use that path, not browser/Spotify substitution. No new music rehearsal was run for this staging.
- QuickTime is installed; Screen Studio was not found. The screen-recording portion needs QuickTime or an already-available recorder. No recording has started.

## Evidence and limits

Jay asked for one focused infrastructure preflight, not five repetitions. Owen's main1facd03 pages, script and shot list were integrated as-authored. Root added backend /slides and corrected actual nested dots.js/font routes found by the UI preflight. Source dbeb227 passed17 focused route/integration checks. Two quiet Brain-only refreshes occurred before recording; audio and tunnel were preserved. All web design remains Owen-owned.

The first actual standard-Chrome guest hello passed the software path but FAILED physically: no picture or sound reached the TV. Its receipt explicitly said audible_verified=false. Preserve this failure: tests/evidence/2026-10-18-recording-speech-preflight.json.

After Jay fixed the fullscreen issue and audio moved from HDMI to Mac speakers, one justified corrected guest hello completed through the actual UI, native room thread and confirmed speaker receipt. Ordinary Leave and independently zero guests passed. Jay said it was too quiet at3% and thought it worked; that is tentative audibility, not an unconditional physical PASS. Final20% is verified but was not replayed. Evidence: tests/evidence/2026-10-18-recording-low-audio-correction.json.

The light phone rejoined, and the final reset produced F28D with both devices online and all cleanup states confirmed. Evidence: tests/evidence/2026-10-18-recording-final-staging.json. No full scripted rehearsal or repeated song/light trial was added.

**Photo finale remains unverified.** The current phone advertises light only, with no consented camera.capture capability. Backend and Owen's viewer exist, but a new phone image has not landed on this TV. Use the roadmap sentence; the earlier native FFmpeg still capture is a different path and does not establish this finale. No photo debugging during recording.

The current guest UI disables its composer after Leave. Show that actual ended/disabled state; do not claim a fresh backend refusal if no post-Leave request was sent.

## Recording freeze

Use Jay's latest two-part handoff: real table take first, then one continuous slides → setup → display recording, preserving the real demo ledger without another reset between halves. This supersedes the older Remotion plan in video-shotlist.md. Film-crew/OBS work remains paused and stopped.

No tests, hidden commands, extra guests, resets, deployments, service restarts, window/fullscreen/Spaces changes or output/volume changes while recording. If the Brain needs intervention, stop and redo the take. Keep the light page visible and the phone awake; the user handles power, DND, framing and physical recording.

Owen handoff: https://github.com/owen-tsao/tenant/pull/1#issuecomment-6248661144
