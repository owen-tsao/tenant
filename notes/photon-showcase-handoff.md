# Photon showcase video: what to build and what to film

For Jay. Goal: a 60–90 s vertical video for Photon's "Make Your Own Muse" contest
(deadline Oct 23) where every beat is a native iMessage behaviour. Build on
`codex/tenant-core-integration`; the only file that changes is
`brain/channels/photon.py`, plus a small lease-timer hook.

## Read this first: what iMessage can actually do over the 2.0 REST API

I re-read the live OpenAPI schema (`https://api.photon.codes/openapi.json`,
fetched Oct 21). The outbound content union for iMessage
(`ImessageMessageContent`, used by `AcceptedImessageMessage` /
`DispatchedImessageMessage` / `DeliveredImessageMessage`) is:

| `content.type` | On iMessage (2.0 REST) | What it is |
| --- | --- | --- |
| `text` | yes (what we send today) | plain bubble |
| `space.typing.update` | yes | the three dots |
| `message.read` | yes | "Read" under the guest's bubble |
| `attachment` | yes ("text and image messages" per the send endpoint) | photo in the thread |
| `group` | yes | several parts delivered as one visual group (e.g. photo + caption) |
| `reaction` | **not in the iMessage union** (listed as "reserved") | tapback 👍 / 👎 |
| `text.update` | **not in the iMessage union** | editing a sent message |
| `voice` | **not in the iMessage union** | audio-waveform bubble |
| `poll` / `poll.vote` | **not in the iMessage union** | polls |

The reserved types are in the generic `SendContent` schema, so the server will
*parse* them. Whether it then returns `422 UNSUPPORTED_CONTENT` for an iMessage
space, or quietly accepts and drops, or actually delivers, is **unverified** —
I have no Photon credentials on this machine. Tapbacks, edits, voice and polls
are available in Photon's Stable `spectrum-ts` SDK (the "advanced iMessage kit"),
not in the 2.0 REST API our Brain uses. The Beta "Messaging" docs page literally
says "This section is being rewritten from the ground up", so the schema is the
only authoritative source right now.

**This corrects what I told Owen earlier.** I said reaction/edit/voice were
verified against the spec; they are not supported for iMessage in the spec.
Sorry. The plan below is rebuilt around what *is* supported, with the reserved
types as a 15-minute gamble, not a dependency.

### Kill check (do this before anything else, ~15 min)

With `PHOTON_PROJECT_ID` / `PHOTON_API_KEY` exported and a live assignment
(text the shared line from your phone first so the peer is "active"):

```python
# in spikes/photon/test.py style: same call() helper, real spaceId/senderId
# from the inbound message you just received, parentMessageId = that message id
body = {"spaceId": space_id, "senderId": agent_user_id, "parentMessageId": inbound_id,
        "content": {"type": "reaction", "reaction": "like", "action": "add"}}
```

- `202` **and a 👍 appears on your bubble** → reaction works; promote item 1 below
  to "build" and try `text.update` the same way (edit the message you just
  sent, `parentMessageId` = its id).
- `202` but nothing appears, or `422 UNSUPPORTED_CONTENT` → dead; use the
  fallbacks below and do not spend more time on it.

Do not test `voice` or `poll`; even if they worked, polls need iOS 26 on the
guest phone and a voice bubble needs an m4a pipeline we have not built.

## Build list, in order of value per hour

Everything goes through the one endpoint we already call,
`POST /v1/projects/{id}/messages`, with `spaceId` + `senderId` from the inbound
message (the poller already keeps them in `bindings.space_id` /
`bindings.agent_id`) and an `Idempotency-Key`. Add one generic method to
`PhotonClient`:

```python
async def send_content(self, space_id, sender_id, content, key, *, parent_message_id=None):
    body = {'spaceId': space_id, 'senderId': sender_id, 'content': content}
    if parent_message_id:
        body['parentMessageId'] = parent_message_id
    return await self._request('POST', 'messages', expected=(202,), json=body,
                               headers={'Idempotency-Key': key})
```

Keep the existing rule: a 202 is acceptance, never delivery; no retries.

### 1. Typing while the room thinks (~1 h) — do this first

What the viewer sees: three dots appear the moment they send, and stay until the
reply lands. This hides the 11–51 s turn latency, which is the single biggest
thing wrong with the current thread.

Where: `PhotonChannel.process_one`, around `await self.core.agent.turn(...)`.

```python
await self.client.send_content(space_id, sender_id,
    {'type': 'space.typing.update', 'typing': True}, 'tenant-typing-on-' + message_id)
try:
    frames = await self.core.agent.turn(guest_id, text)
finally:
    await self.client.send_content(space_id, sender_id,
        {'type': 'space.typing.update', 'typing': False}, 'tenant-typing-off-' + message_id)
```

Two details:

- The schema says `typing: true` "starts **or refreshes** typing". Apple's
  indicator expires on its own (roughly a minute). Our turns can run 51 s, so
  run `turn()` as a task and re-send `typing: true` every ~25 s while it is
  pending. Use a fresh key each refresh (`tenant-typing-on-{message_id}-{n}`).
- Send `typing: false` *before* the reply text, not after, or the dots can
  briefly overlap the bubble. Wrap the typing calls in `suppress(PhotonError)`;
  a failed typing hint must never block the reply.

### 2. Read receipt the instant the text arrives (~20 min)

What the viewer sees: "Read" under their bubble immediately, before the dots.

Two ways in the schema; prefer the dedicated endpoint, it is purpose-built for
inbound messages:

```python
async def mark_read(self, message_id, key):
    return await self._request('POST', 'messages/' + quote(message_id, safe='') + '/read',
                               expected=(202,), headers={'Idempotency-Key': key})
```

