# Prepared local demo capabilities for the genuine Tenant room agent

Jay's decision, 2026-10-18: the iPad sends **chat instructions only** through Tenant's existing guest chat. Interpret the actual request using your normal tools. These are available artifacts and operating notes, not a keyword router, canned answer list, or authority to execute the whole demo.

## Drawing bells and sunset photo album

The lab is the sibling `../tenant-capability-lab/` of this repository. Its `TRANSFER-TO-MAIN.md` and `DRAWING-HANDOFF.md` contain the full acceptance record. The main Tenant owner now owns this lab.

- Current local control page: **http://127.0.0.1:57633/**. Check it before using it. A saved entry point is `../tenant-capability-lab/state/drawing-preview.json`.
- Chrome title: **Tenant · Drawing lab**. Reuse the existing page; avoid making a second independent drawing session.
- The **Open TV preview** button opens **Tenant · Sunset album** at `tv.html?session=...`. Use that actual generated URL. The controller and TV must use the same Chrome profile and origin for their live photo channel. Reuse the matching existing album tab when possible.
- The TV is the existing **SAMSUNG extended display, to the right of the Mac**. Keep a normal window. **Do not use Full screen**, change screen settings, rearrange unrelated windows, or claim physical TV rendering from an HTTP response alone.
- The real page exposes **Enable quiet sound**, **Try sample drawing**, **Open TV preview**, **Stop sound**, and **Start over**. Inspect current UI before clicking. Use the installed computer/browser tools for UI work; do not invent a shell UI bridge or browser-control API.
- **Enable quiet sound** permits subsequent drawing to sound. It does not itself play a demonstration. Enable only when asked. **Stop sound** clears all bell voices/echoes while leaving the current photo/drawing. **Start over** additionally cancels replay, clears the drawing, changes the input session, returns the initial photo, and disables sound; do not reset merely to stop sound.
- The album contains six real, cached Unsplash sunset photos. A new stroke chooses another photo, once per shuffle cycle, with a 900 ms crossfade. It is a photo album, not a prerecorded video or the current song's album cover. It is not currently an autonomous slideshow.
- Preserve the approved sound: C3–C5 soft pentatonic bells, 55 ms attack, eight-second release, independent overlapping tails, subdued upper partials, 0.55 s echo and 0.5 feedback. Preserve the page's current application gain and the Mac's output and volume (last requested system volume: 20). Do not retune or switch speakers unless asked.
- Sound uses the Mac's current default output. A page button cannot currently select a different physical speaker in this browser. Any requested route change needs real system support and verification; never claim it happened from prose alone.

## Input and evidence limits

The working drawing input is **mouse/trackpad** in the Mac control page. The iPad is only a chat terminal. **Notability / Apple Pencil events are not connected.** No camera, microphone, screen observation, or proactive drawing detector runs in this lab. If asked to connect Notability, state the missing connection and ask about a fallback; do not silently use a sample or describe mouse input as iPad input.

**Try sample drawing** is explicitly synthetic three-stroke replay. Use it only if a preview/replay is requested; identify it as a sample. Never use it as proof of live sensing. A replay is not a person drawing.

When asked to show the album, use the existing page and its TV preview. When asked to enable drawing sound, use the existing sound button. When asked to stop just bells, use Stop sound, leaving the album. Wait for the next request; don't run the remaining script automatically. If the local server is down, report that fact; don't silently replace it with a new app, different input, or unrelated music.

Verify browser effects using fresh visible state, matching session/photo/stroke count, and sound enabled/stopped status. Browser state proves rendering in that browser; it does not establish physical TV visibility or audible sound. The host confirms those physical observations. Do not claim an iPad end-to-end test until one actually happens.

## Other demo pieces

Managed CYANIDE playback, late phone-light attachment, and live orb already have their existing helper/program interfaces and earlier bounded physical evidence. Use the current per-turn helper and inventory for those, preserving an existing program when adding a light or orb. Do not restart music merely to add another output. Do not change volume/output. Only requested speech is spoken; text remains the default.

The Celsius scene is being prepared separately in `../tenant-celsius-lab/`. It has no accepted live interface in this guide. Do not claim active camera monitoring or execute it until its owner supplies a verified handoff. It must not interrupt the album or claim a guessed label as an observed fact.
