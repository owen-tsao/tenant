# Owen — everything a human sees

You own the human‑facing surface of Tenant: the three guest/host pages (`join`, `guest`, `display`), the shared stylesheet that also skins Jay's device page, the demo slides, the 3‑minute video, Devpost, and the README story. You also run rehearsals — you are the director of the 3‑minute demo. Jay owns the Brain, the device page's JavaScript, the laptop agent, Photon, and hosting.

The seam is the wire protocol in `ARCHITECTURE.md` §3–§5. Your pages are coded against those frames; a mock lets you build and polish everything before the Brain exists.

Read first: `PLAN.md` §1, §7, §8 (what the guest experiences, the demo script, the risks), then `../../ARCHITECTURE.md` §4 (display frame), §5.1–5.2 (join and chat frames), §7 (device page states), §12 (failure copy).

## What you own

**Page map (decided 5:25 PM with Owen).** Three people, three surfaces, never shared:
- **Judge / guest** → sees Owen's **slide deck** for the pitch (it ends on the QR), then scans and lives in **Messages** (Photon) or the fallback chat page. They never operate our screen.
- **Us (host)** → the **web app**: a setup flow (name the room → add our devices → room is ready, print the QR) and the **display**, which is our operational screen with the audience looking over our shoulder. No QR billboard on the display; the QR is a printed card + the last slide.
- **Devices (our phones)** → `device.html`, a prop nobody reads.
A landing page is Devpost‑only priority — built last, Sunday if needed.

