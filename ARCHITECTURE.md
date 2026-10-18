# Tenant — Architecture

Companion to [`notes/plan/PLAN.md`](notes/plan/PLAN.md) (the original build plan). This is the build spec: components, data model, wire protocol, lifecycles, and the exact browser/OS APIs each capability uses. Names here are the names in code.

---

## 0. Design principles (why it's shaped this way)

1. **Capabilities, not devices.** The agent never reasons about "a phone"; it reasons about `light`, `camera.capture`, `speak`. A device is a bag of capabilities with a label. This is what lets a judge's command route to *whichever* device can do it, and what makes adding a Hue bulb later a registry entry, not a code change.
2. **Leases, not accounts.** Access is a short‑lived grant tied to a room code. No users table, no passwords. Revocation = delete the lease. Everything the agent is allowed to do is derived from the lease at the moment of the request.
3. **Dumb devices, one brain.** Device pages do exactly what they're told and report back. All decisions live in the Brain. Two people can hold the whole system in their heads.
4. **Every failure has a face.** Timeouts, denials, and disconnects produce specific, pre‑written responses so a failure during judging reads as behavior, not a crash.

---

## 1. Components

```
┌─────────────────────────── guest side ────────────────────────────┐
│  iMessage (Photon shared line)      Chat page /g/{guest_id}        │
└──────────────┬──────────────────────────────┬─────────────────────┘
               │ poll 2 s (REST)               │ WebSocket /ws/guest
┌──────────────▼──────────────────────────────▼─────────────────────┐
│  BRAIN  (FastAPI, uvicorn, single process, asyncio)                │
│   channels/photon.py   channels/webchat.py                         │
│   core/registry.py     core/leases.py     core/bus.py              │
│   core/agent.py (LLM tool loop)           core/tools.py            │
│   api/join.py  api/leave.py  api/host.py  ws/devices.py ws/display │
│   state: in‑memory dicts + append‑only JSONL log (no DB)           │
└──────────────┬──────────────────────────────┬─────────────────────┘
               │ WebSocket /ws/device          │ WebSocket /ws/display
┌──────────────▼──────────────┐  ┌─────────────▼─────────────────────┐
│ DEVICE PAGES (phones, tablet)│  │ DISPLAY PAGE (laptop browser)     │
│ /d/{device_id}               │  │ /display  — graph, log, QR, reset │
│ torch, camera, flash, speak, │  └───────────────────────────────────┘
│ sound, show, wake lock       │  ┌───────────────────────────────────┐
└──────────────────────────────┘  │ LAPTOP ROOM AGENT (python, local) │
                                  │ connects to /ws/device as a device│
                                  │ osascript: music, volume, say,    │
                                  │ brightness, slides                │
                                  └───────────────────────────────────┘
```

