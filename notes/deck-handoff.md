# Deck handoff — Tenant, DubHacks '26

Paste this whole file into the slide‑deck chat. It is the single source of truth for the deck's job, look, and content. Repo: `/Users/owentsao/dubhacks2` (GitHub `owen-tsao/tenant`). Project pitch and demo script: `PLAN.md` §1 and §7. Decisions behind this doc: `notes/owen.md` 17:30 entry.

## 1. The deck's job (read this first)

Three people touch Tenant and they never share a screen:

- **Judge / guest** → watches **this deck** for ~60 seconds, scans the QR on its **last slide**, then lives in **Messages** (texts the room). They never operate our screen.
- **Us (host)** → the web app: a setup flow that produces the printable QR, and the **display** (`web/display.html`), our operational screen that shows what is happening in the room.
- **Our phones** → props that flash, light up, speak.

So the deck **is the guest's onboarding**. It replaces a landing page. It must do exactly three things: say what Tenant is, show why a *lease* matters, and end on a QR that holds on screen while a judge scans. After the last slide we switch the laptop to `display.html`, which uses the same colours below, so the handoff reads as one product.

Timing: **≈60 seconds presented**, 5 slides, hard stop on the QR. Build with the `motion-deck` skill (slides as React components, one navigation hook, Motion variants, shared easing).

## 2. Theme — exact tokens (copied from `web/tenant.css`)

Dark plum + one pink. Not black. Not a gradient. Pink is the *only* colour and it means "live / go".

```css
--bg:      #1a1523;   /* floor */
--surface: #211b2c;   /* panels */
--inset:   #2a2237;   /* inputs, inner wells */
--hover:   #31283f;

--line:    rgba(240,168,224,.14);  /* hairline inside a region */
--line-2:  rgba(240,168,224,.32);  /* edge between regions — only two weights exist */

--fg:      #f4eef7;   /* text */
--muted:   #b9a9c4;
--faint:   #7d6d8a;   /* eyebrows, timestamps */

--accent:  #f0a8e0;   /* pink. The one colour. */
```

Rules that follow from the tokens:

- Pink is used for: a solid pink block or pill with **plum text** (`#1a1523` on `#f0a8e0`), the dither motif, a 6 px live dot, and the newest/active thing. Never as a tint, outline on quiet elements, or on body text.
- Inverted emphasis (a `--fg` block with `--bg` text) is for "denied / stopped". Use it once in the deck, on the "leave" beat.
- Exactly two line weights. No shadows, no glass, no rounded framed boxes (Owen: "the right boxes look bad"). Regions separate with hairlines and tracked labels.
- Type: **Inter** (400/500/600) for everything; **mono** (`ui-monospace, "SF Mono", Menlo`) with `font-variant-numeric: tabular-nums` only for the room code, the countdown, timestamps, and counts that tick. Eyebrows 11 px uppercase, `.08em` tracking, `--faint`, top‑left of a region.
- Texture: **one** motif — a dithered pinwheel/radial burst of pink squares on plum (reference: the pink "Systems that run reliably" cards). Squares ≈6 px, density falls off radially, drawn with canvas or inline SVG. It appears behind the title and behind the QR; never behind text that must be read from 2 m. `web/display.html` already draws one in the empty guest region — copy its generator rather than inventing a second look.

### What the inspiration images are for

Paths are in `/Users/owentsao/.cursor/projects/Users-owentsao-dubhacks2/assets/`. Take the named thing, ignore the rest.

| Image | Take | Ignore |
|---|---|---|
| `image-4dacdaf5…` (pink pinwheel hero), `image-88065df9…` (three pink cards) | The whole look: plum, one pink, dither motif, pill buttons | — |
| `image-d226a043…`, `image-30897104…`, `image-2e330138…` (white dither figures on black) | How a dithered image sits with one short line of type; the tiny two‑square mark | The black floor — ours is plum |
| `image-fd79271c…`, `image-6cd10e85…` (archon, pink on black; blue ASCII card) | Pink halftone over a photo as a slide background; big numeral on a solid block | Green, blue |
| `image-a461d10b…` (Reboot), `image-2898fe44…` (Launch), `image-31082266…` (Shopify) | Headline in two weights over a dot‑field; type that is small and confident | White floors |
| `image-1959c9f6…` (NYC Exchange dot donut), `image-17fdb532…` (Craft, Engineered pixel field) | Pixel fields as data, not decoration | Multi‑colour |
| `image-6b9b2bc9…` (Dither Boy), `image-57fbc6de…` (Ironclad), `image-26a97f44…` (BCI), `image-00cadd8f…` (Claura) | Serif display + grotesque body pairing, if a single italic word helps the title | Gradients, pastel, noise fills — declined |

## 3. The five slides (60 s)

