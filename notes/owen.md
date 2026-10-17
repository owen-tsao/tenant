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
