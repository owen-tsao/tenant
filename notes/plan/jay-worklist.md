# Jay — the Brain and the devices

You own everything that makes Tenant *work*: the FastAPI Brain (registry, leases, bus, agent loop, Photon channel, host console), the phone device page's JavaScript, the laptop `osascript` agent, and hosting. Owen owns everything a human *looks at* (join/guest/display pages, styling, slides, video, Devpost). The seam between you is the wire protocol in `ARCHITECTURE.md` §3–§5 — build to it exactly; Owen's pages are coded against those frames in parallel using a mock.

Read first: `ARCHITECTURE.md` (all of it — it is the spec), then `PLAN.md` §1–§3 and §9 (what, scope, kill conditions). Everything below references section numbers from `ARCHITECTURE.md`.

## What you own

| Piece | Files | Done when |
|---|---|---|
| App + state | `brain/main.py`, `brain/state.py`, `brain/config.py` | §2 dataclasses verbatim (incl. `PhotonBinding`, `Lease.state`, `Device.room_code`, `Room.epoch`); `uvicorn brain.main:app` boots; serves `web/` statically at `/`; routes `/j/{code}`, `/g/{guest_id}`, `/d/{device_id}`, `/display` all return the matching HTML file |
| Registry + device WS | `brain/core/registry.py`, `brain/ws/devices.py` | `hello` → registered; `online_in(room)`; ping 5 s, offline after 2 missed or socket close (§3); `DEVICE_TOKEN` checked on connect |
| Bus | `brain/core/bus.py` | `await bus.call(device_id, cap, args, timeout=5.0) -> Result`; one `do` in flight per device, rest queue; `epoch` stamped on every `do`; `err STALE` handled; `FakeDevice` class that answers `ok` instantly for tests |
| Leases | `brain/core/leases.py` | `create(room, channel, phone?) → Lease(joining)`, `activate`, `revoke`, sweep every 5 s (§9); every revoke/expiry/reset does `room.epoch += 1`; `joining` expires after 120 s with no first message |
| Join / leave API | `brain/api/join.py` | `POST /join {room_code, phone?}` → `{guest_id, chat_url, imessage_number?, sms_link?}` (§5.1); `POST /leave {guest_id}`; invalid room code → 404 with JSON `{error}` |
| Agent | `brain/core/agent.py`, `brain/core/tools.py` | `tools_for(lease)` rebuilt per turn, names `slug(dev)__slug(cap)` (§6.1); system prompt §6.2; loop §6.3, max 4 rounds, lease checked before **each** tool call; one turn in flight per guest, second message queued; no‑lease → fixed denial string, no LLM call (§6.4) |
| Web chat channel | `brain/channels/webchat.py` | `/ws/guest?guest_id=` ; in: `{"type":"user","text"}`; out: `{"type":"assistant","text"}` and `{"type":"action","text"}` (§5.2) |
| Photon channel | `brain/channels/photon.py` | One poll loop, 2 s, cursor + de‑dupe by id (§5.3); handle → lease; reply‑only; `DELETE` assignment on release; hidden entirely if `PHOTON_API_KEY` unset. **Spike passed (§5.3) — copy the request shapes from `spikes/photon/test.py`, send a custom `User-Agent`, and never include `parentMessageId`.** Owen gives you the keys out of band — never commit them |
| Display WS + host | `brain/ws/display.py`, `brain/api/host.py` | `state` frame exactly as §4, debounced 50 ms; `host.reset` / `host.revoke` / `host.do` require `HOST_TOKEN`; reset does §10 in order, <1 s |
| Upload | `brain/api/upload.py` | `POST /upload` (image/jpeg) → `{url}`; in‑memory, 10‑min TTL, 10 per lease (§11) |
| Log | `brain/core/log.py` | Append one JSON line per event to `log/events.jsonl`; same rows feed the display `log` array |
| Device page JS | `web/device.html` (JS only — Owen owns the CSS via `web/tenant.css`) | §7 table: Join button → wake lock + AudioContext + torch stream; `light`, `flash`, `speak`, `sound`, `camera.capture`, `show`; reconnect with backoff + re‑`hello`; `localStorage` device id; label prompt |
| Laptop agent | `agent/laptop.py` | Connects to `/ws/device` as `laptop` with `music.play/pause`, `volume`, `say`, `slides.next` via `osascript` (§8); runs with `python agent/laptop.py` |
| Hosting | `scripts/dev.sh`, `fly.toml` or `Caddyfile`, `.env.example` | Public HTTPS URL that an iPhone on cellular can load by 7:30; `PUBLIC_URL` env drives QR and `sms:` links. Owen hands you any account/credit codes |
| **Stretch** | `brain/core/rules.py` | §6.5 — only after the 9:30 run‑through passes; `phone.shake` is your call after a 10‑min DeviceMotion spike |

## Order of work (risk first, not data flow)

Each step has a check you can run yourself. Don't start the next until the check passes.

