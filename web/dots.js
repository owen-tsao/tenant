/* Tenant — the two interactive dot materials, as vanilla JS.
 *   T.sphere(canvas, opts)    a dotted globe that assembles, thinks, resolves and collapses
 *   T.wordmark(canvas, text)  a word printed as a field of squares that part around the pointer
 * Both draw 2D squares (not round dots) so they read as the same material as
 * T.motif / T.ring / T.glyph. Math ported from two 21st.dev components in Owen's
 * library: ai-thinking-orb-and-input (MorphOrb) and halftone-wordmark-footer.
 * Loads after shared.js and extends window.Tenant.
 */
(function () {
  const T = window.Tenant || (window.Tenant = {});
  const TAU = Math.PI * 2;
  const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function cubicBezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const sx = (t) => ((ax * t + bx) * t + cx) * t, sy = (t) => ((ay * t + by) * t + cy) * t, dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
    const solve = (x) => {
      let t = x;
      for (let i = 0; i < 8; i++) { const e = sx(t) - x; if (Math.abs(e) < 1e-6) return t; const d = dx(t); if (Math.abs(d) < 1e-6) break; t -= e / d; }
      let lo = 0, hi = 1; t = x;
      for (let i = 0; i < 40; i++) { const e = sx(t); if (Math.abs(e - x) < 1e-6) break; if (x > e) lo = t; else hi = t; t = (hi - lo) / 2 + lo; }
      return t;
    };
    return (x) => (x <= 0 ? 0 : x >= 1 ? 1 : sy(solve(x)));
  }
  const E = { out: cubicBezier(.22, 1, .36, 1), io: cubicBezier(.65, 0, .35, 1), in: cubicBezier(.4, 0, 1, 1), vortex: cubicBezier(.6, 0, .2, 1) };

  // A tiny timeline: tracks {ch, from, to, t0, t1, ease} written onto `P` each frame.
  const Tr = (ch, from, to, t0, t1, ease) => ({ ch, from, to, t0, t1, ease: ease || E.io });
  function play(P, tracks, onFrame, alive) {
    return new Promise((res) => {
      const end = tracks.reduce((m, k) => Math.max(m, k.t1), 0);
      let t = 0, last = performance.now(), raf = 0;
      const step = (now) => {
        if (alive && !alive()) return res();   // owner destroyed mid-animation: stop the loop, settle the promise
        t += Math.max(0, Math.min(100, now - last)); last = now;
        for (const k of tracks) { if (t < k.t0) continue; const p = Math.min(1, (t - k.t0) / Math.max(1, k.t1 - k.t0)); P[k.ch] = k.from + (k.to - k.from) * k.ease(p); }
        onFrame && onFrame();
        if (t >= end) res(); else raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    });
  }

  /* ---------- sphere ----------
   * opts: size (CSS px, default canvas box), rings (16), ink [r,g,b] (pink), lit [r,g,b] (fg),
   *       square (true: squares, false: round dots).
   * Returns { assemble(), think(), resolve(), collapse(), set(ch,v), P, destroy() }. */
  function sphere(canvas, opts) {
    opts = opts || {};
    const size = opts.size || canvas.clientWidth || 220;
    const RINGS = opts.rings || 16;
    const ink = opts.ink || [240, 168, 224], lit = opts.lit || [244, 238, 247];
    const square = opts.square !== false;
    const rand = mulberry32(7);
    const dots = [];
    for (let k = 0; k < RINGS; k++) {
      const y = 1 - ((k + .5) / RINGS) * 2, r = Math.sqrt(1 - y * y);
      const m = Math.max(4, Math.round(30 * r * (RINGS / 16)));
      for (let j = 0; j < m; j++) { const a = (j / m) * TAU + k * .35; dots.push({ x: Math.cos(a) * r, y, z: Math.sin(a) * r, u: (1 - y) / 2, seed: rand() * 6.283 }); }
    }
    const N = dots.length;
    const DX = Float32Array.from(dots, (d) => d.x), DY = Float32Array.from(dots, (d) => d.y), DZ = Float32Array.from(dots, (d) => d.z), DU = Float32Array.from(dots, (d) => d.u), DS = Float32Array.from(dots, (d) => d.seed);
    const G_STEPS = 24, A_STEPS = 48, COLORS = [];
    for (let gi = 0; gi <= G_STEPS; gi++) {
      const g = gi / G_STEPS, r = Math.round(lerp(ink[0], lit[0], g)), gg = Math.round(lerp(ink[1], lit[1], g)), b = Math.round(lerp(ink[2], lit[2], g));
      for (let ai = 0; ai <= A_STEPS; ai++) COLORS.push("rgba(" + r + "," + gg + "," + b + "," + (ai / A_STEPS).toFixed(3) + ")");
    }
    const P = { k: 0, alpha: 0, spin: 0, rot: 0, sweep: 0, pop: 1, vortex: 0, gain: 1, floor: 0, rad: 0, prog: 0 };
    const ctx = canvas.getContext("2d");
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(size * dpr); canvas.height = Math.round(size * dpr);
    canvas.style.width = size + "px"; canvas.style.height = size + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const R = size * .3, C0 = size / 2, DOT = Math.max(size / 220, opts.dot || .45);   // orb radius 66 at 220; squares never thinner than ~1px
    const litA = new Float32Array(N), SX = new Float32Array(N), SY = new Float32Array(N), SR = new Float32Array(N), SD = new Float32Array(N), SC = new Int16Array(N);
    const pw = [1, 0, 0, 0];
    const S = .6, CP = Math.cos(.35), SP = Math.sin(.35);
    let time = 0, raf = 0, last = 0, dead = false, labelTimer = null;

    function draw(dt) {
      ctx.clearRect(0, 0, size, size);
      time += dt; P.rot += P.spin * dt;
      const yaw = P.rot + P.vortex, cyw = Math.cos(yaw), syw = Math.sin(yaw);
      const stepW = dt / .35;
      for (let q = 0; q < 4; q++) { const d = (q === P.prog ? 1 : 0) - pw[q]; pw[q] += Math.abs(d) <= stepW ? d : d > 0 ? stepW : -stepW; }
      const decay = Math.exp(-dt / .5);
      const h0 = (time * 300) % N, h3 = (time * 480) % N;
      const a1 = time * .8, b1 = Math.sin(time * .5) * .9, f1x = Math.cos(b1) * Math.cos(a1), f1y = Math.sin(b1), f1z = Math.cos(b1) * Math.sin(a1);
      const a2 = time * .55 + 2.1, b2 = Math.cos(time * .42) * .9, f2x = Math.cos(b2) * Math.cos(a2), f2y = Math.sin(b2), f2z = Math.cos(b2) * Math.sin(a2);
      const lat = Math.sin(time * 2.2), swirlK = P.vortex * 1.5;
      for (let n = 0; n < N; n++) {
        const dx = DX[n], dy = DY[n], dz = DZ[n], u = DU[n];
        let pulse = 0;
        if (pw[0] > .001) { let dd = Math.abs(n - h0); if (dd > N - dd) dd = N - dd; const v = Math.max(0, 1 - dd / 16); pulse = Math.max(pulse, v * v * pw[0]); }
        if (pw[1] > .001) { const v1 = Math.max(0, (dx * f1x + dy * f1y + dz * f1z - .72) / .28), v2 = Math.max(0, (dx * f2x + dy * f2y + dz * f2z - .72) / .28); const v = Math.max(v1, v2); pulse = Math.max(pulse, v * v * pw[1]); }
        if (pw[2] > .001) { const e = dy - lat; const v = Math.max(0, 1 - (e * e) / .02); pulse = Math.max(pulse, v * v * pw[2]); }
        if (pw[3] > .001) { let dd = Math.abs(n - h3); if (dd > N - dd) dd = N - dd; const v = Math.max(0, 1 - dd / 22); pulse = Math.max(pulse, v * v * pw[3]); }
        const l = Math.max(litA[n] * decay, pulse * P.gain); litA[n] = l;
        const ki = clamp01(P.k * (1 + S) - S * u);                   // top dots first, bottom collapse first
        if (ki <= .001) { SC[n] = -1; continue; }
        const eo = E.out(ki), kk = eo * P.pop;
        const x1 = dx * cyw + dz * syw, z1 = -dx * syw + dz * cyw;
        const y2 = dy * CP - z1 * SP, z2 = dy * SP + z1 * CP;
        const f = 2.8 / (2.8 - z2), depth = (z2 + 1) / 2;
        let ox = x1 * R * kk * f, oy = -y2 * R * kk * f;
        if (swirlK > .001) { const sw = (1 - ki) * swirlK, cc = Math.cos(sw), ss = Math.sin(sw); const tx = ox * cc - oy * ss; oy = ox * ss + oy * cc; ox = tx; }
        const g = clamp01((P.sweep * 1.4 - u) / .4);
        let a = .1 + .035 * Math.sin(DS[n] + time * 1.6) * (1 - g) + .32 * depth * depth + .75 * l * (1 - g) + g * (.55 + .4 * depth) + 2 * g * (1 - g);
        a = Math.max(a, P.floor * (.7 + .3 * depth)); if (a > 1) a = 1; a *= eo * P.alpha;
        SX[n] = C0 + ox; SY[n] = C0 + oy; SD[n] = depth;
        SR[n] = (1.15 * (.45 + .75 * depth) * f + .9 * l + g * .25) * (1 + P.rad) * (.4 + .6 * eo) * DOT;
        const ai = Math.round(a * A_STEPS), gi = Math.round(g * G_STEPS);
        SC[n] = ai <= 0 ? -1 : gi * (A_STEPS + 1) + ai;
      }
      for (let pass = 0; pass < 2; pass++) for (let n = 0; n < N; n++) {       // back half, then front half
        const c = SC[n]; if (c < 0) continue; if ((SD[n] >= .5) !== (pass === 1)) continue;
        ctx.fillStyle = COLORS[c];
        if (square) { const s = SR[n] * 2; ctx.fillRect(SX[n] - s / 2, SY[n] - s / 2, s, s); }
        else { ctx.beginPath(); ctx.arc(SX[n], SY[n], SR[n], 0, TAU); ctx.fill(); }
      }
    }
    const frame = (now) => {
      raf = 0; if (dead) return;
      const dt = reduced() ? 0 : Math.max(0, Math.min(.05, (now - last) / 1000)); last = now;
      draw(dt);
      if (P.alpha > .002 && !reduced()) raf = requestAnimationFrame(frame); else if (P.alpha <= .002) ctx.clearRect(0, 0, size, size);   // reduced motion: one still frame, no 60 fps loop
    };
    const ensure = () => { if (raf || dead || P.alpha <= .002) return; last = performance.now(); raf = requestAnimationFrame(frame); };
    const run = (tracks) => { P.alpha = Math.max(P.alpha, .003); ensure(); return play(P, tracks, ensure, () => !dead); };

    const api = {
      P,
      set(ch, v) { P[ch] = v; ensure(); },
      // 0 -> full globe, spinning, with a pop
      assemble() {
        if (reduced()) { P.k = 1; P.alpha = 1; P.spin = 0; ensure(); return Promise.resolve(); }
        return run([Tr("k", 0, 1, 0, 800, E.out), Tr("alpha", 0, 1, 0, 800, E.out), Tr("spin", 0, .9, 0, 800, E.out), Tr("pop", 1, 1.05, 0, 420, E.out), Tr("pop", 1.05, 1, 420, 800, E.io)]);
      },
      // light programs take turns every ~1.15 s while waiting
      think() {
        clearInterval(labelTimer); if (dead) return;   // destroy() may land while assemble() is still running
        P.prog = 0; ensure();
        labelTimer = setInterval(() => { P.prog = (P.prog + 1) % 4; }, 1150);
      },
      // a bright sweep runs top to bottom, the spin settles
      resolve(ms) {
        clearInterval(labelTimer); const s = (ms || 900) / 900;
        if (reduced()) { P.sweep = 1; P.floor = .95; ensure(); return Promise.resolve(); }
        return run([Tr("sweep", 0, 1, 0, 700 * s, E.io), Tr("spin", P.spin, .3, 0, 700 * s, E.out), Tr("gain", 1, 0, 0, 700 * s, E.out), Tr("floor", 0, .95, 400 * s, 900 * s, E.out), Tr("rad", 0, .15, 400 * s, 900 * s, E.out), Tr("pop", 1, 1.04, 600 * s, 800 * s, E.out), Tr("pop", 1.04, 1, 800 * s, 900 * s, E.out)]);
      },
      // the globe swirls into its centre and goes out
      collapse() {
        clearInterval(labelTimer);
        if (reduced()) { P.alpha = 0; return Promise.resolve(); }
        return run([Tr("pop", 1, 1.06, 0, 120, E.out), Tr("k", 1, 0, 120, 640, E.vortex), Tr("vortex", 0, 1.6, 120, 640, E.vortex), Tr("alpha", P.alpha, 0, 500, 800, E.out)]);
      },
      destroy() { dead = true; clearInterval(labelTimer); if (raf) cancelAnimationFrame(raf); raf = 0; },
    };
    return api;
  }

  /* ---------- wordmark ----------
   * A word set huge, cropped by the canvas's bottom edge, printed as squares on a 6px grid.
   * Each square's side is set by how much of the letter covers its cell (area-true, so
   * tone stays even). Pointer pushes squares off their place on springs; displaced squares
   * warm from ink toward `lit`; a click sends a shock ring through the word.
   * opts: gap (6), radius (80), crop (0.2 of cap height below the edge), font, weight (800),
   *       ink/lit [r,g,b], interactive (true), maxCap (0.78: cap height as a share of canvas height),
   *       stack (false): one word per line, each filling the width, the block centred — no crop.
   * Returns { setText(s), relayout(), destroy() }. */
  function wordmark(canvas, text, opts) {
    opts = opts || {};
    const ctx = canvas.getContext("2d");
    const ink = opts.ink || [240, 168, 224], lit = opts.lit || [244, 238, 247];
    const inkCss = "rgb(" + ink.join(",") + ")";
    const gap = Math.max(3, opts.gap || 6), radius = opts.radius == null ? 80 : opts.radius, crop = Math.max(0, Math.min(.6, opts.crop == null ? .2 : opts.crop));
    const font = opts.font || '"Inter Tight", Inter, "Helvetica Neue", Arial, sans-serif', weight = opts.weight || 800, maxCap = opts.maxCap || .78;
    let word = text || "", w = 0, h = 0, dpr = 1, px = -1e5, py = -1e5, raf = 0, awake = true, alive = true, visible = true;
    let ring = { x: 0, y: 0, t: -1 };
    let dots = new Float32Array(0), count = 0;                  // x, y, vx, vy, hx, hy, side per square

    function layout() {
      const rect = canvas.getBoundingClientRect();
      w = Math.max(1, Math.round(rect.width)); h = Math.max(1, Math.round(rect.height));
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      const mask = document.createElement("canvas"); mask.width = w; mask.height = h;
      const m = mask.getContext("2d", { willReadFrequently: true });
      m.fillStyle = "#000"; m.textBaseline = "alphabetic";
      const setFont = (px) => { m.font = weight + " " + px + "px " + font; };
      const measure = (s) => { const b = m.measureText(s); return { width: b.width, asc: b.actualBoundingBoxAscent || 0, desc: b.actualBoundingBoxDescent || 0 }; };
      if (opts.stack) {
        // one word per line, each set to fill the width; the block is scaled to fit and centred vertically
        const words = (word.trim() ? word.trim().split(/\s+/) : [" "]);
        const lines = words.map((s) => { setFont(100); const mw = m.measureText(s).width; const fit = mw > 0 ? ((w * .94) / mw) * 100 : 0; setFont(fit); const b = measure(s); return { s, fit, asc: b.asc || fit * .72, desc: b.desc || fit * .05, width: b.width }; });
        const gapL = h * .025;
        const total = () => lines.reduce((a, l) => a + l.asc + l.desc, 0) + gapL * (lines.length - 1);
        if (total() > h * maxCap) { const sc = (h * maxCap) / total(); for (const l of lines) { l.fit *= sc; setFont(l.fit); const b = measure(l.s); l.asc = b.asc || l.fit * .72; l.desc = b.desc || l.fit * .05; l.width = b.width; } }
        let y = (h - total()) / 2;
        for (const l of lines) { setFont(l.fit); m.fillText(l.s, (w - l.width) / 2, y + l.asc); y += l.asc + l.desc + gapL; }
      } else {
        // one line filling the width, cropped by the bottom edge
        const s = word || " ";
        setFont(100);
        const measured = m.measureText(s).width;
        let fit = measured > 0 ? ((w * .96) / measured) * 100 : 0;
        setFont(fit);
        let cap = measure(s).asc || fit * .72;
        if (cap > h * maxCap) { fit *= (h * maxCap) / cap; setFont(fit); cap = measure(s).asc || fit * .72; }
        const box = measure(s);
        m.fillText(s, (w - box.width) / 2, h + cap * crop);
      }
      const img = m.getImageData(0, 0, w, h).data;
      const cols = Math.ceil(w / gap), rows = Math.ceil(h / gap), tmp = [];
      for (let gy = 0; gy < rows; gy++) for (let gx = 0; gx < cols; gx++) {
        let sum = 0;                                                     // coverage: 3x3 samples per cell
        for (let sy = 0; sy < 3; sy++) for (let sx = 0; sx < 3; sx++) {
          const x = Math.min(w - 1, Math.floor(gx * gap + ((sx + .5) * gap) / 3)), y = Math.min(h - 1, Math.floor(gy * gap + ((sy + .5) * gap) / 3));
          sum += img[(y * w + x) * 4 + 3];
        }
        const cov = sum / (9 * 255); if (cov < .06) continue;
        const hx = gx * gap + gap / 2, hy = gy * gap + gap / 2;
        tmp.push(hx, hy, 0, 0, hx, hy, Math.sqrt(cov) * (gap - 1));
      }
      dots = new Float32Array(tmp); count = tmp.length / 7; awake = true;
    }

    function draw(now) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const r = opts.interactive !== false && !reduced() ? radius : 0;
      const ringAge = ring.t < 0 ? 1e9 : now - ring.t, ringR = ringAge * .9;
      let moving = false;
      for (let i = 0; i < count; i++) {
        const j = i * 7;
        let x = dots[j], y = dots[j + 1], vx = dots[j + 2], vy = dots[j + 3];
        const hx = dots[j + 4], hy = dots[j + 5];
        if (!reduced()) {
          if (ringAge < 900) {
            const dx = hx - ring.x, dy = hy - ring.y, d = Math.sqrt(dx * dx + dy * dy) + .001;
            const band = 1 - Math.min(1, Math.abs(d - ringR) / 26);
            if (band > 0) { const f = band * 3.2 * (1 - ringAge / 900); vx += (dx / d) * f; vy += (dy / d) * f; }
          }
          const dx = x - px, dy = y - py, d2 = dx * dx + dy * dy;      // push from the pointer
          if (r > 0 && d2 < r * r) { const d = Math.sqrt(d2) + .001, f = (1 - d / r) * 2.6; vx += (dx / d) * f; vy += (dy / d) * f; }
          vx = (vx + (hx - x) * .05) * .84; vy = (vy + (hy - y) * .05) * .84;   // spring home
          x += vx; y += vy;
          if (Math.abs(vx) + Math.abs(vy) > .02 || Math.abs(x - hx) + Math.abs(y - hy) > .05) moving = true;
          else { x = hx; y = hy; vx = 0; vy = 0; }
          dots[j] = x; dots[j + 1] = y; dots[j + 2] = vx; dots[j + 3] = vy;
        }
        const k = Math.min(1, Math.hypot(x - hx, y - hy) / 28);          // warmth: 0 at home, 1 at 28px away
        ctx.fillStyle = k > .02 ? "rgb(" + Math.round(ink[0] + (lit[0] - ink[0]) * k) + "," + Math.round(ink[1] + (lit[1] - ink[1]) * k) + "," + Math.round(ink[2] + (lit[2] - ink[2]) * k) + ")" : inkCss;
        const side = dots[j + 6];
        ctx.fillRect(x - side / 2, y - side / 2, side, side);
      }
      awake = moving || ringAge < 900 || px > -1e4;
    }
    const loop = (now) => { raf = 0; if (!visible || !alive) return; draw(now); if (awake) raf = requestAnimationFrame(loop); };
    const wake = () => { awake = true; if (!raf && visible && alive) raf = requestAnimationFrame(loop); };
    const toLocal = (e) => { const b = canvas.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
    const onMove = (e) => { const p = toLocal(e); px = p[0]; py = p[1]; wake(); };
    const onLeave = () => { px = -1e5; py = -1e5; wake(); };
    const onDown = (e) => { if (reduced()) return; const p = toLocal(e); ring = { x: p[0], y: p[1], t: performance.now() }; wake(); };
    const target = opts.pointerTarget || canvas;
    if (opts.interactive !== false) { target.addEventListener("pointermove", onMove); target.addEventListener("pointerleave", onLeave); target.addEventListener("pointerdown", onDown); }
    const ro = new ResizeObserver(() => { layout(); wake(); }); ro.observe(canvas);
    const io = new IntersectionObserver((en) => { visible = en[0] ? en[0].isIntersecting : true; if (visible) wake(); }); io.observe(canvas);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (alive) { layout(); wake(); } });
    layout(); wake();

    return {
      setText(s) { word = s || ""; layout(); wake(); },
      relayout() { layout(); wake(); },
      destroy() {
        alive = false; cancelAnimationFrame(raf); ro.disconnect(); io.disconnect();
        target.removeEventListener("pointermove", onMove); target.removeEventListener("pointerleave", onLeave); target.removeEventListener("pointerdown", onDown);
      },
    };
  }

  T.sphere = sphere;
  T.wordmark = wordmark;
})();