**Theme (decided 5:30 PM):** dark plum `#1a1523` floor, surfaces `#211b2c`, pink `#f0a8e0` as the single colour (live guest block, acting‑device dot, newest‑row wipe), pink‑on‑plum dither motif as the only texture (empty state + setup's final step). Device page stays black for the flash. Not the earlier black/amber.

| Piece | Files | Done when |
|---|---|---|
| Stylesheet | `web/tenant.css` | One file, no framework; plum/pink tokens; used by all pages; readable from 2 m on the laptop for `display`; device page black so screen flash is dramatic |
| Setup flow (host onboarding) | `web/setup.html` | Three steps: name the room → add devices (shows each device's `/d/{id}` link + a code to type; devices appear live as they `hello`) → "Your room is ready" with the printable QR to `/j/{code}` and a button to open the display. Needs one Brain call to set the room label — ask Jay |
| Join page | `web/join.html` | Two buttons: **Chat here** (default, one tap, no PII) → `POST /join {room_code}` → redirect to `chat_url`; **Text the room** → phone field (E.164 client‑side) → `POST /join {room_code, phone}` → big "Open Messages" using `sms_link` + "or chat here" fallback. Room code read from the URL `/j/{code}`. Hidden "Text the room" when the join response has no `imessage_number`. Works on iPhone Safari and Android Chrome |
| Guest chat | `web/guest.html` | `/ws/guest?guest_id=` from the URL `/g/{guest_id}`; renders `assistant` and `action` frames distinctly (actions as small system rows, e.g. "owen‑phone.light(on) ✓"); sticky input; sends `{"type":"user","text"}`; shows a countdown from `expires_in` if the Brain includes it; after a denial the input stays enabled but a "Scan the code to rejoin" banner appears. Stretch: hold‑to‑talk via `webkitSpeechRecognition` |
| Display | `web/display.html` | `/ws/display`; **our** operational screen, audience looks over our shoulder. Top bar: room code (mono) + one state sentence + clock. Left: the guest — pink block with countdown when present, dither motif when empty. Right: device table (Device · Can do · State · Last action) over the ledger (newest on top, pink wipe once). Regions split by hairlines, no framed boxes, no QR, no join URL, nothing code‑like. `R` held 1 s → `host.reset` (token in `localStorage`); `X` → revoke selected guest |
| Device page skin | `web/tenant.css` only — the JS in `web/device.html` is Jay's | Style off `<body data-state="idle|joining|ready|busy|offline|error">`. Big Join button in `idle`; label + "Connected to Room 7F3A" in `ready`; `flash` is a full‑viewport fixed div Jay toggles — make sure nothing (status bar, label) sits above it |
| Mock | `web/mock/state.json`, `web/mock/chat.json`, `?mock=1` handling in `web/shared.js` | Pages render fully from fixtures with no Brain running; fixtures match `ARCHITECTURE.md` §4/§5.2 field‑for‑field; Jay diffs his real output against them |
| Slides | `slides/` (Keynote `.key` or a single `slides.html`) | ≤ 5 slides for the laptop screen behind the demo: title, "the problem" (rooms you don't own), "what you just saw" (registry → lease → agent → device), roadmap, team. Jay's laptop agent can advance with `slides.next` — test it once |
| Video | `video/` (not committed — link in Devpost) | 3 minutes, shot on a phone, follows `PLAN.md` §7 beat for beat; record Sunday 7:00–8:30 |
| Devpost + README | `README.md` (story sections), Devpost | Draft by **10:30 PM**; final with video by 9:30 AM. Plain language; outcome first; honest limits. Track declarations from `PLAN.md` §5 |
| Rehearsals | `PLAN.md` §7 is the script | You direct #1 (8:30), #2 (12:30, stranger as judge), #3 (Sunday 8:30). Time each; log every miss |
| **Stretch** | VEYZL | Connect repo, open a PR, run the audit, fix one finding, screenshot it for Devpost |

## Order of work

1. **Mock + display** (4:20–5:30). Write `web/mock/state.json` from §4 and `web/shared.js` with `connectDisplay(onState)` that uses the fixture when `?mock=1`. Build `display.html` against it. *Check:* open `web/display.html?mock=1` from a static server — QR, 5 devices, 1 guest with a ticking countdown, 6 log rows, no console errors. This is the thing judges stare at; it should look finished by 6.
2. **Join page** (5:30–6:15). *Check:* on your iPhone and an Android, both buttons reach their next screen using the mock `POST /join` response; the `sms:` link opens Messages with "join 7F3A" pre‑filled on **both** platforms.
3. **Guest chat** (6:15–7:00). *Check:* `?mock=1` replays `web/mock/chat.json` as a scripted conversation (user → action → assistant) with realistic timing; a denial renders the banner.
4. **Wire to the real Brain** (7:00–7:30). Jay should have `/ws/display` and `/ws/guest` live locally. *Check:* your pages work with `?mock=1` removed; any field mismatch → fix the fixture *or* message Jay (never silently adapt to a frame that differs from `ARCHITECTURE.md`).
5. **Device page skin** (7:30–8:15). *Check:* on a phone, every `data-state` looks intentional; `flash` covers everything.
6. **Rehearsal #1** (8:30) — direct it; write down every miss in `PLAN.md` §8 or `IDEAS.md`.
7. **Slides** (8:45–9:30). *Check:* `slides.next` from the laptop agent advances them.
8. **Rehearsal #2 prep + Devpost draft** (9:30–10:30). **10:30 PM hard deadline.**
9. **Stretch** — VEYZL, hold‑to‑talk, Grok Voice TTS playback in `guest.html` (needs Jay to add an `audio_url` to `assistant` frames — ask first).
10. Sunday: video, README, Devpost final, rehearsal #3.

## Interfaces you depend on — from `ARCHITECTURE.md`

- **`/ws/display` `state` frame (§4):** `room.{code,label,join_url}`, `devices[].{id,label,caps[],online,busy}`, `guests[].{guest_id,display_name,channel,expires_in,scopes[]}`, `log[].{t,kind,text}` where `kind ∈ guest.join|guest.leave|cmd|do|ok|err|denied`. Host → Brain: `host.reset`, `host.revoke {guest_id}`, `host.do {device_id,cap,args}`; all carry `token`.
- **`/ws/guest` (§5.2):** send `{"type":"user","text"}`; receive `{"type":"assistant","text"}` and `{"type":"action","text"}`.
- **`POST /join` (§5.1):** body `{room_code, phone?}` → `{guest_id, chat_url, imessage_number?, sms_link?}`; 404 `{error}` on bad code.
- **Device page states (§7):** Jay sets `<body data-state>`; you style it.

If you need a field that isn't there, the order is: propose it in `ARCHITECTURE.md` → message Jay → he adds it → you update the mock. Never guess at a field.

## Do not touch

Anything under `brain/`, `agent/`, `scripts/`, and the JavaScript in `web/device.html`. If a page needs the Brain to behave differently, message Jay. `.env` values are shared in person only — you hold the Photon keys and any hosting credits; hand them to Jay, never paste them into chat logs or the repo.

## Your log

`notes/owen.md` — append one line for a deviation from the plan, an interface change, or a blocker. Nothing else. Read `notes/jay.md` at every check‑in.

## Design notes (so it doesn't look like a hackathon admin panel)

- Monochrome base, one accent, used only for *live* things: a device going busy, a guest joining, a log row landing. Everything else is greys and type.
- `display.html` is a stage, not a dashboard: the QR and room code are the biggest things on screen until a guest joins; then the guest card and the log take over. Don't show more than the judge needs to understand cause → effect.
- `guest.html` should feel like a text thread, because for Photon users it literally is one. Keep copy under 25 words — the agent's system prompt enforces that on its side.
- Failure states (§12) get the same visual weight as success. "Owen's phone didn't respond" rendered calmly reads as behaviour; a red toast reads as a bug.

## Checkpoints you're responsible for

| Time | What must be true |
|---|---|
| 6:00 | `display.html?mock=1` looks finished |
| 7:00 | Join + chat pages work against the mock on iPhone and Android |
| 7:30 | Pages wired to the real Brain locally (Jay's kill check is the same moment — be at his screen) |
| 8:30 | Rehearsal #1 directed and logged |
| **10:30** | **Devpost draft submitted** |
| 12:30 | Rehearsal #2 with a stranger; slides advance from the laptop agent |
| Sun 9:30 | Video recorded, README final, Devpost final |