1. **Boot** — `state.py`, `config.py`, `main.py` with every route and WS endpoint stubbed; static `web/` served. *Check:* `curl localhost:8000/display` returns Owen's HTML (or a placeholder if his isn't there yet).
2. **Device WS + registry + bus** — with `FakeDevice`. *Check:* a pytest (or a 20‑line script) opens a WS, sends `hello`, Brain calls `bus.call("fake","light",{"on":true})`, gets `ok` within 50 ms; a second call while the first is pending is queued, not interleaved.
3. **Real phone torch** — `device.html` JS: Join → torch stream → `light`. Torch and camera need a secure context, and a LAN IP over plain HTTP is *not* one on iOS — so either run the Brain behind `mkcert` locally (trust the cert on the phone once) or do step 8 (deploy) now and test against the public URL. *Check:* phone loads `/d/phone-a`, taps Join, and `curl -X POST .../host/do -H 'Authorization: Bearer $HOST_TOKEN' -d '{"device_id":"phone-a","cap":"light","args":{"on":true}}'` turns the torch on. **This is the 6:00 checkpoint.**
4. **Leases + join** — `POST /join` creates `joining`; first `/ws/guest` message activates. *Check:* lease appears in the display `state` frame with a countdown; expires at 600 s; `joining` dies at 120 s.
5. **Agent loop** — against `FakeDevice` first, then the real phone. *Check:* typed `"turn on the light"` over `/ws/guest` → `action` event → phone torch on → `assistant` text names the device. Second check: revoke the lease mid‑conversation, send another command → the fixed denial string, and **no LLM call logged**.
6. **Display WS** — `state` frames on every change. *Check:* Owen's `display.html` (or his mock fixture diffed against your output) renders devices/guests/log with no console errors.
7. **Host reset** — `host.reset` with token. *Check:* reset during an in‑flight `do` → the device replies `STALE` or the call is cancelled; code rotates; Photon seats released; all in <1 s wall time.
8. **Deploy** — HTTPS. *Check:* iPhone on **cellular** (Wi‑Fi off) loads `/d/phone-a`, joins, torch toggles from the Brain. **This is the 7:30 kill check.**
9. **Photon** — assignment on join, poll, reply, release. *Check:* a number not yet assigned → `POST /join` with phone → text `join 7F3A` from it → reply arrives in Messages within 5 s; `/leave` → assignment gone from `GET assignments`.
10. **Laptop agent** — music, volume, say. *Check:* "play something calm" from the guest page → Music/Spotify plays through the paired speaker; "say hello" is audible while music plays.
11. **Hardening** — two guests at once, reconnect storms, phone sleeps and wakes. *Check:* kill the Brain, restart it; both phones re‑`hello` within 8 s with no human touching them.
12. **Stretch** — rules (§6.5).

## Interfaces Owen is coding against — do not change silently

- `/ws/display` → `state` frame, exactly §4. Fields he reads: `room.code`, `room.join_url`, `devices[].{id,label,caps,online,busy}`, `guests[].{guest_id,display_name,channel,expires_in,scopes}`, `log[].{t,kind,text}`.
- `/ws/guest` → `assistant` and `action` frames, §5.2.
- `POST /join` request/response, §5.1. The join page reads `chat_url`, `imessage_number`, `sms_link`.
- Device `do` frames and `ok`/`err` codes, §3 — his CSS keys off states your JS sets as `data-state` attributes on `<body>`: `idle | joining | ready | busy | offline | error`.

**If you need to change any of these:** edit `ARCHITECTURE.md` first, message Owen, then change code. He has a mock fixture (`web/mock/state.json`) that must keep matching your output — ask him to update it when you change a frame.

## Do not touch

`web/join.html`, `web/guest.html`, `web/display.html`, `web/tenant.css`, `web/mock/`, `slides/`, `README.md` (except the "Run it" section — that's yours), Devpost. If something in those blocks you, message Owen rather than editing.

## Your log

`notes/jay.md` — append one line for a deviation from the plan, an interface change, or a blocker. Nothing else. Read `notes/owen.md` at every check‑in.

## Environment

`.env.example` is yours to write. Variables: `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`, `LLM_API_KEY` (+ `LLM_MODEL`), `HOST_TOKEN`, `DEVICE_TOKEN`, `PUBLIC_URL`, `ROOM_CODE` (optional fixed code for rehearsals). Owen gives you real values in person. `.env` is gitignored — keep it that way; VEYZL will audit the repo.

Python 3.12; `fastapi`, `uvicorn[standard]`, `httpx`, `websockets`, `pydantic`, the LLM SDK for whichever key we hold, `photonhq-api==0.5.0` or plain `httpx` against `https://api.photon.codes/v1` (the smoke test in `spikes/photon/test.py` already shows the exact calls that worked). Pin versions in `requirements.txt`. No other dependencies without a message to Owen first.

## Checkpoints you're responsible for

| Time | What must be true |
|---|---|
| 6:00 | Phone joins; torch toggles via `host.do` curl; agent loop works against `FakeDevice` |
| 7:00 | Typed "turn on the light" from `guest.html` lights a real phone locally |
| **7:30** | **Kill check:** phone on cellular, public HTTPS, torch via chat. Fail → ship Brain + 2 phones + display only; stop everything else |
| 8:30 | Rehearsal #1 — your phone as the judge, both channels |
| 9:30 | Full 3‑min run‑through, timed |
| 10:30 | Devpost draft deadline (Owen writes; you give him the one‑paragraph "how it works" by 10:15) |
| 12:30 | Rehearsal #2 — a stranger as judge; nothing new after this |

## When something fails

Every failure in §12 has a pre‑written guest reply and a display row. Implement those before adding features — a failure that *reads as behaviour* costs nothing at judging; a stack trace costs the demo. If a check above fails, fix that boundary; do not move on and hope integration sorts it out.
