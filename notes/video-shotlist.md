# Video — two halves, one film

Hard facts (verified on the Hacker Guide 18:45): the video is a recording of the 3-minute presentation, uploaded to Devpost by **10:00 AM Sunday**; no video → not judged. Target **2:40**, hard cap 3:00.

Structure: **Half 1 (0:00–1:20) is live iPhone footage of the real table demo.** **Half 2 (1:20–2:40) is built**, the way the Antibody demo was: Playwright captures our real pages, Remotion lays every shot (including the live footage) into one composition with the same captions, wallpaper, cards and easing as the deck. One film, one look, no "and now a screen recording" seam.

Style reference: `/Users/owentsao/Coreweave Hacks/docs/DEMO_VIDEO.md` and `video/`. What we take: framed window on a blurred wallpaper with a deep shadow; bold + grey caption pairs above the window; at most one slow push-in per shot; 300 ms dissolves; statement and one-number cards between UI shots; nothing scrolls on camera; music only under the built half, ducked under speech. What we change: black → plum `#1a1523`; the wallpaper is the deck's dithered wireframe room (`deck-stage.js`), blurred and dimmed; Inter Tight 800 for cards; pink `#f0a8e0` is the only colour and means "live".

## Half 1 — live (0:00–1:20)

Shot on an iPhone, landscape, propped, 1080p60. One continuous take; we cut it into beats in the edit. Setup checklist is unchanged from the previous version of this file (bottom of doc).

| Time | On camera | Caption (bold / grey) | Audio |
|---|---|---|---|
| 0:00 | Title card (built): mark + "Tenant" on the wireframe room. 4 s. | Tenant / Borrow the room. Leave, and it forgets you. | music in |
| 0:04 | Wide: Mac on `display.html` (nobody here), two phones, the printed card. | Picture a hospital bed at 2 AM. / The light switch is on the wall. The nurse is three rooms away. | Owen VO |
| 0:14 | Guest's hands: scans the card → join page → **Chat here**. Cut-in: the display's pink guest block appears, countdown starts. | No app. No account. / A ten-minute lease on this room's devices. | VO |
| 0:26 | Guest types "turn on a light". **Torch comes on.** Cut-in 2 s: the chat reply. | "Light's on. Owen's phone." / The room picked the device that could do it. | room audio |
| 0:38 | "play something calm" → music from the speaker. Display ledger logs the sentence. | Everything is a sentence. / Nothing is a terminal. | room audio |
| 0:48 | "say the nurse is on her way" → the Mac speaks it. | The room can talk to someone else. / Not just to you. | Mac voice |
| 0:58 | "leave" → display: guest gone, lease ended. Then "turn off the light" → denial. **Torch stays on.** | Same phone. Same request. Refused. / The light was never theirs to turn off. | VO |
| 1:12 | Host presses reset: torch off, music stops, code rotates on the display. | One key. / The next patient gets a clean room. | VO |

Rule: nothing is cued off-camera. If the Brain needs help, stop the take.

## Half 2 — built (1:20–2:40)

Captures are the real pages against `?mock=1` fixtures (the same ones the judge-facing pages were built on) unless marked LIVE. Every number is one we can defend; the *Proof* column says where.

| # | Time | Type | On screen | Caption (bold / grey) | Proof |
|---|---|---|---|---|---|
| 1 | 1:20 | S | Statement card on the wireframe room. | How it works. / Three ideas, one server. | — |
| 2 | 1:24 | UI | `display.html?mock=1` in the framed window, reset state → guest appears → countdown ticking (`state.json` ticker). One push-in on the pink guest block. | A room is a registry. / Every device announces what it can do when it connects. Adding one is plugging it in. | `web/display.html`, `ARCHITECTURE.md` §3 |
| 3 | 1:36 | UI | `guest.html?mock=1` in a 390-px phone frame: the one-line permission ("Owen's phone, the Mac and the speaker · 9:00 left"), then the chat. | Access is a lease. / Ten minutes. A fixed set of devices. Checked at the moment of action, not when you joined. | `web/guest.html`, lease frame §5.2 |
| 4 | 1:48 | M | One-number card, mono. | 14 ms / from "leave" to the next request being refused. No command reached a device. | Jay 17:31, `tests/evidence/…final-acceptance.json` |
| 5 | 1:53 | UI | `display.html` ledger: the last rows, ending on the inverted "Someone who had left asked to turn off the light. The room said no." row. One push-in on that row. | The room said no. / The log is sentences a person reads. No IDs, no code, ever. | `web/display.html` ledger |
| 6 | — | — | **Cut 23:40:** host setup is not the judge's experience. The printed card is on camera in Half 1. Times below shift 7 s earlier. | — | — |
| 7 | 2:10 | UI | `join.html?mock=1` on the phone frame: **Chat here** / **Text the room** → Messages with "join 7F3A". **Only if a real iMessage round-trip has passed by shoot time; otherwise cut this shot.** | Or just text it. / Photon 2.0 gives the room a real phone number. Same room, same lease. | `brain/channels/photon.py`; Jay's acceptance |
| 8 | 2:17 | M | Three mono figures stacked: `0 accounts` · `10:00 lease` · `1 key to reset`. | Nothing to install. Nothing to remember. / The host owns the room. The guest borrows it. | `PLAN.md` claim ¶ |
| 9 | 2:23 | S | Wireframe room, slow turn; small pink dots light on the devices. | Two phones and a laptop today. / A hotel TV, a smart bulb, a hospital bed join the same way. | — |
| 10 | 2:31 | L | End card: `notes/brand/tenant-wide.png` composition, then the GitHub URL in mono. **No QR** (the code rotates). | Tenant / The room has a brain. Leave, and it forgets you. | — |

