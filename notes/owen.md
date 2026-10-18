# Owen — decision log

Append‑only. One line per entry, timestamped. Only three kinds of entry belong here:

1. **Deviation** — I did something the plan or spec didn't say.
2. **Interface** — I need a frame, field, route, or state changed (and I've edited `ARCHITECTURE.md`).
3. **Blocker** — I'm stuck on something that needs Jay.

If an entry is longer than two sentences it belongs in `ARCHITECTURE.md`, not here. Jay reads the last few lines at each check‑in (6:00, 7:00, 7:30, 8:30, 9:30, 10:15, 12:30).

---

- 16:24 — Log created. Starting on `web/mock/state.json` → `web/shared.js` → `web/display.html`.
- 16:45 — Reply to Jay 16:27 feedback request — **Agreed on both.** (1) `guest_id` public / `guest_token` private: now in `ARCHITECTURE.md` §5.1 — token returned by `POST /join`, carried in the `chat_url` fragment, sent as `?token=` on `/ws/guest`, mismatch closes 4401. My pages will do exactly that. (2) Alternatives offered in plain `assistant` text, no new frame — now in §5.2. Nothing else in the shared frames changed.
- 16:45 — Re Jay 16:38 "no model API key" — **Owen to resolve.** Codex CLI via ChatGPT login is not a function‑calling API; the agent loop needs one. Owen is checking which keys he holds (xAI / Anthropic / OpenAI) and will hand one to Jay in person. Until then Jay's `FakeDevice` + stubbed LLM path is the right thing to build against.
- 16:45 — Re Jay 16:27 photo gate — Acknowledged. Demo script §7 keeps the photo beat at 1:25 as *aspirational*; if the gate isn't open by the 9:30 run‑through, Owen cuts the beat from the script, not the other way round.
- 16:58 — Progress — `web/mock/state.json`, `web/mock/chat.json`, `web/shared.js`, `web/tenant.css`, `web/display.html`, `web/join.html`, `web/guest.html` all render against the mock (`?mock=1`). Screenshots verified in Cursor's browser at 1024 and 390 px.
- 16:58 — Interface (request, not a change) — The display renders `log[].text` verbatim as a sentence a judge reads. Please have the Brain emit sentences ("Owen's phone turned its flashlight on.") rather than `owen-phone.light(on) ✓`. The §4 example text should be updated to match; I'll do that edit if you agree.
- 16:58 — Interface (addition, in `shared.js`, not yet in spec) — `guest.html` optionally reads `{"type":"lease","expires_in":N}` and `{"type":"lease","state":"released"}` frames on `/ws/guest` to show the countdown and the ended banner. If you'd rather not add them, the page still works without (no countdown; denial shows via the fixed assistant text). Also `/ws/display` is opened with `?token=` when a host token is stored — ignore it if you don't need it.
- 16:58 — Deviation — QR code on the display is a **placeholder pattern** until we decide on a vendored QR library (~15 KB MIT `qrcode-generator`; `display.html` already calls `window.qrcode` if present). Needs Owen's OK on the dependency.
- 16:55 — UI standards for every Tenant page (Owen's verified past feedback; applies to Jay's `device.html` skin too): surfaces fill the viewport even when empty — no blank columns; columns that sit side by side end on the same line, lists scroll inside; density from structure (hairline tables with real columns, 13px, `px-4 py-3`), never bento, never bare text lists; no terminal strings, IDs, epochs, or code on a judge‑facing surface — sentences only, room code is the only mono; exactly two line weights (inside‑surface hairline, between‑surface edge); custom‑styled form controls, never the OS default; fixed‑height headers so nothing jumps; one‑line truncated titles.
- 17:30 — **Deviation / page map.** Big revision after Owen reviewed the first display. (1) Theme is now dark plum + pink (`#1a1523` / `#f0a8e0`), not black/amber; device page stays black. (2) The display drops the QR entirely — it's *our* operational screen; the QR lives on a printed card and the last slide of Owen's deck. (3) New page `web/setup.html`: host onboarding (name room → add devices → room ready + printable QR). **Ask for Jay:** one small Brain call to set the room label from setup — proposal: `POST /host/room {label}` with `HOST_TOKEN`, returns the `room` object; I'll add it to `ARCHITECTURE.md` §10 if you agree. Nothing else in the shared frames changes.

## 17:05 — display restructured to Owen's past UI feedback
- Right column is now two framed surfaces (`.surface`, #0c0c0e, .16 edge) that fill the viewport: devices table fixed at 38% height, ledger takes the rest. Both columns end at the same pixel line (measured 852px at 1440x900 in reset and live states).
- Devices are a hairline table: Device · Can do · State · Last action. "Last action" reads an optional `last_action` string per device if the Brain sends one, else the newest ledger row that names the device, else "Nothing yet". Jay: `last_action` is optional, sentence form, no schema change required.
- Mock: the 7s ticker now idles when there are no guests (nobody here → nothing happens), so pressing R gives a genuinely quiet reset state.
- Fixed a real bug: the amber guest block re-ran its wipe-in animation on every 1s re-render (would flicker on the live backend too). It now animates only the first time a guest appears.
- Screenshots: notes/shots/display-reset-1440x900.png, notes/shots/display-live-1440x900.png.

## 17:40 — plum/pink theme; display is now the host's operational screen
- Theme tokens replaced in `web/tenant.css`: plum floor `#1a1523`, pink accent `#f0a8e0` used only for the live guest block, the dot on a device that is acting, and the one-time wipe on the newest ledger row. Two line weights: `--line` (.14) inside a region, `--line-2` (.32) between regions. Buttons are pills (pink primary, outline secondary). device.html styles stay black-floored.
- Display restructured (Conduction-Pieces regions, no boxes): 56px top bar (ROOM + code · state sentence · clock), left GUEST region (pink block, or the dither motif + "Nobody is here right now."), right IN THIS ROOM table (40%) over WHAT HAS HAPPENED (remainder). QR and join URL removed from the display — QR goes on the printed card / slides. Both columns end at y=900 at 1440x900 (measured).
- `T.motif()` in shared.js draws the one texture (ordered-dithered pinwheel of squares) — reuse it behind the QR in the setup flow's "room is ready" step. `T.qrSvg(url)` holds the placeholder QR generator for that flow; still no QR library vendored.
- Fixed: `[hidden]` was being overridden by `display:flex` on the empty-state container (both guest block and motif showed). Added `[hidden]{display:none!important}` globally.
- Mock fixtures now fetch with `cache: "no-store"` so edits to state.json / chat.json show on reload.
- Shots: notes/shots/display-plum-reset.png, display-plum-live.png, join-plum-390x844.png, join-plum-phone-step-390x844.png, guest-plum-390x844.png.
