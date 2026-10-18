# Tenant — DubHacks '26 build plan

> Pitch line: **"The room has a brain. Scan the code and you can talk to it. Leave, and it forgets you."** You're a tenant of the room's devices, not an owner — access is temporary and granted by the space.

> **Claim we are making (falsifiable):** In one prepared room, a stranger can scan a QR code and, within 30 seconds and with no app or account, make real devices they do not own act by talking to the room; the room routes each request to a supported device; and when their access ends — by leaving, by timeout, or by host reset — the same new request is refused. The claim fails if any action is manually cued, if a new or queued guest command is dispatched after authority ends, or if adding a supported device instance requires a code change. Already-dispatched work may finish and must be reported truthfully; no physical undo is claimed. We do **not** claim perception, autonomous judgment, or arbitrary‑device interoperability.

> **Current execution gate (Jay, October 17):** Lighting, room audio, temporary access and device adaptation are the baseline. Jay has explicitly opened coordinated music across the Mac and phone for implementation, including many actions in one natural request. Photo-to-screen and proactive rules remain planning-only. The genuine shared native agent and Photon second channel follow the current decisions in `notes/jay.md`. Reviewed source, final-revision checks and actual physical observations are required for each demonstrated capability; no feature is merge-ready while a required check remains blocked.

**Guest experience (Jay’s current decision):** Scan the QR to open a temporary guest chat powered by Jay’s signed-in Codex. Tenant checks that guest’s room permissions before executing each proposed action. Letting a guest connect their own coding agent is a later, closed gate; it adds no implementation to the current build.

## 1. What a guest experiences

You walk up to a room — a hotel room, a hospital bed, an Airbnb, a conference table — and there's a QR code. You scan it, type your phone number (or just tap *Join*), and a text thread (or a chat page) opens with the room. You say "turn on a light," "play something calm," "show me what's in here," "take a picture of me." The room does it, using whatever devices it has, and tells you what it did. You text "leave" (or your lease expires, or the host ends it) and the room says goodbye and will no longer take your commands. No app, no account, no pairing with the host's smart‑home system.

For the judge at our table, *they* are the guest. They control our table's devices from their own phone and watch the room forget them.

## 2. How it works (one paragraph, real names)