Call it in `process_one` right after the lease check passes, key
`tenant-read-{message_id}`. The schema notes "privacy settings may suppress
remote visibility" — on the guest's phone, Read Receipts must be on for the
conversation (Messages → the contact → Send Read Receipts). Check this on the
filming phone before the shoot.

Alternative: `content: {"type": "message.read"}` through `send_content` with
`parentMessageId` = inbound id. Same effect; use whichever returns 202 first.

### 3. The lease countdown, rendered in the thread (~2 h)

This is the product thesis on screen. `Leases.active_ttl` is 600 s, so a lease
is exactly 10:00.

Preferred (only if the kill check passed for `text.update`): send the welcome
("You have 10:00 in Room 212 — a light, a speaker, a screen."), remember its
message id, then at 5:00 / 1:00 / 0:00 send
`{"type": "text.update", "format": "plain", "text": "..."}` with
`parentMessageId` = the welcome id. Apple allows 5 edits within 15 min of send;
three edits inside 10 min fits. The final edit: "Your time's up. The room has
forgotten you."

Fallback (supported for sure): send **new** texts at the milestones instead.
Keep them to one line each so the thread does not fill up:

- 5:00 → "5:00 left in Room 212."
- 1:00 → "One minute."
- 0:00 (or on `leave`) → "Your time's up. The room has forgotten you."

Where: hook `Leases.on_change` (already a constructor arg in
`brain/core/leases.py`) or a small `asyncio` timer started in
`PhotonChannel` when a binding goes `active`. Gate every send on
`self.core.leases.current(guest_id) is lease`, same as replies; the 0:00 message
is the one exception — it is sent *because* the lease ended, so send it from the
revoke/expire path using the stored `space_id` / `agent_id` before the binding is
released. The shared line only sends to a peer "who has messaged it since that
Assignment", so send the expiry text *before* `maintain()` releases the seat.

### 4. The tapback ack (~1 h, only if the kill check passed)

What the viewer sees: they text "lights", a 👍 lands on *their* bubble as the
lamp comes on. No reply text.

`{"type": "reaction", "reaction": "like", "action": "add"}` with
`parentMessageId` = inbound id, on bus `ok`; 👎 (`"dislike"`) on `err` or a
lease denial. Reaction string values are free-form in the schema (`minLength: 1`);
if `like` does not render, try `thumbs_up`, `love`, `heart`, `laugh`,
`emphasize`, `question`.

Fallback if dead: keep the reply text but make successful device actions
*terse*. "Light's on." / "Done." / "Playing." The agent's short confirmations plus
typing dots read almost as crisp on camera.

### 5. Photo of the room in the thread (half day, optional)

The photo flow exists (accepted Sun 11:09). What is missing is the upload:

1. `POST /v1/projects/{id}/attachments` — `multipart/related` with **exactly two
   parts**: a JSON part `{"contentType": "image/jpeg", "sizeBytes": N,
   "filename": "room.jpg"}`, then the raw bytes. Required headers:
   `content-length`, `content-type` (the multipart type), `idempotency-key`.
   Returns an `Attachment` with `id` (`pho_att_…`); `201` on first upload,
   `200` on an idempotent replay.
2. `send_content(..., {"type": "attachment", "attachmentId": att_id}, key)`.
   A `409 ATTACHMENT_NOT_READY` means the upload is still processing — wait a
   second and resend with the same key; do not re-upload.

`httpx` does not build `multipart/related` for you; assemble the body by hand
(boundary, two parts, CRLFs). Treat this whole item as **unverified** until a
real image lands on the phone; if the upload fights you for more than an hour,
drop it. The video is fine without it.

### Skip

- **Voice bubble** — not in the iMessage union; also needs `say -o` → m4a →
  upload. Skip.
- **Polls** — not in the union, and need iOS 26 on the guest phone. Skip.
- **Message effects (lasers/confetti)** — Stable SDK only, and shared lines
  reject them. Skip.

### Already built, zero code

- "play something with a beat" → phone torch pulses in time, orb on the TV.
  You confirmed this physically. Film it in a dark room.

## The cut (60–90 s, vertical, filmed dark, phone screen-recorded + room camera)

1. QR card on the TV → tap **Text the room** → Messages opens pre-filled
   (`Hello Tenant`) → send.
2. "Read" appears → dots → welcome: "You have 10:00 in Room 212 — a light, a
   speaker, a screen."
3. "lights" → dots → (👍 on the bubble if reactions work, otherwise "Light's
   on.") → lamp on, cut to the room.
4. "play something with a beat" → dots → torch pulses in time, orb on the TV.
5. *(only if item 5 landed)* "send me a picture of the room" → photo arrives.
6. "leave" → "Your time's up. The room has forgotten you." (as the edited
   welcome bubble if edits work, otherwise as a new line).
7. "turn off the light" → (👎 or) "You're no longer in Room 212." Nothing
   happens in the room.
8. End card.

Each beat is something iMessage users already recognise — read receipt, typing,
a message that changes, a tapback — which is what Photon's judges and audience
respond to. If a beat is not working on the day, cut it; do not fake it.

## Schedule

- Wed: kill check → items 1, 2, 3 (fallback variant if needed) → item 4 only
  if the check passed.
- Wed night: film. Read Receipts on, Do Not Disturb on, brightness up, dark room.
- Thu morning: edit, post, quote our contest entry.

## What I did not verify

- Any of the above against a live line (no credentials on my machine). The
  kill check is the one call that settles the reaction/edit question.
- That `message.read` is visible on the guest's phone when their Read Receipts
  are off (the schema warns it may be suppressed).
- The exact `multipart/related` body the attachment endpoint expects; the
  schema describes it, I have not sent one.
- How long Apple shows a typing indicator before it times out on its own; the
  ~25 s refresh is a safe guess, not a measured number.
