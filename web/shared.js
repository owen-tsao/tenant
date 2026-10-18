/* Tenant — shared browser helpers for join / guest / display.
 * No framework, no build. Frames are defined in ARCHITECTURE.md §4–§5.
 * `?mock=1` on any page swaps the Brain for fixtures under /mock/ so the
 * pages can be built and judged with nothing running.
 */
(function () {
  const qs = new URLSearchParams(location.search);
  const MOCK = qs.get("mock") === "1";
  const WS_BASE = (location.protocol === "https:" ? "wss://" : "ws://") + location.host;

  // Paths work both when served by the Brain at / and when opened from web/ by a static server.
  const base = location.pathname.includes("/web/") ? location.pathname.split("/web/")[0] + "/web" : "";
  const mockUrl = (name) => `${base}/mock/${name}`;

  const CAP_WORDS = {
    "light": "flashlight", "flash": "screen flash", "speak": "speak", "say": "speak", "sound": "sounds",
    "camera.capture": "take a photo", "photo": "take a photo", "show": "show things",
    "music.play": "play music", "music.pause": "pause music", "volume": "volume", "slides.next": "slides",
    "brightness": "brightness",
  };
  // Unknown capabilities are shown as their own name, lowercased — never dropped.
  function capWord(c) { return CAP_WORDS[c] || String(c).toLowerCase().replace(/[._]/g, " "); }
  // "Owen’s phone, Jay’s phone and the speaker"
  function listWords(items) {
    items = items.filter(Boolean);
    if (items.length <= 1) return items.join("");
    return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
  }

  /* The one texture: a pinwheel of pink squares, ordered-dithered so density
   * falls off from the centre. Deterministic; returns an inline <svg> string.
   * Used only where no text has to be read over it (display empty state,
   * setup "room is ready" behind the QR). */
  function motif(n = 56, arms = 8, twist = .03) {
    const bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
    const c = (n - 1) / 2, R = c, cells = [];
    let h = 0x9e3779b9;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const dx = x - c, dy = y - c, r = Math.hypot(dx, dy) / R, th = Math.atan2(dy, dx);
      const spiral = .5 + .5 * Math.cos(arms * th + r * R * twist * arms);
      const core = Math.pow(Math.max(0, 1 - r / .95), 1.7);          // dense centre, steep falloff
      const v = Math.min(1, core * (0.55 + 0.45 * spiral) * 1.35);
      let on = v > (bayer[y % 4][x % 4] + .5) / 16;
      if (!on && r > .45 && r < 1.15) {                               // outer arms dissolve into single squares
        h = (h ^ (x * 73856093) ^ (y * 19349663)) >>> 0; h = Math.imul(h, 2654435761) >>> 0;
        on = ((h >>> 8) & 1023) / 1024 < spiral * spiral * Math.max(0, 1.15 - r) * .22;
      }
      if (on) cells.push(`<rect x="${x * 6}" y="${y * 6}" width="5" height="5"/>`);
    }
    return `<svg viewBox="0 0 ${n * 6 - 1} ${n * 6 - 1}" fill="currentColor" shape-rendering="crispEdges" aria-hidden="true">${cells.join("")}</svg>`;
  }

  // QR placeholder until a QR library is approved: a deterministic hash pattern
  // that reads as "a QR goes here" without pretending to be scannable.
  // If window.qrcode (qrcode-generator) exists it is used instead.
  function qrSvg(url) {
    if (window.qrcode) { const q = window.qrcode(0, "M"); q.addData(url); q.make(); return q.createSvgTag({ cellSize: 4, margin: 0, scalable: true }); }
    let h = 2166136261; for (const ch of url) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
    const n = 21, cells = [];
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const finder = (x < 7 && y < 7) || (x >= n - 7 && y < 7) || (x < 7 && y >= n - 7);
      let on;
      if (finder) { const fx = x < 7 ? x : x - (n - 7), fy = y < 7 ? y : y - (n - 7); on = fx === 0 || fx === 6 || fy === 0 || fy === 6 || (fx >= 2 && fx <= 4 && fy >= 2 && fy <= 4); }
      else { h = (h ^ (x * 73856093) ^ (y * 19349663)) >>> 0; h = Math.imul(h, 2654435761) >>> 0; on = (h >>> 13) & 1; }
      if (on) cells.push(`<rect x="${x}" y="${y}" width="1" height="1"/>`);
    }
    return `<svg viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" fill="#000">${cells.join("")}</svg>`;
  }

  function fmtClock(sec) {
    sec = Math.max(0, Math.round(sec));
    const m = Math.floor(sec / 60), s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  function fmtTime(t) {
    const d = new Date(t * 1000);
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, "0")).join(":");
  }

  // Reconnecting socket: 500 ms doubling to 8 s. Stops for good on 4401 (bad
  // token) and 1008 (policy), or when the page says so. Reports open/closed.
  function reconnecting(path, onFrame, onStatus) {
    let delay = 500, ws, closed = false, retryTimer = null;
    function open() {
      if (closed) return;
      ws = new WebSocket(WS_BASE + path);
      ws.onopen = () => { delay = 500; onStatus && onStatus("open"); };
      ws.onmessage = (e) => { try { onFrame(JSON.parse(e.data)); } catch (_) {} };
      ws.onclose = (ev) => {
        onStatus && onStatus("closed", ev.code);
        if (closed || ev.code === 4401 || ev.code === 1008) { closed = true; return; }
        retryTimer = setTimeout(() => { retryTimer = null; open(); }, delay); delay = Math.min(delay * 2, 8000);
      };
      ws.onerror = () => ws.close();
    }
    open();
    return {
      send: (obj) => { if (!ws || ws.readyState !== 1) return false; try { ws.send(JSON.stringify(obj)); return true; } catch (_) { return false; } },
      close: () => { closed = true; clearTimeout(retryTimer); ws && ws.close(); },
      stopReconnect: () => { closed = true; clearTimeout(retryTimer); },
    };
  }

  /* ---------- display ---------- */
  async function connectDisplay(onState) {
    if (!MOCK) {
      const token = localStorage.getItem("tenant.host_token") || "";
      const conn = reconnecting(`/ws/display${token ? `?token=${encodeURIComponent(token)}` : ""}`,
        (f) => { if (f.type === "state") onState(f); });
      return {
        host: (type, extra) => conn.send(Object.assign({ type, token: localStorage.getItem("tenant.host_token") || "" }, extra || {})),
      };
    }
    // Mock: load the fixture, then keep it alive — countdown ticks, a log row lands now and then.
    const state = await (await fetch(mockUrl("state.json"), { cache: "no-store" })).json();
    const extra = [
      ["do", "Guest 1 asked for something calm to listen to."],
      ["ok", "The room speaker started playing Calm."],
      ["do", "Guest 1 asked what's in the room."],
      ["ok", "The room listed its devices."],
      ["do", "Guest 1 asked for a photo."],
      ["ok", "Jay's phone took a photo and the screen is showing it."],
    ];
    let i = 0;
    onState(state);
    setInterval(() => {
      if (state.guests[0]) state.guests[0].expires_in = Math.max(0, state.guests[0].expires_in - 1);
      onState(state);
    }, 1000);
    setInterval(() => {
      if (!state.guests.length) return; // nobody here — nothing happens
      const [kind, text] = extra[i++ % extra.length];
      const dev = state.devices[i % 2];
      dev.busy = kind === "do";
      if (kind === "ok") state.devices.forEach(d => d.busy = false);
      state.log.unshift({ t: Date.now() / 1000, kind, text });
      state.log = state.log.slice(0, 40);
      onState(state);
    }, 7000);
    return { host: (type) => { if (type === "host.reset") { state.guests = []; delete state.room.sentence_subject; delete state.room.sentence_rest; state.log.unshift({ t: Date.now() / 1000, kind: "cmd", text: "The room was reset." }); onState(state); } } };
  }

  /* ---------- guest chat ---------- */
  // Frames the page receives: connection {state, code} · lease {state, expires_in,
  // access_expires_in, controls:[{label, caps}]} · user · assistant · action · error · denied.
  async function connectGuest(guestId, token, onFrame) {
    if (!MOCK) {
      const conn = reconnecting(`/ws/guest?guest_id=${encodeURIComponent(guestId)}&token=${encodeURIComponent(token || "")}`,
        onFrame, (state, code) => onFrame({ type: "connection", state, code }));
      return { send: (text) => conn.send({ type: "user", text }), close: () => conn.close(), stopReconnect: () => conn.stopReconnect() };
    }
    // Mock: one connection frame, one lease built from the online devices in state.json,
    // then the scripted thread. ?scene=quiet plays nothing; ?scene=short stops after four lines; ?scene=ended ends the lease early.
    const scene = qs.get("scene") || "";
    const state = await (await fetch(mockUrl("state.json"), { cache: "no-store" })).json();
    const controls = state.devices.filter(d => d.online).map(d => ({ label: d.label, caps: d.caps.slice() }));
    onFrame({ type: "connection", state: "open" });
    onFrame({ type: "lease", state: "active", expires_in: 540, access_expires_in: 540, controls });
    if (scene !== "quiet") {
      const fx = await (await fetch(mockUrl("chat.json"), { cache: "no-store" })).json();
      let t = 0;
      const steps = scene === "ended" ? fx.script.slice(0, 4).concat([{ after: 800, type: "lease", state: "released", reason: "ended", expires_in: 0, access_expires_in: 0, controls: [] }])
        : scene === "short" ? fx.script.slice(0, 4) : fx.script;
      for (const step of steps) { t += step.after; setTimeout(() => onFrame(step), t); }
    }
    return {
      send: (text) => { onFrame({ type: "user", text }); setTimeout(() => onFrame({ type: "assistant", text: "This is a preview — nothing in the room moved." }), 700); return true; },
      close: () => {}, stopReconnect: () => {},
    };
  }

  // POST /leave {guest_id}. Resolves when the Brain confirms; rejects on anything else (5 s cap).
  async function leaveGuest(guestId) {
    if (MOCK) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const r = await fetch("/leave", { method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ guest_id: guestId }) });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body.ok !== true) throw new Error("Leaving wasn't confirmed.");
    } finally { clearTimeout(timer); }
  }

  /* ---------- join ---------- */
  // Rejects with an Error carrying .status and the server's message when it has one.
  async function postJoin(roomCode, phone) {
    if (!MOCK) {
      const r = await fetch("/join", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(phone ? { room_code: roomCode, phone } : { room_code: roomCode }) });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        const err = new Error(body.error || body.detail || body.message || `Couldn't join (${r.status}).`); err.status = r.status; throw err;
      }
      return r.json();
    }
    await new Promise(r => setTimeout(r, 500));
    if (phone && qs.get("sms") === "503") { const err = new Error("Texting isn't available right now."); err.status = 503; throw err; }
    const out = { guest_id: "g_mock", guest_token: "tok_mock", chat_url: `${base}/guest.html?mock=1&room=${encodeURIComponent(roomCode)}#t=tok_mock` };
    if (phone) { out.imessage_number = "+1 628-502-4649"; out.sms_link = `sms:+16285024649?&body=${encodeURIComponent("join " + roomCode)}`; }
    return out;
  }

  window.Tenant = { MOCK, capWord, listWords, fmtClock, fmtTime, motif, qrSvg, connectDisplay, connectGuest, leaveGuest, postJoin };
})();
