# Devpost draft — Tenant

Paste-ready copy for the **mandatory 10:30 PM Saturday draft**. Every claim below is tied to evidence in `notes/jay.md` / `notes/owen.md` as of 18:45; the "Claims register" at the bottom says what to cut if something doesn't land by Sunday.

Fill the `[brackets]` before submitting. Nothing else needs editing tonight.

---

## 0. What Devpost requires at 10:30 PM (from the Hacker Guide + Devpost "What to Submit")

- [ ] Project created on https://dubhacks-2026.devpost.com/
- [ ] **Every team member added as a contributor, with their Discord username** — the guide says a draft without this blocks Sunday judging
- [ ] **Tracks declared** (exactly one title track; up to 3 sponsored side tracks; any non-sponsored)
- [ ] Overview text (section 2 below) — a short version is fine for the draft
- [ ] Video: **not required for the draft**, required for the 10:00 AM Sunday final. "Teams who do not submit a video will not be allowed to judge."
- [ ] Code link: public GitHub repo — `[https://github.com/owen-tsao/tenant]` (confirm it is public before 10:00 AM)

---

## 1. Name and tagline

**Project name:** Tenant

**Tagline (pick one, ≤ 60 characters):**

- The room has a brain. Scan it, talk to it, leave — it forgets you.
- Borrow a room's devices by texting it. No app. No account.
- Temporary control of devices you don't own, from the phone you do.

---

## 2. About the project

### Inspiration

One of us spent a week this summer visiting someone in a hospital room. The light switch was on the wall by the door. The TV remote had been borrowed from a different room and only half the buttons worked. Every evening, the same small negotiation: wait for a nurse to walk past, or get up when you shouldn't.

Then you check into a hotel and it's the same thing with better furniture. A smart TV you can't cast to. A speaker that wants the owner's account. A thermostat with an app you'll install once, for two nights, and never open again.

The devices are right there. You just aren't allowed to talk to them. So we built a way to borrow a room.

### What it does

You walk up to a room and there's a card on the table with a QR code. Scan it and you're in a chat with the room. No app, no account, nobody asked for your email. You type what you want the way you'd text a friend: "turn on a light," "play something calm," "say hello." Something in the room does it. A phone's flashlight comes on. Music starts from the laptop. The laptop says hello out loud. The room texts back one sentence about what it just did.

The part we care about most is what happens when you're done. Your access is a lease, not an account: ten minutes and a specific set of devices. When you text "leave," or your time runs out, or the host hits one key to reset the room, you're out. Ask for the light again and the room politely tells you you're no longer here, scan the card to come back. The light stays however you left it. It was never yours to begin with.

The host has a screen that reads like a story, not a log: who's in the room, what's online, and what happened in plain sentences ("Owen's phone turned its flashlight on").

If you'd rather text than use a web page, the room has a real phone number. Give the join page your number and the room shows up in Messages like any other contact. Same room, same conversation, same ten minutes.

### How we built it

Two people, one Saturday, two iPhones, a MacBook and whatever speaker was nearby.

- The Brain is a small Python server (FastAPI, WebSockets). Every device connects and announces what it can do: "I'm Owen's phone, I have a flashlight and I can talk." The Brain keeps that registry and the list of who currently holds a lease, passes commands down to devices, and waits for them to say done. Adding a device means plugging it in and letting it introduce itself. No code changes.
- The agent is one conversation, running on OpenAI Codex signed in locally on the host's Mac. When it wants to touch a device, the request goes through the Brain, and the Brain checks your lease at that moment, not when you joined or when you typed. A lease that ended a second ago is refused.
- The devices are web pages. On an iPhone, Safari can control the flashlight through the camera's torch setting over HTTPS with permission, so we keep a page open that stays awake and listens. On the Mac, a small Python script drives Music, the volume and the voice through AppleScript.
- Two ways in: a chat page, and iMessage through Photon 2.0. Photon gives the room a number and delivers the texts; our agent does the thinking either way.
- The look is deliberately plain. Dark plum, one pink that means "live," no boxes, no IDs, no code on any screen a guest or judge sees. Just sentences.

### Challenges we ran into

- The hard part isn't making it work, it's making it stop. What if someone texts "leave" while the room is halfway through doing what they asked? We stamp every command with the lease's version number and devices ignore anything stale. If a command times out, we don't know what happened, so we say so, and we never quietly retry it on another device.
- Phones do not want to be demo hardware. They sleep, they drop Wi-Fi, and Safari changes its mind about the flashlight between iOS versions. We needed Wake Lock, auto-reconnect, and a rule for when the same phone shows up twice (the original wins, the newcomer is told to try again) before we got three clean runs in a row.
- "Accepted" is not "delivered." Photon's API says yes long before a text appears on a phone. We treat those as two different facts and only claim the one we've watched happen.

### Accomplishments we're proud of

- A stranger scans a code and a real flashlight in front of them turns on, within seconds, with nothing installed.
- The lease really ends. We ran a full ten-minute expiry, a "leave," and a host reset. Each time, the very next request was refused.
- Reset is one key. Every lease ends, lights go off, music stops, the room code rotates so a photo of the old QR is useless, and the log clears, all in about a second.
- The host screen reads like a sentence.

### What we learned

Temporary is harder than permanent. Almost every bug lived at the boundary: the command already on its way when the lease ended, the device reconnecting under an old identity. Designing for "the room forgets you" gave us two rules we'd now use anywhere. Every action is absolute (light on, never toggle), and every permission is checked at the moment of action, not before.

### What's next