Each slide: eyebrow top‑left (mono, faint), one headline, at most one supporting line, one visual. Text rises out of a clipped line; numbers tick; SVG paths draw. One easing everywhere.

| # | Time | Eyebrow | Headline | Visual / motion | Speaker line |
|---|---|---|---|---|---|
| 1 | 0–8 s | `TENANT` | **Borrow the room.** | Dither pinwheel behind, slowly turning (≤1 rpm). Pink pill: "DubHacks '26". | "Tenant lets a guest use a room's devices by texting it — no app, no account, and it forgets them when they leave." |
| 2 | 8–20 s | `THE PROBLEM` | Rooms you don't own still want an app. | Three mono labels count in: `HOTEL ROOM` · `HOSPITAL BED` · `AIRBNB`. Under each, a faint line: "download, sign in, pair, forget to sign out." | "Every room you don't own has devices you can't use without an app you'll never open again." |
| 3 | 20–34 s | `WHAT HAPPENS` | Scan. Text. Done. | Three steps draw left→right as a hairline with pink dots: **Scan** → **Text "turn on a light"** → **The light turns on.** Last dot pulses pink. | "You scan a card, text the room like a person, and the room's devices do it." |
| 4 | 34–48 s | `THE LEASE` | Guest 1 can use **3 devices** for **10:00**. | A solid pink block with plum text, mono countdown ticks down 10:00 → 9:57. Then the beat: guest texts "leave" → the block inverts to `--fg` with `--bg` text: **Lease ended. 0 devices.** | "Access is a lease, not an account. Leave, and it's gone — the room's owner still owns the room." |
| 5 | 48–60 s + hold | `ROOM 7F3A` | Text the room. | QR large and centred (≥ 320 px, high contrast: pink modules on plum **only if** scan‑tested; otherwise `--fg` on `--bg`). Under it, mono: `join 7F3A`, and one line in `--muted`: "Scan, or text **join 7F3A** to the number." Dither motif faint behind, never over the QR. | "Scan this." (Then we switch the laptop to the display.) |

The QR encodes the join URL for the room — `https://<host>/j/7F3A` — read from one constant so we can swap the host and code on the day. The room code is rotated on reset, so make the code and QR a prop, not hard‑coded text. The real host URL comes from Jay when the Brain is deployed; use `http://127.0.0.1:8899/join.html?mock=1` as the placeholder.

Slide 5 also needs a keyboard shortcut (`D`) that opens `display.html` in the same window, so the handoff is one key.

## 4. Components you may pull from Owen's component library

`~/.cursor/skills/component-library/SKILL.md`. Take the technique, retoken to the palette above. Do not import across projects; copy.

- **`dither-donut-chart`** (prompt‑only) — the jittered‑dither‑squares canvas technique. Use it for the pinwheel motif and slide 3's dot field. Needs you to write `useCanvasSetup` (ResizeObserver + visibility + reduced‑motion); the prompt doesn't include it.
- **`loading-state`** (shipped in clad‑core) — 3×3 pixel‑grid loader with a mono elapsed timer. Reuse the pixel wavefront as the "room is listening" tick on slide 3 and the timer pattern for slide 4's countdown. Anchor the timer to a fixed start (`since`), not mount time — Owen caught the reset bug before.
- **`animated-slideshow`** — the keyed‑clone wipe pattern is how slide transitions should feel if you want a wipe; the lesson is "mount a fresh clone over settled pixels, never unmount mid‑flight". `clip-path` hidden state in `%`, not `px`.
- **`wizard-steps`** rail — if slide 3's three steps want a rail: 28 px tiles, spring on the active tile, connectors `scaleX` in. Retoken stone → plum/pink.
- **`cta-button`** — the pill: label only, no ornament glyphs.

Not to use: liquid‑metal, mesh‑gradient, thread hero, bento, neobrutalism. They are another product's voice.

## 5. Constraints

- No new dependency without Owen's OK in the deck chat. The QR is the one you'll need — ask before adding (`qrcode` or similar); a Canvas‑drawn QR is fine too.
- 1440×900 laptop, presented from Chrome full‑screen. Also check 1920×1080 for the ballroom screen in case.
- Reduced motion: every animation collapses to a fade.
- No sound from the deck — the room speaker is a demo device and must stay silent until a guest asks.
- Nothing code‑like on a slide except the room code and `join 7F3A`. No IDs, no epochs, no "WebSocket".
- Numbers on slides must be true on the day: 3 devices, 10‑minute lease, room `7F3A` (default mock code). If the device count changes, the deck changes.

## 6. Hand‑back

When the deck is in a reviewable state, drop a line in `notes/owen.md` with the route to open and screenshots of slides 1, 4 and 5 under `notes/shots/deck-*.png`. Owen reviews it against the display side by side.
