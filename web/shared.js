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
    // Each "ok" names the device that acted (`device`) and lights it `busy` for ~3 s, so the
    // display's acting state is exercised. The photo event carries a local `image_url`.
    const state = await (await fetch(mockUrl("state.json"), { cache: "no-store" })).json();
    const byId = (id) => state.devices.find(d => d.id === id);
    const extra = [
      ["do", "Guest 1", " asked for something calm to listen to.", null],
      ["ok", "The room speaker", " started playing Calm.", "laptop"],
      ["do", "Guest 1", " asked what's in the room.", null],
      ["ok", "The room", " listed its devices.", null],
      ["do", "Guest 1", " asked for a photo.", null],
      ["ok", "Jay's phone", " took a photo and the screen is showing it.", "jay-phone", mockUrl("photo.jpg")],
      ["do", "Guest 1", " asked for the screen to flash.", null],
      ["ok", "Owen's phone", " flashed its screen.", "owen-phone"],
    ];
    let i = 0, busyTimer = null;
    onState(state);
    setInterval(() => {
      if (state.guests[0]) state.guests[0].expires_in = Math.max(0, state.guests[0].expires_in - 1);
      onState(state);
    }, 1000);
    setInterval(() => {
      if (!state.guests.length) return; // nobody here — nothing happens
      const [kind, subject, rest, devId, image_url] = extra[i++ % extra.length];
      const row = { t: Date.now() / 1000, kind, subject, rest, text: subject + rest };
      if (devId) row.device = devId;
      if (image_url) row.image_url = image_url;
      if (kind === "ok" && devId) {
        state.devices.forEach(d => d.busy = false);
        byId(devId).busy = true; byId(devId).last_action = row.text;
        clearTimeout(busyTimer);
        busyTimer = setTimeout(() => { byId(devId).busy = false; onState(state); }, 3000);
      }
      state.log.unshift(row);
      state.log = state.log.slice(0, 40);
      onState(state);
    }, 7000);
    return { host: (type, extra) => {
      if (type === "host.reset") { state.guests = []; delete state.room.sentence_subject; delete state.room.sentence_rest; state.log.unshift({ t: Date.now() / 1000, kind: "cmd", subject: "The room", rest: " was reset.", text: "The room was reset." }); onState(state); }
      if (type === "host.revoke") { const g = state.guests.find(x => x.guest_id === (extra || {}).guest_id); if (g) { state.guests = state.guests.filter(x => x !== g); delete state.room.sentence_subject; delete state.room.sentence_rest; state.log.unshift({ t: Date.now() / 1000, kind: "guest.leave", subject: g.display_name, rest: " was asked to leave.", text: g.display_name + " was asked to leave." }); onState(state); } }
    } };
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

  /* ---------- dither as the one material (display) ----------
   * Everything below draws 5px squares on a 6px grid, thresholded by the same
   * 4x4 Bayer matrix as `motif`, so the ring, the device glyphs and the halftone
   * photo read as one substance. All return inline <svg> strings or draw to a canvas.
   */
  const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  const bayerOn = (v, x, y) => v > (BAYER[y & 3][x & 3] + .5) / 16;
  const hash2 = (x, y, salt) => { let h = (0x9e3779b9 ^ (x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)) >>> 0; h = Math.imul(h, 2654435761) >>> 0; return ((h >>> 8) & 1023) / 1024; };

  /* A ring of squares whose arc is `frac` of the circle, starting at 12 o'clock and
   * going clockwise. The leading minute of arc dissolves into scattered squares.
   * n = grid cells per side. Used for the lease countdown on the guest block. */
  function ring(frac, n = 48, thick = .12) {
    frac = Math.max(0, Math.min(1, frac));
    const c = (n - 1) / 2, R = c, cells = [];
    const edge = frac * 2 * Math.PI, fade = Math.min(edge, Math.PI / 6); // the leading twelfth dissolves
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const dx = x - c, dy = y - c, r = Math.hypot(dx, dy) / R;
      if (r > 1 || r < 1 - thick * 2.4) continue;
      let th = Math.atan2(dx, -dy); if (th < 0) th += 2 * Math.PI;   // 0 at top, clockwise
      if (th > edge) continue;
      const band = 1 - Math.abs((r - (1 - thick)) / thick);           // 1 at the ring's centre line, 0 at its edges
      if (band <= 0) continue;
      let v = Math.pow(band, .55);                                     // dense centre line, dithering out to both edges
      const lead = edge - th;                                          // distance back from the leading edge
      if (lead < fade) { const k = lead / fade; v *= k; if (hash2(x, y, 7) > .2 + k) continue; }
      // a few squares drift off the leading edge
      if (lead < fade * .5 && hash2(x, y, 11) < .08) { const ox = Math.round(dx * .08), oy = Math.round(dy * .08); cells.push(`<rect x="${(x + ox) * 6}" y="${(y + oy) * 6}" width="5" height="5"/>`); continue; }
      if (bayerOn(v, x, y)) cells.push(`<rect x="${x * 6}" y="${y * 6}" width="5" height="5"/>`);
    }
    const px = n * 6 - 1;
    return `<svg viewBox="0 0 ${px} ${px}" width="${px}" height="${px}" fill="currentColor" shape-rendering="crispEdges" aria-hidden="true">${cells.join("")}</svg>`;
  }

  /* Device glyphs on a 12x12 cell grid, 72px drawn. Each square carries its distance
   * from the glyph's centre as a CSS variable so the acting animation can run
   * centre-outward (phone), ring-by-ring (speaker) or top-down (screen). */
  function glyphKind(label) {
    const l = String(label || "").toLowerCase();
    if (/speaker|sound|audio/.test(l)) return "speaker";
    if (/phone|mobile/.test(l)) return "phone";
    if (/screen|tablet|tv|display|laptop|monitor/.test(l)) return "screen";
    return "square";
  }
  function glyph(kind, n = 12) {
    const cells = [], c = (n - 1) / 2;
    const push = (x, y) => { const d = Math.hypot(x - c, y - c) / c; cells.push(`<rect x="${x * 6}" y="${y * 6}" width="5" height="5" style="--d:${d.toFixed(2)};--row:${(y / (n - 1)).toFixed(2)}"/>`); };
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      let on = false, v = 1;
      if (kind === "phone") {                                             // rounded rect 6 wide, notch at top
        const inX = x >= 3 && x <= 8, inY = y >= 0 && y <= 11;
        const corner = (x === 3 || x === 8) && (y === 0 || y === 11);
        const notch = y === 0 && x >= 5 && x <= 6;
        on = inX && inY && !corner && !notch;
        v = (x === 3 || x === 8 || y === 1 || y === 11 || notch) ? 1 : .35;   // solid shell, dithered face
        if (y === 0) v = 1;
      } else if (kind === "speaker") {                                    // concentric rings
        const r = Math.hypot(x - c, y - c);
        on = r <= 5.6 && (Math.abs(r - 5.2) < .6 || Math.abs(r - 3.2) < .6 || r < 1.2);
        v = 1;
      } else if (kind === "screen") {                                     // wide rect 12 x 8 with a stand
        on = (y >= 2 && y <= 8 && x >= 0 && x <= 11) || (y === 9 && x >= 4 && x <= 7) || (y === 10 && x >= 2 && x <= 9);
        v = (y === 2 || y === 8 || x === 0 || x === 11 || y >= 9) ? 1 : .35;
      } else {                                                            // plain square
        on = x >= 2 && x <= 9 && y >= 2 && y <= 9;
        v = (x === 2 || x === 9 || y === 2 || y === 9) ? 1 : .35;
      }
      if (on && bayerOn(v, x, y)) push(x, y);
    }
    return `<svg viewBox="0 0 ${n * 6 - 1} ${n * 6 - 1}" fill="currentColor" shape-rendering="crispEdges" aria-hidden="true">${cells.join("")}</svg>`;
  }

  /* Halftone: draw `img` into `canvas` as 5px squares on a 6px grid, one colour,
   * luminance -> Bayer threshold. Scales to the canvas's CSS box. Pink on plum by default. */
  function halftone(canvas, img, color) {
    const cell = 6, W = Math.max(cell, Math.floor(canvas.clientWidth || 240)), H = Math.max(cell, Math.floor(canvas.clientHeight || 160));
    const gx = Math.floor(W / cell), gy = Math.floor(H / cell);
    canvas.width = gx * cell; canvas.height = gy * cell;
    const ctx = canvas.getContext("2d");
    // sample: cover-fit the image onto the cell grid
    const s = Math.max(gx / img.naturalWidth, gy / img.naturalHeight);
    const sw = img.naturalWidth * s, sh = img.naturalHeight * s;
    const tmp = document.createElement("canvas"); tmp.width = gx; tmp.height = gy;
    const tc = tmp.getContext("2d"); tc.drawImage(img, (gx - sw) / 2, (gy - sh) / 2, sw, sh);
    const px = tc.getImageData(0, 0, gx, gy).data;
    ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.fillStyle = color || getComputedStyle(canvas).color;
    for (let y = 0; y < gy; y++) for (let x = 0; x < gx; x++) {
      const i = (y * gx + x) * 4, lum = (px[i] * .2126 + px[i + 1] * .7152 + px[i + 2] * .0722) / 255;
      if (bayerOn(lum, x, y)) ctx.fillRect(x * cell, y * cell, cell - 1, cell - 1);
    }
  }

  window.Tenant = { MOCK, capWord, listWords, fmtClock, fmtTime, motif, ring, glyph, glyphKind, halftone, qrSvg, connectDisplay, connectGuest, leaveGuest, postJoin };
})();