Two phones and a laptop were what we had at 4 PM on a Saturday. The Brain doesn't care. A hotel TV, a smart bulb, or the controls on a hospital bed would join the same way and live under the same lease. After that: voice (hold to talk, the room talks back), letting a guest lend their own camera to the room, and letting a host set rules in plain language: "whenever someone joins, dim the lights."

---

## 3. Built with (Devpost tags)

`python` `fastapi` `websockets` `uvicorn` `pydantic` `httpx` `javascript` `html` `css` `openai-codex` `photon` `imessage` `applescript` `ios-safari` `qrcode` `cursor` `veyzl`

---

## 4. Tracks to declare

Verified against the Hacker Guide track pages on 10/17 18:45.

### Title track (exactly one)

**Community Kitchen** — "accessibility and assistive tech … solutions that make everyday life more connected, equitable." The pitch for the judge: *the person in the hospital bed who can't reach the light switch, or the guest who can't operate an unfamiliar remote, controls the room by text — the same way they text a friend.*

> **Decided 21:05: Community Kitchen.** The story opens on a hospital room and the demo's framing beat is a patient who can't reach the switch, so the copy, deck and video all already pitch accessibility. Cook Smarter was the alternative ("AI agents, automation") and would have required rewriting the opener; it is also the more crowded track. Say the "who is this for" answer out loud to the judge the same way the Inspiration paragraph does.

### Sponsored side tracks (max 3)

| Track | Declare? | Why / status |
|---|---|---|
| **Photon** | Yes | Requirement is "built on Photon 2.0 and live on at least one Photon channel." Adapter is deployed (`brain/channels/photon.py`); first real phone round-trip is **still pending** per Jay 18:21. Judged in person. **Prize (verified on the Track Prizes page):** winner $400 cash + $300 credits + fast-track to Photon's final interview round; runner-up $200 + $100 credits. Separate Best Voice Agent ($300) requires phone calls on an SMS number via SIP — not what we have; don't claim it. |
| **VEYZL** | Yes — declare now, drop Sunday if not done | $500 cash + lifetime VEYZL Pro per member (side-tracks page; prizes page says "coming soon"). Needs: repo connected, audit check visible on a PR, one real finding fixed with a before/after. Judged in person. ~90 min of work; PR1 already exists. |
| **SpaceXAI** | Yes — declare now; keep only if Grok Voice is wired | **Prize (verified on the Track Prizes page):** winning team gets a Cursor mechanical keyboard each **and their names shared directly with SpaceXAI's recruiting team**; everyone who submits enters the Owala raffle. **Gate:** project "must also use the Grok Imagine or Voice API." Cheapest honest path: Grok Voice as the room's spoken voice, replacing macOS `say` in `brain/core/conversation_speech.py`. Kill condition: no xAI key. Theme is space data, so we're a weak fit even when qualified — treat as a lottery ticket, not a plan. |

### Non-sponsored side tracks (any number)

| Track | Declare? | Why / status |
|---|---|---|
| **DubHacks NEXT** | Yes | Judged in person; the "rooms you don't own" roadmap is the startup story. |
| **SideShift** | Yes | Judged in person; nothing to build. |
| Vultr / GoDaddy / Backboard / MongoDB / Gemini | **No** | No evidence we use any of them. The Brain is reached through a tunnel, not a Vultr box; no domain registered; no Backboard. Declaring them costs credibility with the main-track judge and wins nothing. |
| MLH Commit Fellowship | Optional | Needs a separate form; only if someone wants the founder sprint. |

---

## 5. Links to fill in

- GitHub: `[https://github.com/owen-tsao/tenant]` — must be **public** before 10:00 AM
- Live join page (for judges reading Devpost later): `[https://<host>/j/<code>]` — optional; the code rotates on reset so this may be dead by the time anyone clicks it. Consider leaving it out.
- Video: `[YouTube/Drive link]` — **required for the 10:00 AM final**, not the draft

---

## 6. Claims register — what this page asserts and what backs it

Edit the copy, not the evidence. If a row's evidence is still "pending" at Sunday 9:00 AM, cut the sentence it backs.

| Claim in the copy | Evidence | Status 18:45 |
|---|---|---|
| Scan → chat → real iPhone flashlight on/off | Jay 17:25, 17:31: three fresh guest cycles, physically observed | Verified |
| Music play/pause, volume, Mac speech | Jay 17:23, 17:25: heard; volume 63→68→63 restored | Verified |
| "Leave" → next command denied | Jay 17:23/17:25 | Verified |
| 600 s expiry → denied | Jay 17:31: "denied in 14 ms with no command" | Verified |
| Host reset: lights off, music stops, code rotates, old QR rejected, < 1 s | Jay 17:31: two real resets observed | Verified (sub-second timing not separately measured — soften to "in about a second" if asked) |
| Duplicate connection → original wins, newcomer retried | Jay 17:43 (`cc2c2ae`), tests pass; **not physically retested** | Code-verified only |
| Photon iMessage into the same conversation | Jay 18:21: deployed `d8fef91`, 37 tests; **no real phone message yet** | **Pending** — if not delivered on a phone by Sunday, change the Photon paragraph to "We integrated Photon 2.0 as a second channel; see the repo" and do not show it in the video |
| Agent = OpenAI Codex running locally | `brain/core/room_conversation.py` docstring | Verified |
| Display shows guests, devices, sentence log | `web/display.html` against mock; live backend feed confirmed by Jay 17:23 | Verified |
| Photo → screen, scenes, rules | — | **Not built.** Not claimed anywhere above except "What's next". Keep it that way. |
| Adding a device needs no code change | Registry design; a second iPhone was enrolled by QR (Jay 17:24) | Verified for phones; untested for anything else |
