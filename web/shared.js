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
    "light": "flashlight", "flash": "screen flash", "speak": "speak", "sound": "sounds",
    "camera.capture": "camera", "show": "show things", "music.play": "music",
    "music.pause": "pause music", "volume": "volume", "say": "speak", "slides.next": "slides",
    "brightness": "brightness",
  };
  function capWord(c) { return CAP_WORDS[c] || c; }

  /* The one texture: a pinwheel of pink squares, ordered-dithered so density
   * falls off from the centre. Deterministic; returns an inline <svg> string.
   * Used only where no text has to be read over it (display empty state,
   * setup "room is ready" behind the QR). */
  function motif(n = 40, arms = 8, twist = .04) {
    const bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
    const c = (n - 1) / 2, R = c * Math.SQRT2, cells = [];
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const dx = x - c, dy = y - c, r = Math.hypot(dx, dy), th = Math.atan2(dy, dx);
      const spiral = Math.pow(.5 + .5 * Math.cos(arms * th + r * twist * arms), 1.15);
      const fall = Math.pow(Math.max(0, 1 - r / (R * .76)), .3);
      const v = spiral * fall;
      if (v > (bayer[y % 4][x % 4] + .5) / 16) cells.push(`<rect x="${x * 7}" y="${y * 7}" width="6" height="6"/>`);
    }
    return `<svg viewBox="0 0 ${n * 7 - 1} ${n * 7 - 1}" fill="currentColor" shape-rendering="crispEdges" aria-hidden="true">${cells.join("")}</svg>`;
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

  function reconnecting(path, onFrame, onStatus) {
    let delay = 500, ws, closed = false;
    function open() {
      ws = new WebSocket(WS_BASE + path);
      ws.onopen = () => { delay = 500; onStatus && onStatus("open"); };
      ws.onmessage = (e) => { try { onFrame(JSON.parse(e.data)); } catch (_) {} };
      ws.onclose = () => {
        onStatus && onStatus("closed");
        if (closed) return;
        setTimeout(open, delay); delay = Math.min(delay * 2, 8000);
      };
      ws.onerror = () => ws.close();
    }
    open();
    return {
      send: (obj) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); },
      close: () => { closed = true; ws && ws.close(); },
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
    return { host: (type) => { if (type === "host.reset") { state.guests = []; state.log.unshift({ t: Date.now() / 1000, kind: "cmd", text: "The room was reset." }); onState(state); } } };
  }

  /* ---------- guest chat ---------- */
  async function connectGuest(guestId, token, onFrame) {
    if (!MOCK) {
      const conn = reconnecting(`/ws/guest?guest_id=${encodeURIComponent(guestId)}&token=${encodeURIComponent(token || "")}`, onFrame);
      return { send: (text) => conn.send({ type: "user", text }) };
    }
    const fx = await (await fetch(mockUrl("chat.json"), { cache: "no-store" })).json();
    let t = 0;
    for (const step of fx.script) { t += step.after; setTimeout(() => onFrame(step), t); }
    return { send: (text) => { onFrame({ type: "user", text }); setTimeout(() => onFrame({ type: "assistant", text: "(mock) I heard: " + text }), 700); }, expires_in: fx.expires_in };
  }

  /* ---------- join ---------- */
  async function postJoin(roomCode, phone) {
    if (!MOCK) {
      const r = await fetch("/join", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(phone ? { room_code: roomCode, phone } : { room_code: roomCode }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Join failed (${r.status})`);
      return r.json();
    }
    await new Promise(r => setTimeout(r, 500));
    const out = { guest_id: "g_mock", guest_token: "tok_mock", chat_url: `${base}/guest.html?mock=1#t=tok_mock` };
    if (phone) { out.imessage_number = "+1 628-502-4649"; out.sms_link = `sms:+16285024649?&body=${encodeURIComponent("join " + roomCode)}`; }
    return out;
  }

  window.Tenant = { MOCK, capWord, fmtClock, fmtTime, motif, qrSvg, connectDisplay, connectGuest, postJoin };
})();
