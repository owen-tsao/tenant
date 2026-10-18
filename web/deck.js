/* Tenant deck — controller.
 * One hook owns navigation (keys, click, right-click, #n hash, steps-within-a-slide). Each slide names
 * a stage shot and declares how many clicks it consumes; `cues` says what the room and the slide's own
 * graphics do on each step. Live room state (code, device count, join URL, guests) comes from
 * Tenant.connectDisplay when the Brain is up; in ?mock=1 the fixture is used and the automatic
 * hand-off never fires.
 *
 * Deck-level constants you may need to change on the day are at the top. */
(function () {
  "use strict";
  const T = window.Tenant || {};
  const MOCK = !!T.MOCK;
  const qs = new URLSearchParams(location.search);

  /* ---- constants for the day ---- */
  const DISPLAY_URL = "display.html";             // where the deck hands off to
  const IMESSAGE_NUMBER = qs.get("imessage") || ""; // e.g. "+1 628-502-4649" once Photon is live; empty = hidden
  const FALLBACK = { code: "7F3A", devices: 3, joinUrl: location.origin + "/j/7F3A" };
  const LEASE_SECONDS = 600;
  const STILL = qs.has("still"); // debug: finish every animation immediately (screenshots, tests)
  const TRACE = qs.has("trace"); // debug: show the last input/navigation events bottom-left

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  // The trace always records (ring buffer of the last 40 input/navigation events); it is only *shown* with
  // ?trace=1 or by pressing T. So when a navigation misbehaves, press T right then and read what led to it.
  let tracePane = null, traceOn = TRACE;
  const traceLines = [];
  function showTrace(on) {
    traceOn = on;
    if (on && !tracePane) tracePane = Object.assign(document.body.appendChild(document.createElement("pre")), { id: "trace", style: "position:fixed;left:8px;bottom:8px;z-index:99;font:11px ui-monospace,monospace;color:#fff;background:#000b;margin:0;padding:6px 8px;border-radius:6px;pointer-events:none;white-space:pre" });
    if (tracePane) { tracePane.hidden = !on; if (on) tracePane.textContent = traceLines.join("\n"); }
  }
  function trace(s) { traceLines.push(`${(performance.now() / 1000).toFixed(2)}s ${s}`); if (traceLines.length > 40) traceLines.shift(); if (traceOn && tracePane) tracePane.textContent = traceLines.join("\n"); }
  window.deckTrace = () => traceLines.join("\n");
  window.addEventListener("keydown", e => trace(`key ${e.key}${e.repeat ? " (repeat)" : ""}${e.metaKey ? " meta" : ""}${e.ctrlKey ? " ctrl" : ""}${e.altKey ? " alt" : ""}`), true);
  window.addEventListener("click", e => trace(`click ${e.button} on ${e.target.tagName}`), true);
  window.addEventListener("auxclick", e => trace(`auxclick button=${e.button}`), true);
  window.addEventListener("contextmenu", () => trace("contextmenu"), true);
  window.addEventListener("hashchange", () => trace(`hashchange ${location.hash}`), true);
  window.addEventListener("popstate", () => trace(`popstate ${location.hash}`), true);
  window.addEventListener("pageshow", e => trace(`pageshow persisted=${e.persisted}`));
  window.addEventListener("wheel", e => trace(`wheel dx=${Math.round(e.deltaX)} dy=${Math.round(e.deltaY)}`), { capture: true, passive: true });
  trace(`load ${location.hash || "(no hash)"}`);
  if (TRACE) showTrace(true);
  function settle() {
    if (!STILL) return;
    requestAnimationFrame(() => {
      document.getAnimations().forEach(a => { try { if (a.effect && a.effect.getTiming().iterations !== Infinity) a.finish(); } catch (_) {} });
      stage.settle();
    });
  }

  /* ---- primitives: odometer, typing, rising characters ---- */
  // odo(el, "9:57") — digits roll inside 1em windows; other characters are static.
  function odo(el, str) {
    str = String(str);
    if (el.dataset.shape !== str.replace(/\d/g, "#")) {
      el.dataset.shape = str.replace(/\d/g, "#");
      el.innerHTML = "";
      for (const ch of str) {
        if (/\d/.test(ch)) { const d = document.createElement("span"); d.className = "odo-d"; d.innerHTML = "<span>" + "0123456789".split("").map(n => `<i>${n}</i>`).join("") + "</span>"; el.appendChild(d); }
        else { const c = document.createElement("span"); c.className = "odo-c"; c.textContent = ch; el.appendChild(c); }
      }
    }
    const digits = $$(".odo-d > span", el); let i = 0;
    for (const ch of str) if (/\d/.test(ch)) digits[i++].style.setProperty("--n", ch);
    el.dataset.value = str; el.setAttribute("aria-label", str); el.setAttribute("role", "text");
    $$(":scope > *", el).forEach(c => c.setAttribute("aria-hidden", "true"));
  }
  // Timers and typing belong to the current step: applyStep() cancels all of them before the next step's cue runs,
  // so a 1.9 s "type the reply once the pulse lands" can never write into a step the presenter already left.
  let timers = [], typers = [];
  function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
  function cancelStep() { timers.forEach(clearTimeout); typers.forEach(clearInterval); timers = []; typers = []; }
  function type(el, { delay = 0, instant = false, onDone } = {}) {
    const text = el.dataset.text || ""; el.textContent = ""; el.classList.remove("done");
    if (STILL || instant) { el.textContent = text; el.classList.add("done"); onDone && onDone(); return; }
    let i = 0;
    later(() => {
      const id = setInterval(() => { el.textContent = text.slice(0, ++i); if (i >= text.length) { clearInterval(id); el.classList.add("done"); onDone && onDone(); } }, 34);
      typers.push(id);
    }, delay);
  }

  /* ---- slide 2: the stack of things a guest is asked to set up ---- */
  function buildStack() {
    const g = $("#stack-cards"), rule = $("#stack-rule"), labels = $$("#stack-labels li");
    if (!g || g.children.length) return;
    const n = labels.length, cx = 160, w = 140, h = 70, t = 14, gap = 30, baseY = 215;
    const ns = "http://www.w3.org/2000/svg";
    for (let i = 0; i < n; i++) {
      const y = baseY - i * gap, d = 0.45 + i * 0.18;
      const card = document.createElementNS(ns, "g"); card.setAttribute("class", "card" + (i === n - 1 ? " top-card" : "")); card.style.setProperty("--d", d + "s");
      const top = document.createElementNS(ns, "path"); top.setAttribute("class", "top");
      top.setAttribute("d", `M${cx - w} ${y} L${cx} ${y - h} L${cx + w} ${y} L${cx} ${y + h} Z`);
      const left = document.createElementNS(ns, "path"); left.setAttribute("class", "side");
      left.setAttribute("d", `M${cx - w} ${y} L${cx} ${y + h} L${cx} ${y + h + t} L${cx - w} ${y + t} Z`);
      const right = document.createElementNS(ns, "path"); right.setAttribute("class", "side");
      right.setAttribute("d", `M${cx} ${y + h} L${cx + w} ${y} L${cx + w} ${y + t} L${cx} ${y + h + t} Z`);
      card.append(left, right, top); g.appendChild(card);
      const li = labels[i]; if (li && !li.firstElementChild) { const s = document.createElement("span"); s.style.setProperty("--d", (d + 0.1) + "s"); s.textContent = li.textContent; li.textContent = ""; li.appendChild(s); }
    }
    // measuring line to the right of the stack
    const x = cx + w + 22, y0 = baseY + h + t, y1 = baseY - (n - 1) * gap - h;
    const bar = document.createElementNS(ns, "line"); bar.setAttribute("class", "bar"); bar.setAttribute("x1", x); bar.setAttribute("x2", x); bar.setAttribute("y1", y0); bar.setAttribute("y2", y1);
    const tick = (y) => { const l = document.createElementNS(ns, "line"); l.setAttribute("x1", x - 5); l.setAttribute("x2", x + 5); l.setAttribute("y1", y); l.setAttribute("y2", y); return l; };
    rule.append(bar, tick(y0), tick(y1));
  }

  /* ---- stage ---- */
  const stage = window.Stage;
  stage.mount($("#stage"));
  stage.setDeviceCount(FALLBACK.devices);
  function lvl(o) { for (const k in o) stage.set(k, o[k]); }

  // What the room — and each slide's own graphics — do as each step arrives. `final` is false when we
  // are catching up through earlier steps (e.g. deep-linking to #3.2), so long-running effects skip ahead.
  const cues = {
    title:   { 0: (final) => { if (final) { stage.jump("build", 0); stage.set("build", 1); } lvl({ presence: 1, devicesLit: 0, brainLit: 0, links: 0, guest: 0, scale: 1, wash: 1, rooms: 0, reach: 0 }); } },
    problem: { 0: () => { stage.jump("build", 1); lvl({ presence: .16, devicesLit: 0, brainLit: 0, links: 0, guest: 0, scale: 1, wash: 0, rooms: 0, reach: 0 }); buildStack(); },
               1: () => {} },
    how:     { 0: () => { stage.jump("build", 1); lvl({ presence: 1, devicesLit: 1, brainLit: 1, links: 0, guest: 0, scale: 1, rooms: 0, reach: 0 }); },
               1: (final) => { lvl({ links: 1, guest: 1 }); type($("#typed-ask"), { delay: 350, instant: !final }); },
               2: (final) => { lvl({ links: 1, guest: 1 }); const reply = $("#typed-reply"); reply.parentElement.classList.add("waiting");
                               const go = () => { reply.parentElement.classList.remove("waiting"); type(reply, { instant: !final }); };
                               if (final) { later(() => stage.pulse(), 200); later(go, 1250); } else go(); } },
    lease:   { 0: () => { stage.jump("build", 1); lvl({ presence: 1, devicesLit: 1, brainLit: 1, links: 1, guest: 1, scale: 1, rooms: 0, reach: 0 }); startCountdown(); },
               1: () => { lvl({ guest: 0, links: 0 }); endLease(); } },
    // the room we've been looking at pulls back and becomes a block of nine; on the click one guest reaches all of them
    vision:  { 0: () => { stage.jump("build", 1); lvl({ presence: 1, devicesLit: 1, brainLit: 1, links: 0, guest: 0, scale: 1, rooms: 1, reach: 0 }); stopCountdown(); },
               1: () => { lvl({ reach: 1 }); } },
    scan:    { 0: () => { stage.jump("build", 1); lvl({ presence: .3, devicesLit: 1, brainLit: 1, links: 1, guest: 0, scale: 1, rooms: 0, reach: 0 }); stopCountdown(); } },
  };

  /* ---- live room state ---- */
  let room = Object.assign({}, FALLBACK);
  let handedOff = false;
  function applyRoom(s) {
    if (s.room && s.room.code) room.code = s.room.code;
    if (s.room && s.room.join_url) room.joinUrl = s.room.join_url;
    if (Array.isArray(s.devices)) { const n = s.devices.filter(d => d.online !== false).length; if (n) room.devices = n; }
    stage.setDeviceCount(room.devices);
    $$(".room-code").forEach(el => el.textContent = room.code);
    $$(".device-count").forEach(el => el.textContent = room.devices);
    renderQR();
    // Hand-off: the moment a real guest appears while we're on the last slide, the display takes over.
    if (!MOCK && !handedOff && index === slides.length - 1 && Array.isArray(s.guests) && s.guests.length) handOff();
  }
  if (typeof T.connectDisplay === "function") T.connectDisplay(applyRoom).catch(() => {});

  function handOff() {
    handedOff = true;
    document.body.style.transition = "opacity 600ms cubic-bezier(.5,0,.75,0)";
    document.body.style.opacity = "0";
    setTimeout(() => { location.href = DISPLAY_URL + (MOCK ? "?mock=1" : ""); }, 650);
  }

  /* ---- QR: the Brain serves /qr.svg for the current room; mock gets the placeholder ----
   * If /qr.svg fails (Brain restarting, route missing) the box must not sit empty on the projector:
   * the placeholder pattern fills it, dimmed, and we retry every 4 s until the real image loads.
   * (The placeholder is NOT scannable — shared.js qrSvg; Owen chose no on-slide URL line, 23:53.) */
  let qrKey = null, qrRetry = null;
  function renderQR() {
    const el = $("#qr"); if (!el) return;
    const key = room.joinUrl + "|" + room.code; if (key === qrKey) return; qrKey = key;
    clearTimeout(qrRetry); setQRFallback(false);
    // Jay's Brain serves /qr.svg for the room's current join URL (notes/jay.md 17:05); the query is only a cache-buster keyed to the code.
    if (!MOCK) { loadQR(el, `/qr.svg?v=${encodeURIComponent(room.code)}`, 0); return; }
    el.innerHTML = typeof T.qrSvg === "function" ? T.qrSvg(room.joinUrl) : "";
  }
  function loadQR(el, src, attempt) {
    const img = new Image(); img.alt = "";
    img.onload = () => { el.replaceChildren(img); setQRFallback(false); };
    img.onerror = () => {
      trace(`qr.svg failed (attempt ${attempt + 1})`);
      if (!el.firstChild) el.innerHTML = typeof T.qrSvg === "function" ? T.qrSvg(room.joinUrl) : "";
      setQRFallback(true);
      qrRetry = setTimeout(() => loadQR(el, src + "&r=" + (attempt + 1), attempt + 1), 4000);
    };
    img.src = src;
  }
  function setQRFallback(on) { const q = $("#qr"); if (q) q.classList.toggle("is-fallback", on); }
  if (IMESSAGE_NUMBER) { $("#text-number").textContent = IMESSAGE_NUMBER; $("#text-opt").hidden = false; }

  /* ---- lease countdown + the "leave" beat ---- */
  let countdown = null, leaseEnded = false, leaseStart = 0;
  function startCountdown() {
    stopCountdown(); leaseEnded = false; leaseStart = performance.now();
    $("#lease-block").classList.remove("ended");
    $("#lease-who").textContent = "Your lease";
    // Shown from 9:59, not 10:00: the clock is sized for four glyphs so it fills the block; "10:00" would overflow for one second.
    const tick = () => { const left = Math.min(LEASE_SECONDS - 1, Math.max(0, LEASE_SECONDS - (performance.now() - leaseStart) / 1000)); odo($("#lease-left"), T.fmtClock ? T.fmtClock(left) : Math.ceil(left)); };
    tick(); countdown = setInterval(tick, 250);
  }
  function stopCountdown() { if (countdown) clearInterval(countdown); countdown = null; }
  function endLease() {
    stopCountdown(); leaseEnded = true;
    $("#lease-block").classList.add("ended");
    $("#lease-who").textContent = "Lease ended";
    odo($("#lease-left"), "0:00");
  }

  /* ---- navigation ---- */
  const slides = $$(".slide");
  const stepsOf = (el) => parseInt(el.dataset.steps || "0", 10);
  let index = 0, step = 0, busy = false, pending = 0; // pending: presses that arrived mid-transition (+ forward, − back)
  const fromHash = () => { const m = (location.hash || "").match(/^#(\d+)(?:\.(\d+))?$/); return m ? [Math.min(slides.length - 1, Math.max(0, +m[1] - 1)), +(m[2] || 0)] : [0, 0]; };
  [index, step] = fromHash();

  function applyStep(el, s, final) {
    const id = el.dataset.id;
    cancelStep();
    $$(".beat", el).forEach(b => { const want = +b.dataset.step === s; if (b.hidden === want) { b.hidden = !want; if (want) { const fresh = restart(b); $$(".typed", fresh).forEach(t => { t.textContent = ""; }); } } });
    $$("[data-on]", el).forEach(n => n.classList.toggle("on", +n.dataset.on <= s));
    const cue = cues[id] && cues[id][s]; if (cue) cue(final !== false);
    history.replaceState(null, "", `#${index + 1}${s ? "." + s : ""}`);
    settle();
  }
  function restart(node) { // re-run the node's CSS animations by re-mounting it
    const clone = node.cloneNode(true); node.replaceWith(clone); return clone;
  }

  function enter(i, s, dir) {
    const el = slides[i];
    el.classList.add("is-active");
    document.body.classList.toggle("stage-front", el.dataset.stage === "front"); // slide 1: the room is drawn over the word
    stage.shot(el.dataset.shot || "wide");
    const last = Math.min(s, stepsOf(el));
    for (let k = 0; k <= last; k++) applyStep(el, k, k === last);
    if (dir < 0) $$(".beat", el).forEach(b => { b.hidden = +b.dataset.step !== s; });
  }

  function go(i, s, dir) {
    i = Math.min(slides.length - 1, Math.max(0, i));
    trace(`go ${index + 1}.${step} -> ${i + 1}.${s}${busy ? " (queued)" : ""}`);
    if (busy) { pending += dir > 0 ? 1 : -1; return; } // a press mid-transition is kept, not dropped
    const from = slides[index];
    if (i === index) { step = s; applyStep(from, s, true); drain(); return; }
    busy = true;
    let done = false; // this transition's own flag — a global `busy` check let a stale fallback timer finish the *next* transition
    const finish = () => {
      if (done) return; done = true;
      stopCountdown();   // leaving any slide stops the lease clock; the lease slide's step 0 restarts it on entry
      from.classList.remove("is-active", "is-exiting");
      const fresh = restart(from); slides[index] = fresh;   // reset the old slide's animations for next time
      $$(".typed", fresh).forEach(t => { t.textContent = ""; });
      const sc = $("#stack-cards", fresh); if (sc) sc.innerHTML = ""; const sr = $("#stack-rule", fresh); if (sr) sr.innerHTML = "";
      $$("#stack-labels li", fresh).forEach(li => { li.textContent = li.textContent; });
      index = i; step = s;
      enter(i, s, dir);
      busy = false;
      drain();
    };
    from.classList.add("is-exiting");
    from.addEventListener("animationend", function onEnd(e) { if (e.target !== from) return; from.removeEventListener("animationend", onEnd); finish(); });
    setTimeout(() => { if (!done) finish(); }, 420);
  }

  // Presses that arrived mid-transition are replayed one per completed transition. If a replayed press
  // can't move (we're already on the first or last slide) nothing would ever drain the rest, and the
  // leftover count would fire after the *next* press in the other direction — Owen's "bounce back"
  // (trace 05:56: End, hold ←, then → went 1→2→1). So a press that goes nowhere clears the queue.
  function drain() {
    if (!pending) return;
    trace(`drain pending=${pending}`);
    const moved = pending > 0 ? (pending--, advance()) : (pending++, retreat());
    if (!moved) { pending = 0; trace("drain: at the edge, queue cleared"); }
  }

  function advance() { // → true if a move was started
    const el = slides[index];
    if (step < stepsOf(el)) { go(index, step + 1, 1); return true; }
    if (index < slides.length - 1) { go(index + 1, 0, 1); return true; }
    return false;
  }
  function retreat() {
    if (step > 0) { go(index, step - 1, -1); return true; }
    if (index > 0) { go(index - 1, stepsOf(slides[index - 1]), -1); return true; }
    return false;
  }

  window.addEventListener("keydown", (e) => {
    if (e.repeat) return;
    switch (e.key) {
      case "ArrowRight": case " ": case "Enter": case "PageDown": e.preventDefault(); advance(); break;
      case "ArrowLeft": case "Backspace": case "PageUp": e.preventDefault(); retreat(); break;
      case "Home": go(0, 0, -1); break;
      case "End": go(slides.length - 1, 0, 1); break;
      case "d": case "D": handOff(); break;
      case "f": case "F": document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {}); break;
      case "t": case "T": showTrace(!traceOn); break;
    }
  });
  window.addEventListener("click", advance);
  window.addEventListener("contextmenu", (e) => e.preventDefault()); // no menu over the projector; a trackpad two-finger tap used to read as "back"
  window.addEventListener("hashchange", () => { const [i, s] = fromHash(); trace(`hash -> ${i + 1}.${s} (at ${index + 1}.${step}${busy ? ", busy" : ""})`); if (i !== index) go(i, s, i > index ? 1 : -1); else if (s !== step) go(i, s, s > step ? 1 : -1); });

  let idle = null;
  const wake = () => { document.body.classList.remove("idle"); clearTimeout(idle); idle = setTimeout(() => document.body.classList.add("idle"), 1400); };
  window.addEventListener("mousemove", wake); wake();

  // first paint
  $$(".room-code").forEach(el => el.textContent = room.code);
  odo($("#lease-left"), "9:59");
  $$(".device-count").forEach(el => el.textContent = room.devices);
  renderQR();
  enter(index, step, 1);
})();
