# Video — one iPhone take, one Screen Studio take, joined

Decided Owen 02:35 Sun. Supersedes the two-half / Remotion plan. Hard facts (Hacker Guide): the video is a recording of the 3-minute presentation, uploaded to Devpost by **10:00 AM Sunday**; no video → not judged. Target **2:45**, hard cap 3:00.

Structure: **Clip 1 (0:00–1:20) is iPhone camera footage of the real table demo.** **Clip 2 (1:20–2:45) is one continuous Screen Studio recording** of slides → setup → display → end card, narrated live. Joined in QuickTime Player (Add Clip to End). No Remotion, no Playwright, no new dependencies.

## Clip 1 — iPhone, 0:00–1:20

Landscape, propped, 1080p60, TV + both device phones + the judge's hands in frame. One take, three attempts, pick the best. Nothing is cued off-camera; if the Brain needs help, stop the take.

| Time | On camera |
|---|---|
| 0:00 | Wide shot. Owen: "Picture a hospital bed at 2 AM. The switch is on the wall, the nurse is three rooms away. Here's the card on the bedside table." |
| 0:10 | Guest scans the printed card → **Chat here** → the TV shows the guest, lease ring starts |
| 0:20 | "turn on a light" → Owen's phone torch on |
| 0:32 | "play Cyanide" → the speaker |
| 0:44 | "say out loud: I need some help in here" → the TV speaker says it |
| 0:56 | "leave" → then "turn off the light" → refused, torch stays on. Owen: "Same phone, same request. The light was never theirs to turn off." |
| 1:08 | Owen presses **R**: torch off, music stops, code rotates. "One key. The next patient gets a clean room." |
| 1:15 | Photo finale **only if** one real photo landed on the TV at the 8:30 rehearsal |

Upload the raw best take to Drive immediately as the no-edit fallback.

## Clip 2 — Screen Studio, 1:20–2:45, one recording

Record **immediately after the iPhone take, before anyone resets the room again**, so the display at the end shows the real ledger from the demo. Laptop 1440×900, Chrome full screen, tabs pre-opened in order; move between them with ⌘-Shift-]. Mic on; Owen narrates as he goes.

| Time | Tab | Do | Say |
|---|---|---|---|
| 1:20 | `slides.html` slide 1 | | "That's Tenant. A guest borrows a room's devices by talking to it. No app, no account." |
| 1:28 | slide 2 | → | "Rooms you don't own still make you download something." |
| 1:36 | slide 3 | → | "You scan a card, you ask like a person, the room does it." |
| 1:44 | slide 4 | → (countdown, then the invert) | "Access is a lease. Ten minutes, a fixed set of devices, checked at the moment you ask. Leave and it's gone." |
| 1:54 | slide 5 | hold 3 s | "Scan this and you're in." |
| 1:58 | `setup.html` step 1 | type the room name | "Here's the host's side. Name the room." |
| 2:06 | step 2 | devices appear as they connect | "Plug a device in; it announces what it can do. Two phones and the Mac." |
| 2:16 | step 3 | the printable card | "Print the card. That's the whole install." |
| 2:24 | `display.html` | hover the guest block, then the ledger; **never scroll** | "And the host watches it all in sentences. There's the light, the song, the request the room refused, the reset." |
| 2:38 | `brand.html?v=wide` | hold 6 s | "Tenant. Leave, and it forgets you." |
| 2:45 | | stop | |

Real vs mock: all three pages against the **real Brain** (Jay's tunnel URL) if it is up; the real ledger is the payoff. Fallback if the Brain is down: `?mock=1` on all three and drop the "there's the light, the song" line.

Screen Studio: background `#1a1523`, window padding on, auto-zoom on clicks, cursor smoothing, 1080p export, mic audio in. Music: none, or a quiet bed under Clip 2 only if time allows.

## Assembly (10 min)

1. Open Clip 1 in QuickTime Player → Edit → **Add Clip to End** → the Screen Studio export → File → Export As → 1080p.
2. Watch once end to end. Check: audio levels match between clips; total ≤ 3:00.
3. Upload to **Drive, unlisted** (Cyanide in Clip 1 will trip YouTube Content ID). Paste the link into Devpost. Devpost final by 9:30.

Fallback if Clip 2 slips past 9:00: submit Clip 1 alone with a 4 s title card. A rough video beats no video.

## Order of work Sunday morning

1. 8:30 rehearsal (gates the photo finale and every extra).
2. Shoot Clip 1, three attempts. Upload raw best take.
3. Without resetting the room, record Clip 2 in one pass. Re-record whole if a tab misbehaves; do not splice.
4. Assemble, watch, upload, paste. Budget 9:00–9:30.

## Setup checklist

- TV mirrored from the laptop at 1440×900; Chrome full screen on `display.html`; default audio output = TV or room speaker at a volume the camera mic picks up. Test "say hello" first.
- Guest phone: Do Not Disturb, brightness max.
- Device phones: enrolled, online on the display, torches off, plugged in, Do Not Disturb.
- Camera phone: landscape, propped; the torch must read on camera (2 s test with room lights as they'll be).
- Brain `/health` 200, room reset, zero guests, music stopped.
- For Clip 2: five Chrome tabs pre-opened in order (slides, setup, display, brand wide), Screen Studio set to record the Chrome window, mic checked.

## Do not

- Cue anything by hand off-camera.
- Show the Codex window, terminal, logs, dev QR page.
- Claim iMessage (handset delivery still unconfirmed as of Jay 23:06).
- Speed up footage. Judges read latency as honesty.
- Scroll on camera. Put a QR in the video (the code rotates).