Audio for half 2: Owen reads the bold+grey lines as voiceover (it's a "recorded presentation", judges expect a voice); captions stay on screen for the ballroom. Music at −6 dB under the whole built half, ducked −10 dB under VO, out over the last 4 s.

## Production

### Reuse, don't rebuild
Copy `/Users/owentsao/Coreweave Hacks/video/` → `dubhacks2/video/` and re-token: `src/components.tsx` wallpaper → the deck room render; colours → `tenant.css` tokens; font → Inter Tight (`web/fonts/InterTight-latin.woff2`, already in repo); captions bold/grey → `--fg` / `--muted`. `src/shots.ts` becomes the table above as data. `capture/*.mjs` → one script per UI shot against `python -m http.server 8899` serving `web/` (the same static server the pages are built on; `?mock=1` means no Brain needed).

**Dependency ask (needs Owen's OK before `npm install`):** `remotion`, `@remotion/cli`, `react`, `react-dom`, `playwright` — the exact set `Coreweave Hacks/video/package.json` already uses. Nothing new to the machine; new to this repo. `ffmpeg` is on PATH (`/opt/homebrew/bin/ffmpeg`), Chrome is installed, Node 24.

### Capture rules (learned the hard way on Antibody)
- Headed Chromium, window uncovered, nobody touches it during a take.
- `Page.startScreencast` at 2× → 60 fps CRF-12 clip; the master is the only lossy step.
- No scrolling on camera: open pages pre-scrolled; let the composition zoom.
- Mock ticker: `display.html?mock=1` idles with no guests; shot 2 needs the fixture to add a guest ~2 s in. Check `web/mock/state.json` supports this or add a `&demo=1` step sequence to the fixture (Owen's file).
- One zoom per shot, centre fixed; the Antibody home-card drift came from a moving centre.

### The live half inside Remotion
Half 1's iPhone clip is imported as one more shot: trimmed per beat, placed in the same framed window on the plum wallpaper (the window is 16:9, the footage fills it), captions above it in the same style. iOS screen recording of the guest phone is a second clip for the 2-s cut-ins in beats 0:14 and 0:26. This is what makes the two halves one film.

### Order of work (Sunday morning if tonight is spent on the Brain)
1. **Tonight after 9:30 run-through: shoot Half 1 (three takes).** This is the only part that needs the hardware. Upload the raw best take to Drive immediately as the no-edit fallback.
2. Copy and re-token the Remotion workspace (≈45 min).
3. Capture shots 2, 3, 5, 6 against mock (≈30 min). Shot 7 only if Photon passed.
4. Record Owen's VO on the iPhone voice memo app in a quiet corner (≈10 min).
5. Compose, render, watch once end to end, upload unlisted to YouTube or Drive, paste into Devpost. Budget 7:00–8:45 AM, master by 9:00, Devpost final by 9:30.

Fallback if step 2 slips past 8:00 AM: Half 1 raw take + title/end cards in iMovie. Submit that. A rough video beats no video.

## Setup checklist for the live take (unchanged)

- Mac at 1440×900, Chrome full-screen on `display.html`, clock visible. Screen Studio recording the Chrome window. Default output = Mac speaker at a volume the camera mic picks up — test "say hello" first.
- Guest phone: iOS Screen Recording on (mic off), Do Not Disturb, brightness max.
- Device phones: enrolled, online on the display, torches off, plugged in, Do Not Disturb.
- Camera phone: landscape, propped, Mac display + both device phones + guest's hands in frame. Room lit so the torch still reads on camera (2-s test).
- Brain `/health` 200, room reset, zero guests, music stopped.
- Three takes back to back; reset between; pick the best; prefer one unbroken take.

## Do not
- Cue anything by hand off-camera.
- Show the Codex window, terminal, logs, dev QR page.
- Claim iMessage unless the beat is in the take.
- Speed up footage. Judges read latency as honesty.
- Put a QR in the video.