**Hosting:** Brain + static pages on one small VM (Vultr) behind Caddy for automatic HTTPS (needs a real domain → use the GoDaddy track domain, or skip the VM and use Fly.io's free `*.fly.dev` TLS). HTTPS is non‑negotiable: camera/torch/wake‑lock all require a secure context. The laptop room agent runs locally and dials *out* to the Brain, so it works on any Wi‑Fi. **Decide hosting by 5 PM; a domain's DNS can take an hour to propagate.**

---

## 2. Data model (in‑memory; `state.py`)

```python
@dataclass
class Device:
    id: str                 # "owen-phone", stable per device (localStorage)
    label: str              # "Owen's phone (left side of table)"
    room_code: str          # from hello; a device belongs to exactly one room
    caps: dict[str, CapSpec]  # cap name -> JSON schema for args
    ws: WebSocket
    last_seen: float
    busy: bool = False

@dataclass
class CapSpec:
    name: str               # "light"
    args: dict              # JSON schema, e.g. {"on": {"type":"boolean"}}
    description: str        # fed to the LLM verbatim

@dataclass
class Room:
    code: str               # "7F3A", rotated on reset
    label: str              # "Room 7F3A"
    device_ids: set[str]

@dataclass
class PhotonBinding:
    assignment_id: str      # for DELETE on release
    agent_number: str       # the shared-pool number this guest texts
    handle: str             # guest's phone, E.164

@dataclass
class Lease:
    guest_id: str           # uuid4
    room_code: str
    state: Literal["joining","active","released","expired"]
    scopes: set[str]        # cap names allowed; default = all caps in room
    expires_at: float       # now + 600
    channel: Literal["photon","webchat"]
    photon: PhotonBinding | None
    display_name: str       # "Guest 3" or first name if given

@dataclass
class Session:              # conversation state per guest
    guest_id: str
    messages: list[dict]    # LLM transcript (trimmed to last 20 turns)
    last_active: float
```

Registry = `dict[str, Device]`. Leases = `dict[str, Lease]`. Sessions = `dict[str, Session]`. Everything is also appended to `log/events.jsonl` (one line per event) for the display's live log, VEYZL audit evidence, and post‑mortem.

---

## 3. Wire protocol — devices (`/ws/device`)

All frames JSON. The Brain is the only party that initiates `do`.

**Device → Brain, on connect (and on every reconnect):**
```json
{"type":"hello","id":"owen-phone","label":"Owen's phone","room":"7F3A",
 "caps":{
   "light":  {"description":"Turn the flashlight on or off","args":{"on":{"type":"boolean"}}},
   "flash":  {"description":"Fill the screen with a color at full brightness","args":{"color":{"type":"string"},"seconds":{"type":"number"}}},
   "speak":  {"description":"Say text out loud from this phone","args":{"text":{"type":"string"}}},
   "sound":  {"description":"Play a short sound: chime|alarm|doorbell","args":{"name":{"type":"string"}}},
   "camera.capture": {"description":"Take a photo and return an image URL","args":{"facing":{"type":"string","enum":["user","environment"]}}},
   "show":   {"description":"Show text or an image on this screen","args":{"text":{"type":"string"},"image_url":{"type":"string"}}}
 }}
```
Brain replies `{"type":"welcome","server_time":..., "room":"7F3A"}` and broadcasts registry state to the display.

**Brain → Device:**
```json
{"type":"do","req":"r_8f21","cap":"light","args":{"on":true},"deadline_ms":5000,"epoch":3}
```
`epoch` is the room's lease epoch, incremented on every revoke/reset. The device keeps the highest epoch it has seen and replies `err STALE` to any `do` with a lower one, so a frame queued before a reset can never fire after it. Args are always absolute state (`on:true`), never toggles — a timed‑out `do` has unknown outcome and is reported as such, not resent.
**Device → Brain:**
```json
{"type":"ok","req":"r_8f21","result":{"on":true}}
{"type":"err","req":"r_8f21","code":"PERMISSION|UNSUPPORTED|BUSY|FAILED|STALE","message":"camera permission denied"}
```
**Heartbeat:** Brain sends `{"type":"ping"}` every 5 s; device replies `{"type":"pong"}`. Two missed (10 s) → device marked offline, removed from tool list, display greys it out. A WebSocket `close` event marks it offline immediately. On reconnect the device re‑sends `hello`.

**Device auth:** the device page and laptop agent include `?t=DEVICE_TOKEN` (shared secret from env) when opening `/ws/device`; otherwise anyone who guesses `/d/` could register a fake device during judging.

`core/bus.py` implements `await bus.call(device_id, cap, args, timeout=5.0) -> Result`, with per‑device serialization (one `do` in flight per device; others queue) and a `Future` keyed by `req`.

---

## 4. Wire protocol — display (`/ws/display`)

Brain → Display on every change (debounced 50 ms):
```json
{"type":"state",
 "room":{"code":"7F3A","label":"Room 7F3A","join_url":"https://room.example/j/7F3A"},
 "devices":[{"id":"owen-phone","label":"Owen's phone","caps":["light","flash",...],"online":true,"busy":false}],
 "guests":[{"guest_id":"g_1","display_name":"Guest 1","channel":"photon","expires_in":412,"scopes":["*"]}],
 "log":[{"t":1760740000.1,"kind":"guest.join|guest.leave|cmd|do|ok|err|denied","text":"Guest 1: turn on a light → owen-phone.light(on=true) ✓"}]}
```
Display → Brain (host actions, require `HOST_TOKEN` from env, entered once):
```json
{"type":"host.reset"}            // revoke all leases, release Photon seats, rotate code, clear log, torch off
{"type":"host.revoke","guest_id":"g_1"}
{"type":"host.do","device_id":"owen-phone","cap":"light","args":{"on":false}}  // manual override
```
Keyboard: `R` = reset (with a 1‑s hold to avoid accidents), `X` = revoke selected guest.

---

## 5. Guest channels

### 5.1 Join flow (`api/join.py`)

`GET /j/{room_code}` → join page (static). Two buttons:

- **Chat here** → `POST /join {room_code}` → `{guest_id, guest_token, chat_url:"/g/{guest_id}#t={guest_token}"}` → redirect. No PII. `guest_id` is public (shown on the display, in logs); `guest_token` is the private credential, carried in the URL fragment so it never reaches server logs, and sent as `?token=` on `/ws/guest`. A WS without a matching token is closed with code 4401.
- **Text the room** → form with phone number (E.164 normalized client‑side) → `POST /join {room_code, phone}` → Brain calls Photon `POST /v1/projects/{id}/platforms/imessage/assignments {handle: phone}` (first `GET` existing assignments to reuse one for the same handle) → `{guest_id, imessage_number, sms_link}` → page shows a big button "Open Messages" and the fallback "or chat here". `sms_link` uses the cross‑platform form `sms:+1206…?&body=join%207F3A` — iOS wants `&body`, Android wants `?body`; `?&body` is accepted by both. Test on each.

Both paths create a `Lease` (TTL 600 s) and a `Session`. The display shows the guest immediately as "joining…" until their first message.

### 5.2 Web chat (`channels/webchat.py`, `/ws/guest`)

Guest page opens WS at `/ws/guest?guest_id=…&token=…` (token from the URL fragment). Frames: `{"type":"user","text":"turn on a light"}` → Brain runs the agent → streams `{"type":"assistant","text":"…"}` plus `{"type":"action","text":"owen-phone.light(on) ✓"}` events so the guest sees what happened. When a requested device is unavailable, the agent offers alternatives **in ordinary `assistant` text** and waits for the guest's choice — no new frame type. Hold‑to‑talk button uses the browser `SpeechRecognition` API where available (Chrome/Android; iOS Safari has partial support) and falls back to typing. Audio replies optional via Grok Voice TTS → `<audio>`.

### 5.3 Photon iMessage (`channels/photon.py`)

- One background task polls `GET /v1/projects/{id}/messages?direction=received&createdSince={cursor}&order=asc&pageSize=100&platform=imessage` every 2 s; advances `cursor` to the newest `createdAt`; de‑dupes by message `id`.
- Maps the sender handle → `Lease` via `PhotonBinding.handle`. Unknown sender → ignored (shared line only delivers assigned senders anyway).
- Text "join 7F3A" (or anything, if lease is `joining`) → activates the lease and replies with the welcome + device list. Otherwise text → agent.
- Replies: `POST /v1/projects/{id}/messages` with `spaceId` (from the inbound message's `space.id`), `senderId` (= inbound `receivedBy.id`, the shared‑line agent), `content {type:"text", format:"plain", text}`, header `idempotency-key: reply:{incoming_id}`. **Verified live 4:11 PM** — full round trip, reply accepted HTTP 202, ~2 s inbound latency on polling. The room **never** sends first; it only replies.
- **Gotchas, all solved in `spikes/photon/test.py` — do not re‑debug:**
  - Cloudflare returns 403 (error 1010) to Python's default `urllib` User‑Agent. Send any custom `User-Agent`. `httpx` is fine.
  - **Never set `parentMessageId` on iMessage sends.** Shared lines don't support threaded replies and surface it as `409 SPACE_NOT_SENDABLE "Replies are not supported for this Space"`. Photon's own quickstart includes the field; the sample is wrong for shared lines.
  - Deleting the thread on the phone does nothing — Photon's space is keyed by participant pair, not device thread.
  - A 202 is *acceptance*, not delivery. Confirm on the phone during rehearsal.
- Project: `pho_prj_01m55zzgmresk81n1kz3w5q4ba`; shared line `+1 628‑502‑4649`; 1 of 25 assignments used after the spike. Not yet tested with a second phone number — assumed identical.
- On leave/expiry/reset: `DELETE /v1/projects/{id}/platforms/imessage/assignments/{assignment_id}` to free the seat (25 on Free).
- Rate: one poll loop total, not per guest.

If `PHOTON_API_KEY` is unset, the "Text the room" button is hidden. The system is fully functional without Photon.

---

## 6. Agent (`core/agent.py`, `core/tools.py`)

### 6.1 Tool generation (per turn)

```python
def tools_for(lease: Lease) -> list[ToolDef]:
    room = rooms[lease.room_code]
    out = []
    for dev in registry.online_in(room):
        for cap in dev.caps.values():
            if lease.allows(cap.name):
                out.append(ToolDef(
                    name=f"{slug(dev.id)}__{slug(cap.name)}",      # owen_phone__light — stable across turns
                    description=f"[{dev.label}] {cap.description}",
                    parameters=cap.args_schema))
    out.append(ToolDef(name="room__list_devices", ...))
    out.append(ToolDef(name="room__leave", description="End this guest's access"))
    return out
```
Tool names are deterministic so the model's memory of "I used `owen_phone__light` last turn" stays valid. ~25–30 tools is normal for function calling.

### 6.2 System prompt (fixed text + live block)

> You are Room {code}, a physical room that a guest is talking to. You control real devices in the room through tools. Rules: (1) When the guest asks for something, act — call a tool — then confirm in one short sentence naming the device you used. (2) If several devices can do it, pick the most sensible one using their labels; if truly ambiguous, pick one and say which. (3) If nothing in the room can do it, say exactly what's missing; never pretend. (4) Never claim an action succeeded unless the tool returned ok. (5) Keep replies under 25 words; this is a text thread. (6) If the guest says goodbye/leave/done, call `room__leave`.
> Currently in the room: {bulleted device/caps list}. Guest: {display_name}, access expires in {mm:ss}.

### 6.3 Loop

```
user text → append → LLM(tools=tools_for(lease)) →
  while tool_calls: for each: parse device/cap → bus.call(...) → append tool result (ok/err verbatim) → LLM again (max 4 rounds)
→ final assistant text → send via channel → log
```
Lease checked **before** every tool call (not just at turn start) so a mid‑turn revoke is honored. Denied → tool result `{"error":"lease revoked"}` and the agent is told to inform the guest. One turn in flight per guest; a second message while a turn runs is queued (not dropped).

Model: whichever fast function‑calling model we have a key for (Anthropic Haiku‑class, OpenAI mini‑class, or Grok fast). Budget: p50 turn < 1.5 s including one device action. Transcript trimmed to last 20 messages.

### 6.4 Guest without a lease

Any message from a `guest_id`/handle with no active lease gets a fixed reply (no LLM): *"You're no longer in Room 7F3A. Scan the room code to join again."* This is the Act‑3 line; it must be deterministic.

### 6.5 Rules — STRETCH, from Morph (build only after the 9 PM run‑through passes)

A rule is data, not code: `{"rule_id","guest_id","when":{"event":"guest.join"},"do":[{"device":"owen-phone","cap":"flash","args":{"color":"green","seconds":2}},{"device":"laptop","cap":"say","args":{"text":"Welcome"}}],"expires_at":...}`.

- **Install:** the agent gets one extra tool, `room__add_rule(when, do)`, with `when.event` constrained to an enum of events the Brain already emits: `guest.join`, `guest.leave`, `photo.taken`, `timer(seconds)`. The LLM proposes; `core/rules.py` validates the event is in the enum and every `do` step is a (device, cap) the guest's lease allows **at install time**. The agent confirms in one sentence what will happen.
- **Fire:** `core/bus.py` emits events on the in‑process bus; `rules.py` matches and dispatches the `do` list through the same lease check as a live command (so a revoked guest's rule dies with them). No LLM call at fire time — timing is deterministic.
- **Bounds:** one rule per guest; a new rule replaces the old one; rules expire with the lease; 10 s cooldown per rule. Display shows the active rule as a card so the audience can see the cause before the effect.
- **Optional event:** `phone.shake` from the device page via `DeviceMotionEvent` (iOS needs `requestPermission()` inside the Join gesture). Add only if a 10‑minute spike shows the permission prompt is tolerable.
- **Not included:** any camera‑derived event. Perception is out of scope for this build (see `notes/plan/PLAN.md` §11).

---

## 7. Device page (`/d/{device_id}`) — capability implementations

Single static page, vanilla JS, no framework. On first load: generate `device_id` → `localStorage`; ask for a label; big **Join room** button (the one user gesture that unlocks everything below).

| Cap | Implementation | Gotchas |
|---|---|---|
| `light` | `stream = getUserMedia({video:{facingMode:"environment"}})`; `track.applyConstraints({advanced:[{torch:on}]})` | iOS 17.5+ only; needs the camera permission; keep `stream` alive for the page lifetime; on iOS 18 `getSettings().torch` may be stale — track state locally. Android Chrome fine. |
| `flash` | Full‑viewport fixed `<div>`, background color; revert after `seconds` | `requestFullscreen()` is **not** available on iPhone Safari — don't rely on it. Max screen brightness can't be set from web; ask the human to max it once. |
| `speak` | `speechSynthesis.speak(new SpeechSynthesisUtterance(text))` | Must be after a user gesture (Join covers it). Pick a voice once. |
| `sound` | Pre‑decoded `AudioBuffer`s via `AudioContext` created on Join | Autoplay policy; `ctx.resume()` on Join. |
| `camera.capture` | For `environment`, grab a frame from the existing torch `stream` (no new stream). For `user`, open a second stream, capture, stop it, then **re‑apply torch** — iOS allows one active camera at a time and switching kills the torch. Draw to canvas; `canvas.toBlob` → `POST /upload` → returns URL | Return URL in `ok.result.image_url`; Brain then `show`s it on the display. |
| `show` | Render text/image full‑screen | Keep device page in foreground. |
| wake lock | `navigator.wakeLock.request("screen")` on Join; re‑request on `visibilitychange` | iOS 16.4+. Phones must stay unlocked and on this page. |
| reconnect | Exponential backoff 0.5 → 8 s; resend `hello`; keep local `device_id` | Re‑acquire wake lock after reconnect. |

Tablet/laptop as a device: same page; caps auto‑detected (no torch → omit `light`).

---

## 8. Laptop room agent (`agent/laptop.py`)

Python, connects to `/ws/device` with `id:"laptop"`, `label:"Room speaker & screen"`. Capabilities via `subprocess.run(["osascript","-e", ...])`:

| Cap | Command |
|---|---|
| `music.play` | `tell application "Music" to play playlist "{name}"` (or Spotify: `tell application "Spotify" to play track "spotify:playlist:…"`) |
| `music.pause` | `tell application "Music" to pause` |
| `volume` | `set volume output volume {0-100}` |
| `say` | `say -v Samantha "{text}"` (or Grok Voice TTS → afplay) |
| `brightness` | `brightness {0.0-1.0}` (Homebrew `brightness`) or skip if not installed |
| `slides.next` / `slides.show` | `tell application "Keynote" to show next` / open file |

Bluetooth speaker is simply the laptop's audio output. Test music + `say` overlapping once.

---

## 9. Lease lifecycle

```
            POST /join                 first message / "join" text
  (none) ─────────────▶ joining ───────────────────────────────▶ active
                          │                                        │
                          │ 120 s no first message                 │ "leave" | TTL expiry | host.revoke | host.reset
                          ▼                                        ▼
                        expired  ◀──────────────────────────────  released
                                   (Photon assignment deleted, session kept 10 min for the denial reply)
```
Background task every 5 s: expire leases, release Photon seats, push display state. Every revoke/expiry/reset increments `room.epoch`, which is stamped on all subsequent `do` frames (§3). Expiry warning: at 60 s remaining the agent (on next turn) mentions it; we do not send unsolicited messages (Photon can't; webchat could but we keep parity).

---

## 10. Host console & reset

`host.reset` performs, in order: cancel in‑flight `do`s → `light off` on every device that has it → delete all leases → release Photon assignments (best effort, parallel) → rotate `room.code` → clear display log → broadcast state. Target < 1 s wall time. Rotating the code invalidates any stale QR a judge photographed.

---

## 11. Security & safety (also what VEYZL will look at)

- Secrets only in env (`PHOTON_API_KEY`, `LLM_API_KEY`, `HOST_TOKEN`, `DEVICE_TOKEN`); `.env` gitignored; keys scoped to one Photon project.
- Guests can only reach `/join`, `/g/*`, `/ws/guest`, `/upload`; host endpoints need `HOST_TOKEN`; device WS needs `DEVICE_TOKEN` plus a `room_code` that matches.
- Lease check on every tool call; scopes default to all room caps but can exclude (`camera.capture` off for guests by default? — **decision: on**, it's part of the demo; mention in the pitch that scopes exist).
- Rate limit: 1 command / 2 s per guest; 10 photos / lease.
- Camera photos stored in memory with a 10‑min TTL, never to disk.
- Confirm‑before‑act hook exists for caps flagged `sensitive` (none today; this is the VEYZL "finding changed the build" candidate if their audit asks for human‑in‑the‑loop).

---

## 12. Failure behaviors (pre‑written)

| Failure | Guest sees | Display shows |
|---|---|---|
| Device timeout (5 s) | "Owen's phone didn't respond — try again or ask for another device." | `err timeout` row, device marked slow |
| Device offline | tool not offered; if asked: "There's no light I can reach right now." | device greyed |
| Lease revoked mid‑command | "You're no longer in Room 7F3A." | `denied` row |
| LLM error / slow (>8 s) | "The room's thinking is slow — say that again?" | `err llm` |
| Photon send fails | retry once; log; webchat unaffected | `err photon` |
| Brain restart | devices reconnect in <8 s and re‑hello; leases lost → room effectively reset | state rebuilds |

---

## 13. Repo layout

```
dubhacks2/
  brain/            FastAPI app (api/, channels/, core/, ws/, state.py, main.py)
  web/              static pages: join.html, guest.html, device.html, display.html, shared.js
  agent/            laptop.py (room agent)
  scripts/          dev.sh (uvicorn + caddy), reset.py, seed_demo.py
  log/              events.jsonl (gitignored)
  PLAN.md  ARCHITECTURE.md  README.md  .env.example
```
Python 3.12, `fastapi`, `uvicorn[standard]`, `httpx`, `websockets`, `pydantic`, LLM SDK, `photonhq-api==0.5.0`. Frontend: vanilla JS + a few hundred lines of CSS. No build step (serve `web/` statically) — nothing to break at 3 AM.

---

## 14. Tech choices and what we chose over

| Choice | Over | Why | Would switch if |
|---|---|---|---|
| Single FastAPI process, in‑memory state | DB + queue | Two people, 18 h, one room; restart = reset is acceptable | We needed multi‑room persistence |
| WebSocket devices | Polling / WebRTC | Bidirectional, trivial, phones→cloud works through any NAT | Needed video streaming (WebRTC) |
| Capability‑per‑tool | One generic `control(device,cap,args)` tool | Models route far better with explicit, labeled tools; schema per cap | Tool count > ~60 |
| Vanilla JS pages | React | No build, no hydration bugs, phones load instantly | — |
| Photon as *optional* channel | Photon as the only channel | Free tier needs per‑sender assignment; chat page is the reliable floor | Dedicated line were free |
| osascript for laptop | Home Assistant | Zero setup, real effects (music/volume) | Real smart devices appear (then HA/Hue API as another device) |