A **Brain** (FastAPI + WebSocket server on a public HTTPS host) holds a **device registry**: every device keeps a WebSocket open and announces a capability manifest (`{"id":"owen-phone","caps":{"light":{...},"camera.capture":{...},...}}`). A **Lease** is a short‑lived grant (room code → guest identity → TTL + scopes). Guests reach the Brain through one of two **channels**: Photon iMessage (we create a shared‑line assignment for their phone number, they text the returned number) or a web chat page (typed / hold‑to‑talk). Each guest gets an **Agent session**: an LLM tool‑calling loop whose tool list is rebuilt every turn from the registry filtered by the guest's lease scopes. Tool calls become `{"do":"light","on":true}` messages down a device's socket; the device replies `{"ok":true}` and the agent narrates. Revocation deletes the lease; subsequent commands get a fixed denial. The laptop runs a **Display** page (capability graph + what's happening) and a **Laptop device agent** (AppleScript: music/volume/brightness/say/Keynote). Phones run a **Device page** (torch, camera, screen flash, TTS, sound, wake lock).

## 3. Scope — locked device list

| Device | Capabilities | How |
|---|---|---|
| Laptop (display) | `show(text/image/url)`, `graph` | Browser page on the laptop, WebSocket |
| Laptop (room) | `music.play/pause`, `volume`, `brightness`, `say`, `slides.next` | Python agent → `osascript` |
| Bluetooth speaker | (audio output of laptop) | Pair once; it's the laptop's speaker |
| Phone A (Owen) | `light` (torch), `camera.capture`, `flash(color)`, `speak(text)`, `sound` | Device page, iOS 17.5+ Safari |
| Phone B (teammate) | same | Device page |
| Borrowed tablet/laptop (optional) | `show`, `speak` | Device page |

Not in scope today: webcam vision (Perceptron), guest‑lends‑their‑camera, voice calls, any simulated device. Anything added after the 7:30 kill check must be a device page instance, not a new capability type.

## 4. Architecture

```
guest phone ──iMessage──▶ Photon ──poll 2s──▶ ┐
guest phone ──HTTPS chat page──WebSocket────▶ │  Brain (FastAPI, Vultr/Fly, HTTPS)
                                              │  ├─ registry      {device_id → manifest, socket}
                                              │  ├─ leases        {guest_id → room, scopes, expires}
                                              │  ├─ agent loop    LLM tool-calling, tools = f(registry, lease)
                                              │  └─ bus           do/ok frames, 5 s timeout per action
device pages (phones, laptop display) ◀──WebSocket──┘
laptop room agent (python, osascript) ◀──WebSocket──┘
```

### Protocol (simplified — `ARCHITECTURE.md` §3–§5 is authoritative; build from there, not from here)

Device → Brain on connect: `{"type":"hello","id":"owen-phone","label":"Owen's phone","room":"7F3A","caps":{"light":{"description":...,"args":{...}},...}}`
Brain → Device: `{"type":"do","req":"r123","cap":"light","args":{"on":true},"deadline_ms":5000,"epoch":3}`
Device → Brain: `{"type":"ok","req":"r123","result":{...}}` or `{"type":"err","req":"r123","code":"PERMISSION|UNSUPPORTED|BUSY|FAILED|STALE","message":"..."}`
Brain → Display: `{"type":"state","room":{...},"devices":[...],"guests":[...],"log":[...]}` on every change.

### Lease

`POST /join {room_code, phone?}` → creates guest, lease (TTL 10 min default, scopes = all room caps), optional Photon assignment → returns `{guest_id, chat_url, imessage_number?}`.
`POST /leave {guest_id}` or guest says "leave" or TTL expiry → lease deleted **and the Photon assignment is released (`DELETE /v1/projects/{id}/platforms/imessage/assignments/{assignmentId}` — verified in their OpenAPI) so the 25‑seat free cap recycles**; agent responds to any command with: "You're no longer in Room 7F3A. Scan the code to rejoin."
Host console (display page, keyboard shortcut `R`): reset room — revoke all leases, rotate room code, re‑render QR.

### Agent loop

System prompt: you are Room {code}; here are the devices and what they can do right now; always act, then confirm in one sentence; if nothing can do it, say what's missing, never pretend. Tools generated per turn: one function per (device, capability) pair in the guest's scope, e.g. `owen_phone__light(on: bool)`. Multiple candidates (two phones can `speak`) → the model picks; we add a `label`/location hint so it can be sensible ("the phone nearest the window"). Each tool call → bus → 5 s timeout → result fed back. Model: fast function‑calling model (Claude Haiku / GPT‑4o‑mini / Grok fast); Grok Voice for TTS of the agent's reply on the laptop speaker (SpaceXAI eligibility by the letter).

## 5. Track declaration

- **Title:** Community Kitchen (accessibility: patients and guests who can't reach controls run the room by text/voice; no app barrier). Fallback framing: Cook Smarter.
- **Sponsored (≤3):** Photon (guest channel — verified), VEYZL (lease/scope/revocation audit on the repo — run their check on a PR, fix one finding), SpaceXAI (built in Cursor; **if we hold an xAI key, Grok is the agent's function‑calling model** so xAI is load‑bearing, not a bolt‑on; Grok Voice TTS as stretch on top).
- **Non‑sponsored:** SideShift, DubHacks NEXT, Vultr (host), GoDaddy (domain), Backboard if trivially added (guest preferences across rooms), MLH Commit form.

## 6. Who builds what

Two files, one per person, written so each person's agent can work from it alone: **[`jay.md`](jay.md)** and **[`owen.md`](owen.md)**. They are the source of truth for ownership; this section is the summary.

- **Jay — the Brain and the devices.** Everything that makes Tenant work: FastAPI Brain (registry, bus, leases, agent loop, web‑chat + Photon channels, host console, upload, log), the device page's JavaScript, the laptop `osascript` agent, hosting/HTTPS. Stretch: rules (`ARCHITECTURE.md` §6.5).
- **Owen — everything a human sees.** `join.html`, `guest.html`, `display.html`, the shared `tenant.css` (which also skins the device page), the `?mock=1` fixtures the pages are built against, slides, the 3‑minute video, Devpost, README story, and directing all three rehearsals. Stretch: VEYZL.

The seam is the wire protocol in `ARCHITECTURE.md` §3–§5. Rule for both: **a protocol change goes in `ARCHITECTURE.md` first, then a message, then code.** Neither edits the other's files.

### Timeline (we start at 4:20, not 3:30)
| When | Jay | Owen | Checkpoint |
|---|---|---|---|
| 4:20–6:00 | Boot, state, registry, bus + `FakeDevice`, device WS, device page JS → real torch | Mock fixtures, `shared.js`, `display.html` | **6:00:** phone joins, torch toggles via `host.do`; `display.html?mock=1` looks finished |
| 6:00–7:00 | Leases, `/join`, agent loop + tools, `/ws/guest` | `join.html`, `guest.html` against mock, iPhone + Android | 7:00: typed "turn on the light" from `guest.html` lights a real phone locally |
| 7:00–7:30 | Deploy HTTPS; phones over cellular | Wire pages to the real Brain | **7:30 KILL CHECK:** phone on cellular + public HTTPS + torch via chat. Fail → Brain + 2 phones + display only |
| 7:30–8:30 | Display WS, host reset, epoch/`STALE`, Photon channel | Device page skin; failure‑state copy | 8:30: rehearsal #1, Jay's phone as judge, both channels |
| 8:30–9:30 | Laptop agent: music, volume, say, `slides.next` | Slides; log rehearsal misses | 9:30: full 3‑min run‑through, timed |
| 9:30–10:30 | Hardening: two guests, reconnects, sleep/wake; **[STRETCH]** rules | **Devpost draft**; **[STRETCH]** VEYZL | **10:30 PM Devpost hard deadline** |
| 10:30–12:30 | Bug fixes; rate limit; Photon seat release verified | Hold‑to‑talk / Grok TTS **[STRETCH]**; polish | 12:30: rehearsal #2, stranger as judge, Android + iPhone |
| 12:30–2:00 | Bug fixes only | Bug fixes only | No new features after 12:30 |
| 2:00–7:00 | Sleep | Sleep | |
| 7:00–8:30 | Charge everything; pair speaker; tape QR | Record video; README; Devpost final | |
| 8:30–9:30 | Rehearsal #3; reset drill ×6 | Rehearsal #3 (directs) | |
| 10:00 | **Submit.** 10:20 HUB Ballroom. | | |

## 7. The 3‑minute demo (table)

0:00 Reset room (one key). Display shows: Room 7F3A, 5 devices, 0 guests, QR.
0:15 "Scan this." Judge scans → join page with two buttons: **Chat here** (no phone number) or **Text the room** (enters number → Messages opens with "join 7F3A" pre‑filled → they send). Display: guest appears. *Which button we point iPhone judges at is decided after rehearsal #1, based on how the ~4 s Photon round trip feels versus ~1.5 s on chat.*
0:40 Judge: "turn on a light." Phone torch on. Reply: "Light's on — Owen's phone."
0:55 Judge: "play something calm." Music through the speaker.
1:10 Judge: "what's in this room?" Reply lists devices; display highlights them.
1:25 Judge: "take a picture of me and show it." Phone B captures → laptop displays it.
1:45 Judge texts "leave." Display: guest removed, lease gone. Judge: "turn off the light." Reply: "You're no longer in Room 7F3A." Light stays on until *we* turn it off — ownership is the point.
2:10 One sentence on why: rooms you don't own — hotels, hospital beds, Airbnbs — without apps or accounts. Roadmap: devices that are already there (TV, lights, thermostat) join the same registry.
2:30 Q&A.

Rule: we never touch a keyboard during the demo except the reset key.

## 8. Risks → mitigations

1. **Ballroom noise** → text is the primary channel; voice is a bonus with a headset.
2. **Judge onboarding** → join page offers **Chat here** (default, zero PII, one tap) and **Text the room** (Photon; asks phone number). Most judges will tap Chat; Photon is the channel we *show* works, not one every judge must use. Rehearse on iPhone *and* Android; the Join button handles all permission prompts in one gesture.
3. **Phones sleep / Wi‑Fi drops** → Wake Lock, auto‑reconnect + re‑hello, phones plugged in, hotspot as backup network.
4. **Photon shared‑line rules** → agent never sends first; we only reply. If assignment fails, join page falls back to chat silently.
5. **Reset between judges** → `R` revokes all, rotates code, redraws QR in <1 s.
6. **Two guests at once** → last command wins; host override; agent mentions "another guest is here."
7. **Scope creep** → device list is locked (section 3). New ideas go in `IDEAS.md`, not the code.
8. **Secrets** → `.env` only, `.gitignore`d, keys scoped per project; VEYZL will check.

## 9. Kill conditions

- ~~3:55 PM: Photon smoke test fails → cut Photon, keep chat.~~ **Passed 4:11 PM.**
- 7:30 PM: no phone‑over‑HTTPS torch via chat → ship Brain + 2 phones + display only; drop music/camera.
- 10:00 PM: typed guest path unreliable → draft still goes in; spend the night on reliability, not features.

## 10. Assumptions (status)

- Verified: iOS 17.5+ Safari torch, camera (HTTPS), Wake Lock; Photon free tier = 25 shared assignments, agent can't text first; **Photon full round trip live (assign → inbound → reply 202, ~2 s inbound latency)**; DubHacks judging is at tables in the ballroom; rubric weights.
- Unverified: Photon reply actually *delivered* to the phone (202 = accepted, not delivered — check Messages); second phone number behaves identically; that we have an xAI key (if yes, Grok becomes the agent's model — see §5); Grok Voice TTS latency; Vultr credit code (ask MLH table; any HTTPS host works); Bluetooth speaker stays paired under load; **both demo phones are on iOS 17.5+** (torch requires it — check Settings → General → About now).

## 11. Merge with Project Morph (teammate's plan) — final

Morph V1/V2 and this plan describe the same core: capability registry, short‑lived lease, QR join, permission check before every action, revocation → denial, device substitution. Morph V2 was written without the inputs it lists as missing (team size, hours, hardware, venue). Supplying them — **2 people, ~13 build hours, 2 phones + laptop + Bluetooth speaker, table demo of 3 minutes** — makes the decisions below mechanical. Morph remains the vision doc; this file is tonight's build.

### Kept (already in both)
Registry of capabilities not devices · lease with TTL + scopes · QR identifies an invitation, lease is the grant · deterministic permission check immediately before dispatch · revocation produces a fixed denial · a new device joins without code changes · public display separate from operator view · no hidden manual cues during the demo · fail closed on physical actions.

### Adopted from Morph (now in this plan / `ARCHITECTURE.md`)
1. Falsifiable claim paragraph at the top of this file.
2. `lease_epoch` carried on every `do` frame; devices reject frames from an old epoch (`ARCHITECTURE.md` §3, §9).
3. Absolute state commands only (`light on=true`, not toggle); a timed‑out request has *unknown* outcome and is never blindly resent.
4. Runtime rules ("whenever `<event>`, do `<actions>`") as the single stretch feature, with triggers limited to events we already emit — no perception (§6 timeline, `ARCHITECTURE.md` §6.5).
5. Rehearsal #2 uses a person who has not seen the project as the judge, giving unseen commands.

### Cut from Morph, with the reason
| Cut | Reason |
|---|---|
| Camera perception: MediaPipe pose, hand‑raise, zone entry, clothing colour, tracking IDs, world‑state engine | No USB camera; Morph V2 itself rates this unverified (A1) and requires 40+ labelled live episodes. Not achievable in 13 hours alongside the core. |
| Musical chairs / elimination adjudication | Already cut in Morph V2. |
| Borrowed phone **video** via LiveKit (WebRTC, TURN, token revocation testing) | We have `camera.capture` (photo → display). Streaming adds a third transport and a vendor to debug; V2's A2 gate needs 10 join/remove cycles. |
| WLED lights, second smart light, projector, $200 hardware budget | Nothing to buy at 4 PM Saturday. Phone `flash(color)` + laptop brightness are the lights; the laptop screen is the projector. If a WLED strip turns up, it joins as a device page instance — no plan change. |
| Six‑component architecture (perception, world state, situational agent, capability planner, execution engine as separate pieces) | Collapses to registry + agent loop + bus once perception is gone. |
| Independent evaluation packet: 60 positive / 60 negative episodes, Wilson intervals, 30 permission sequences, 5‑person comprehension study | Right instinct, wrong scale. Replaced by three timed rehearsals (one with a stranger) and the kill checks in §9. |
| Hand‑authored vs language‑generated rule comparison | Only meaningful with the rules stretch; if rules ship we show one unseen rule working, not a matched study. |
| React + TypeScript + Vite, SQLite, Home Assistant, OpenAI Responses API as fixed choices | Vanilla JS with no build step; in‑memory state with JSONL log; no HA devices exist here; model is whichever fast function‑calling key we hold. |
| Wake‑word voice activation | Hold‑to‑talk is the fallback in both plans; wake word is cut outright. |
| 48‑hour / 4‑person schedule and the two‑person variant (loop by hour 12, core by hour 20) | Our window ends at hour ~18 wall‑clock including sleep. Replaced by §6. |
| Three‑tier revocation timing (request received / locally enforced / cleanup observed) with measured intervals | Single process, single room: revocation is one dict delete and the next tool call is denied. Keep the *principle* (check at dispatch); skip the measurement apparatus. |
| Thermostat, curtains, fans, PTZ cameras, DMX fixtures, mmWave, haptics, fabrication | Future‑vision list in Morph; none present. |

### Tiebreaker for anything not listed
Does it survive the 7:30 kill check **and** fit the 3‑minute table demo? If either is no, it is deferred with a written unlock condition in `IDEAS.md`, not built.
