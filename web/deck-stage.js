/* Tenant deck — the stage.
 * One <canvas> that never unmounts, behind every slide. A stippled 3D room (floor, walls, a few
 * pieces of furniture) drawn as thousands of tiny squares; the room's devices as pink nodes; the
 * Brain as one node under the ceiling. Slides don't own the picture — they name a *shot* (camera
 * framing) and set *levels* (0..1 scalars). Every frame the camera and every level ease toward
 * their targets, so a slide change is a continuous camera move, not a cut.
 *
 * No dependencies. Plain perspective projection, DPR-aware, pauses when hidden, honours
 * prefers-reduced-motion by freezing the drift (shots still move, instantly).
 *
 * API (window.Stage):
 *   Stage.mount(canvas)             start rendering into this canvas
 *   Stage.shot(name)                ease the camera to a named framing
 *   Stage.set(level, value)         ease a level toward value          levels: see LEVELS
 *   Stage.jump(level, value)        set a level without easing
 *   Stage.pulse()                   run the scan → brain → device pulse once
 *   Stage.setDeviceCount(n)         how many device nodes exist (1..6)
 */
(function () {
  "use strict";

  /* ---------- scene geometry (units ≈ metres) ---------- */
  const ROOM = { w: 7.2, d: 5.2, h: 2.9 };
  const FURNITURE = [
    // a bed along the back wall
    { x: -2.2, y: 0, z: -1.2, w: 2.0, h: 0.55, d: 1.7 },
    { x: -2.2, y: 0.55, z: -1.75, w: 2.0, h: 0.35, d: 0.6 },   // pillow / headboard mass
    // a desk by the right wall with a laptop block on it
    { x: 2.3, y: 0, z: 0.4, w: 1.4, h: 0.74, d: 0.7 },
    { x: 2.4, y: 0.74, z: 0.45, w: 0.34, h: 0.22, d: 0.26 },
    // low table in the middle, a chair
    { x: 0.2, y: 0, z: 0.6, w: 1.1, h: 0.42, d: 0.6 },
    { x: 0.9, y: 0, z: 1.65, w: 0.5, h: 0.95, d: 0.5 },
    // a nightstand with a lamp
    { x: -0.65, y: 0, z: -1.7, w: 0.45, h: 0.6, d: 0.45 },
    { x: -0.65, y: 0.6, z: -1.7, w: 0.1, h: 0.5, d: 0.1 },
  ];
  // Where devices sit if the room reports them. Up to six.
  const DEVICE_SLOTS = [
    [0.2, 0.46, 0.6],      // phone on the table
    [-0.65, 1.12, -1.7],   // phone on the nightstand / lamp
    [2.57, 0.98, 0.58],    // laptop on the desk
    [2.9, 0.78, 0.0],      // speaker on the desk end
    [-2.4, 0.95, -1.75],   // tablet on the bed
    [0.9, 0.98, 1.65],     // something on the chair
  ];
  const BRAIN = [0.9, ROOM.h - 0.3, -0.5];
  const SCAN_POINT = [1.6, 1.3, 2.2];  // where the guest stands — in front of the room

  // Slide 5 ("Every room you don't own"): the same room, eight more times, in a 3×3 block around this one.
  // Nearest neighbours first so the block grows outward. Each clone gets a label at its front edge.
  const GAP = 2.8;
  const CLONES = [
    { dx:  1, dz:  0, label: "Hotel" },     { dx: -1, dz:  0, label: "Hospital" },
    { dx:  0, dz:  1, label: "Airbnb" },    { dx:  0, dz: -1, label: "Classroom" },
    { dx:  1, dz:  1, label: "Office" },    { dx: -1, dz:  1, label: "Clinic" },
    { dx:  1, dz: -1, label: "Dorm" },      { dx: -1, dz: -1, label: "Gym" },
  ].map(c => Object.assign(c, { ox: c.dx * (ROOM.w + GAP), oz: c.dz * (ROOM.d + GAP) }));
  const FAR_GUEST = [0.40, 0.80];  // one guest, outside the whole block: anchored in SCREEN space (fractions of W, H) so the camera drift can't carry it off

  /* ---------- camera shots ---------- */
  // theta: orbit angle around Y (radians); phi: elevation; dist: metres; target: look-at; drift: rad/s
  const SHOTS = {
    wide:   { theta: -0.55, phi: 0.60, dist: 11.8, target: [0.2, 0.9, 0.0], drift: 0.028, offset: [0.56, 0.08] },
    push:   { theta: -0.30, phi: 0.50, dist: 10.0, target: [0.0, 0.9, 0.0], drift: 0.02,  offset: [0.36, 0.06] },
    orbit:  { theta: 0.40,  phi: 0.78, dist: 10.2, target: [0.2, 1.0, 0.0], drift: 0.035, offset: [0.34, 0.10] },
    lease:  { theta: -0.95, phi: 0.46, dist: 10.0, target: [0.0, 1.0, 0.0], drift: 0.02,  offset: [0.36, 0.06] },
    corner: { theta: -0.6,  phi: 0.62, dist: 22.0, target: [0.0, 1.0, 0.0], drift: 0.025, offset: [-0.62, -0.62] },
    behind: { theta: -0.55, phi: 0.58, dist: 9.5,  target: [0.2, 0.9, 0.0], drift: 0.022, offset: [0.02, 0.04] },
    city:   { theta: -0.50, phi: 0.74, dist: 43.0, target: [0.0, 0.4, 0.0], drift: 0.006, offset: [0.46, 0.10] },
  };
  // offset = where on screen the room sits (fraction of half-width/half-height; + = right/down)

  /* ---------- levels ---------- */
  const LEVELS = {
    presence: 1,     // overall ink
    devicesLit: 0,   // 0..1 — fraction of device nodes lit, in order
    brainLit: 0,     // the Brain node
    links: 0,        // 0..1 — hairlines device → brain drawn
    guest: 0,        // the guest's line scan → brain
    scale: 1,        // room scale multiplier
    build: 1,        // 0..1 — how much of the room has been drawn yet (points appear in a sweep)
    wash: 0,         // 0..1 — fill the room's footprint with background so copy behind it recedes (slide 1, SP-style)
    rooms: 0,        // 0..1 — the eight neighbouring rooms stipple in around this one (slide 5)
    reach: 0,        // 0..1 — one guest's hairlines reach every room's Brain (slide 5, click)
  };
  const target = Object.assign({}, LEVELS);
  const level = Object.assign({}, LEVELS);
  const SPEED = { presence: 2.2, devicesLit: 1.4, brainLit: 2.5, links: 1.6, guest: 2.4, scale: 2.4, build: 1.1, wash: 2.0, rooms: 0.9, reach: 1.5 };

  /* ---------- build the point cloud once ---------- */
  function rnd(seed) { let s = seed >>> 0; return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; }
  const R = rnd(7);
  const pts = []; // [x, y, z, weight]
  function plane(count, fn, w) { for (let i = 0; i < count; i++) { const p = fn(R(), R()); pts.push([p[0], p[1], p[2], w * (0.6 + 0.4 * R())]); } }
  // Build order for the slide-1 reveal: a sweep from the left wall to the right, jittered so it reads as a stipple filling in.
  function order(p) { return Math.min(1, Math.max(0, (p[0] + ROOM.w / 2) / ROOM.w * 0.75 + R() * 0.25)); }
  const hw = ROOM.w / 2, hd = ROOM.d / 2;
  // floor: denser
  plane(3400, (u, v) => [-hw + u * ROOM.w, 0, -hd + v * ROOM.d], 0.55);
  // back wall and left/right walls: sparser, fading toward the top (so the room reads as open)
  plane(1500, (u, v) => [-hw + u * ROOM.w, v * v * ROOM.h, -hd], 0.42);
  plane(900, (u, v) => [-hw, v * v * ROOM.h, -hd + u * ROOM.d], 0.38);
  plane(900, (u, v) => [hw, v * v * ROOM.h, -hd + u * ROOM.d], 0.38);
  // floor edge + wall top edges as denser lines so the box reads. Edge points are tagged (p[5]) so distance
  // thinning can skip surface stipple but never break a line.
  const edge = (...ps) => { for (const q of ps) { q[5] = 1; pts.push(q); } };
  for (let i = 0; i < 420; i++) { const t = i / 420; edge([-hw + t * ROOM.w, 0, -hd, 0.9], [-hw + t * ROOM.w, 0, hd, 0.9], [-hw, 0, -hd + t * ROOM.d, 0.9], [hw, 0, -hd + t * ROOM.d, 0.9]); }
  for (let i = 0; i < 300; i++) { const t = i / 300; edge([-hw + t * ROOM.w, ROOM.h, -hd, 0.5], [-hw, ROOM.h, -hd + t * ROOM.d, 0.45], [hw, ROOM.h, -hd + t * ROOM.d, 0.45]); }
  for (let i = 0; i < 160; i++) { const t = i / 160; edge([-hw, t * ROOM.h, -hd, 0.7], [hw, t * ROOM.h, -hd, 0.7], [-hw, t * ROOM.h, hd, 0.6], [hw, t * ROOM.h, hd, 0.6]); }
  // furniture: points on the five visible faces of each box
  for (const b of FURNITURE) {
    const area = b.w * b.d + 2 * b.w * b.h + 2 * b.d * b.h;
    const n = Math.max(60, Math.round(area * 260));
    for (let i = 0; i < n; i++) {
      const r = R() * area; let p;
      if (r < b.w * b.d) p = [b.x + (R() - .5) * b.w, b.y + b.h, b.z + (R() - .5) * b.d];
      else if (r < b.w * b.d + b.w * b.h) p = [b.x + (R() - .5) * b.w, b.y + R() * b.h, b.z + b.d / 2];
      else if (r < b.w * b.d + 2 * b.w * b.h) p = [b.x + (R() - .5) * b.w, b.y + R() * b.h, b.z - b.d / 2];
      else if (r < b.w * b.d + 2 * b.w * b.h + b.d * b.h) p = [b.x + b.w / 2, b.y + R() * b.h, b.z + (R() - .5) * b.d];
      else p = [b.x - b.w / 2, b.y + R() * b.h, b.z + (R() - .5) * b.d];
      pts.push([p[0], p[1], p[2], 0.85]);
    }
    // box edges
    const ex = [b.x - b.w / 2, b.x + b.w / 2], ez = [b.z - b.d / 2, b.z + b.d / 2], ey = [b.y, b.y + b.h];
    for (let i = 0; i < 40; i++) {
      const t = i / 40;
      for (const z of ez) for (const y of ey) edge([ex[0] + t * b.w, y, z, 1]);
      for (const x of ex) for (const y of ey) edge([x, y, ez[0] + t * b.d, 1]);
      for (const x of ex) for (const z of ez) edge([x, b.y + t * b.h, z, 1]);
    }
  }

  for (const p of pts) { p[4] = order(p); p[6] = Math.floor(R() * 4); } // p[6]: thinning key, so distance thinning drops a random quarter/half, never a whole line

  /* ---------- state ---------- */
  let canvas, ctx, W = 0, H = 0, DPR = 1, raf = 0, last = 0, running = false;
  let shot = SHOTS.wide, cam = { theta: SHOTS.wide.theta, phi: SHOTS.wide.phi, dist: SHOTS.wide.dist, target: SHOTS.wide.target.slice(), ox: SHOTS.wide.offset[0], oy: SHOTS.wide.offset[1] };
  let driftAngle = 0, deviceCount = 3, pulseT = -1;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const css = (name, fallback) => (getComputedStyle(document.documentElement).getPropertyValue(name) || fallback).trim();
  let INK = "#f4eef7", PINK = "#f0a8e0", BG = "#1a1523";
  function readTokens() { INK = css("--fg", INK); PINK = css("--accent", PINK); BG = css("--bg", BG); }

  function damp(cur, to, speed, dt) { return cur + (to - cur) * (1 - Math.exp(-speed * dt)); }

  /* ---------- projection ---------- */
  let cx, cy, cz, fwd, right, up, f;
  function setupCamera() {
    const th = cam.theta + driftAngle, ph = cam.phi;
    cx = cam.target[0] + cam.dist * Math.cos(ph) * Math.sin(th);
    cy = cam.target[1] + cam.dist * Math.sin(ph);
    cz = cam.target[2] + cam.dist * Math.cos(ph) * Math.cos(th);
    const fx = cam.target[0] - cx, fy = cam.target[1] - cy, fz = cam.target[2] - cz, fl = Math.hypot(fx, fy, fz);
    fwd = [fx / fl, fy / fl, fz / fl];
    // right = forward × worldUp; up = right × forward (right-handed, y up)
    const rx = -fwd[2], rz = fwd[0], rl = Math.hypot(rx, rz); right = [rx / rl, 0, rz / rl];
    up = [right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2], right[0] * fwd[1] - right[1] * fwd[0]];
    f = Math.min(W, H) * 1.05 * level.scale;
  }
  function project(x, y, z) {
    const dx = x - cx, dy = y - cy, dz = z - cz;
    const zc = dx * fwd[0] + dy * fwd[1] + dz * fwd[2];
    if (zc <= 0.1) return null;
    const xc = dx * right[0] + dy * right[1] + dz * right[2];
    const yc = dx * up[0] + dy * up[1] + dz * up[2];
    return [W / 2 + cam.ox * W / 2 + xc * f / zc, H / 2 + cam.oy * H / 2 - yc * f / zc, zc];
  }

  /* ---------- draw ---------- */
  function hex2rgb(h) { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join(""); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; }
  function rgba(rgb, a) { return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`; }

  function frame(t) {
    if (!running) return;
    const dt = Math.min(0.05, (t - last) / 1000 || 0.016); last = t;
    if (document.hidden) { raf = requestAnimationFrame(frame); return; }

    // ease camera + levels
    const k = reduced ? 1e9 : 2.4;
    cam.theta = damp(cam.theta, shot.theta, k, dt); cam.phi = damp(cam.phi, shot.phi, k, dt); cam.dist = damp(cam.dist, shot.dist, k, dt);
    for (let i = 0; i < 3; i++) cam.target[i] = damp(cam.target[i], shot.target[i], k, dt);
    cam.ox = damp(cam.ox, shot.offset[0], k, dt); cam.oy = damp(cam.oy, shot.offset[1], k, dt);
    if (!reduced) driftAngle += shot.drift * dt;
    for (const key in level) {
      const sp = key === "rooms" && target.rooms === 0 ? 3.2 : SPEED[key]; // clones arrive slowly, leave quickly: the slide after must not pay for them
      level[key] = damp(level[key], target[key], reduced ? 1e9 : sp, dt);
    }
    if (pulseT >= 0) { pulseT += dt / 1.1; if (pulseT > 1.25) pulseT = -1; }

    setupCamera();
    ctx.clearRect(0, 0, W, H);
    const tDraw = performance.now();

    // --- the wash: the room's silhouette (convex hull of its eight corners) filled with background, so
    // whatever sits behind the canvas on this slide is dimmed where the room overlaps it. Grows with build.
    if (level.wash > 0.01) {
      const hull = roomHull();
      if (hull) {
        ctx.fillStyle = rgba(hex2rgb(BG), 0.58 * level.wash * Math.min(1, level.build * 1.2)); // copy stays legible through it, SP-style
        ctx.beginPath(); hull.forEach((q, i) => i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.closePath(); ctx.fill();
      }
    }

    // --- the room: thousands of squares. Depth → alpha so the far wall sits back.
    const ink = hex2rgb(INK);
    const near = cam.dist - 4.5, far = cam.dist + 4.5;
    const sq = Math.max(1.5, Math.round(DPR * 1.5)) / DPR;
    const buckets = new Array(8).fill(null).map(() => []);
    const far_ = cam.dist > 24; // far shots: every other surface point — the room is a quarter the size, full density is pure overdraw. Edges stay solid.
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i]; if (p[4] > level.build) continue;
      if (far_ && !p[5] && (p[6] & 1)) continue;
      const s = project(p[0], p[1], p[2]); if (!s) continue;
      const depth = Math.min(1, Math.max(0, (s[2] - near) / (far - near)));
      const a = p[3] * (0.62 - 0.42 * depth) * level.presence;
      buckets[Math.min(7, Math.floor(a * 8))].push(s[0], s[1]);
    }
    for (let b = 0; b < 8; b++) {
      const list = buckets[b]; if (!list.length) continue;
      ctx.fillStyle = rgba(ink, (b + 0.5) / 8 * 0.72);
      for (let i = 0; i < list.length; i += 2) ctx.fillRect(list[i], list[i + 1], sq, sq);
    }

    // --- the neighbouring rooms (slide 5): the same cloud, offset, each sweeping in a little after the last
    const cloneF = CLONES.map((c, k) => Math.min(1, Math.max(0, level.rooms * 1.7 - k * 0.09)));
    if (level.rooms > 0.02) {
      const cnear = cam.dist - 14, cfar = cam.dist + 14;
      for (let b = 0; b < 8; b++) buckets[b].length = 0;
      // clones are context, not the subject: a quarter of the surface stipple and half the edge points read the same at this distance
      for (let k = 0; k < CLONES.length; k++) {
        const fk = cloneF[k]; if (fk <= 0) continue;
        const c = CLONES[k];
        for (let i = 0; i < pts.length; i++) {
          const p = pts[i]; if (p[4] > fk) continue;
          if (p[5] ? (p[6] & 1) : p[6]) continue;
          const s = project(p[0] + c.ox, p[1], p[2] + c.oz); if (!s || s[0] < -2 || s[0] > W + 2 || s[1] < -2 || s[1] > H + 2) continue;
          const depth = Math.min(1, Math.max(0, (s[2] - cnear) / (cfar - cnear)));
          const a = p[3] * (0.6 - 0.4 * depth) * level.presence * (0.55 + 0.45 * fk);
          const b = Math.min(7, Math.floor(a * 8)); if (b === 0) continue; // < 1/8 alpha: invisible on the projector, not free to draw
          buckets[b].push(s[0], s[1]);
        }
      }
      for (let b = 0; b < 8; b++) {
        const list = buckets[b]; if (!list.length) continue;
        ctx.fillStyle = rgba(ink, (b + 0.5) / 8 * 0.72);
        for (let i = 0; i < list.length; i += 2) ctx.fillRect(list[i], list[i + 1], sq, sq);
      }
    }

    // --- links device → brain (hairlines that draw)
    const pink = hex2rgb(PINK);
    if (level.build < 0.98) { raf = requestAnimationFrame(frame); return; } // nodes and lines wait for the room to finish
    const brain = project(BRAIN[0], BRAIN[1], BRAIN[2]);
    const devs = DEVICE_SLOTS.slice(0, deviceCount).map(d => project(d[0], d[1], d[2]));
    if (brain && level.links > 0.005) {
      ctx.lineWidth = 1; ctx.lineCap = "round";
      devs.forEach((d, i) => {
        if (!d) return;
        const lit = Math.min(1, Math.max(0, level.devicesLit * deviceCount - i));
        const prog = Math.min(1, Math.max(0, level.links * 1.25 - i * 0.08)) * lit;
        if (prog <= 0) return;
        ctx.strokeStyle = rgba(pink, 0.42 * prog * level.presence);
        ctx.beginPath(); ctx.moveTo(d[0], d[1]); ctx.lineTo(d[0] + (brain[0] - d[0]) * prog, d[1] + (brain[1] - d[1]) * prog); ctx.stroke();
      });
    }
    // --- the guest's line: from the scan point to the brain
    const scan = project(SCAN_POINT[0], SCAN_POINT[1], SCAN_POINT[2]);
    if (scan && brain && level.guest > 0.005) {
      ctx.setLineDash([3, 5]); ctx.lineWidth = 1;
      ctx.strokeStyle = rgba(pink, 0.55 * level.guest * level.presence);
      ctx.beginPath(); ctx.moveTo(scan[0], scan[1]); ctx.lineTo(scan[0] + (brain[0] - scan[0]) * level.guest, scan[1] + (brain[1] - scan[1]) * level.guest); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = rgba(pink, 0.9 * level.guest * level.presence);
      ctx.beginPath(); ctx.arc(scan[0], scan[1], 3.5, 0, Math.PI * 2); ctx.fill();
    }

    // --- device nodes
    devs.forEach((d, i) => {
      if (!d) return;
      const lit = Math.min(1, Math.max(0, level.devicesLit * deviceCount - i));
      const base = 0.35 * level.presence, r = 2.2 + 2.6 * lit;
      ctx.fillStyle = lit > 0.02 ? rgba(pink, (base + 0.65 * lit) * level.presence) : rgba(ink, base);
      ctx.beginPath(); ctx.arc(d[0], d[1], r, 0, Math.PI * 2); ctx.fill();
      if (lit > 0.5) { ctx.strokeStyle = rgba(pink, 0.35 * lit * level.presence); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(d[0], d[1], r + 4, 0, Math.PI * 2); ctx.stroke(); }
    });
    // --- the brain
    if (brain && level.brainLit > 0.01) {
      const b = level.brainLit * level.presence;
      ctx.fillStyle = rgba(pink, 0.95 * b); ctx.beginPath(); ctx.arc(brain[0], brain[1], 3.5 + 2 * b, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = rgba(pink, 0.3 * b); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(brain[0], brain[1], 11, 0, Math.PI * 2); ctx.stroke();
    }
    // --- slide 5: each neighbour's devices and Brain light as it lands; labels; one guest reaching every room
    if (level.rooms > 0.02 && brain) {
      const lbl = Math.max(11, Math.min(26, f / cam.dist * 0.95));
      ctx.font = `700 ${lbl}px "Inter Tight", Inter, system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
      const brains = [brain];
      CLONES.forEach((c, k) => {
        const fk = cloneF[k]; if (fk <= 0) return;
        const lit = Math.max(0, fk * 1.6 - 0.6) * level.presence;   // nodes arrive once the room is mostly there
        DEVICE_SLOTS.slice(0, deviceCount).forEach(d => {
          const s = project(d[0] + c.ox, d[1], d[2] + c.oz); if (!s) return;
          ctx.fillStyle = rgba(pink, 0.35 + 0.6 * lit); ctx.beginPath(); ctx.arc(s[0], s[1], 1.6 + 1.8 * lit, 0, Math.PI * 2); ctx.fill();
        });
        const bb = project(BRAIN[0] + c.ox, BRAIN[1], BRAIN[2] + c.oz);
        if (bb) { brains.push(bb); ctx.fillStyle = rgba(pink, 0.9 * lit); ctx.beginPath(); ctx.arc(bb[0], bb[1], 2.2 + 1.6 * lit, 0, Math.PI * 2); ctx.fill(); }
        const lp = project(c.ox, 0, c.oz + hd + 0.5);
        if (lp) label(c.label, lp, ink, 0.85 * Math.max(0, fk * 1.4 - 0.4) * level.presence, lbl);
      });
      const hp = project(0, 0, hd + 0.5);
      if (hp) label("This room", hp, pink, 0.95 * Math.min(1, level.rooms * 2) * level.presence, lbl);
      // one guest, every room: dashed hairlines from a single far point to each Brain, nearest first
      const g = [W * FAR_GUEST[0], H * FAR_GUEST[1]];
      if (level.reach > 0.005) {
        ctx.setLineDash([4, 6]); ctx.lineWidth = 1.25;
        brains.forEach((b, k) => {
          const prog = Math.min(1, Math.max(0, level.reach * 1.35 - k * 0.04));
          if (prog <= 0) return;
          ctx.strokeStyle = rgba(pink, 0.75 * prog * level.presence);
          ctx.beginPath(); ctx.moveTo(g[0], g[1]); ctx.lineTo(g[0] + (b[0] - g[0]) * prog, g[1] + (b[1] - g[1]) * prog); ctx.stroke();
        });
        ctx.setLineDash([]);
        ctx.fillStyle = rgba(pink, 0.95 * level.reach * level.presence); ctx.beginPath(); ctx.arc(g[0], g[1], 5.5, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = rgba(pink, 0.4 * level.reach * level.presence); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(g[0], g[1], 14, 0, Math.PI * 2); ctx.stroke();
        label("One guest", [g[0], g[1] + 18], pink, 0.95 * level.reach * level.presence, lbl);
      }
    }

    // --- the pulse: scan → brain → first device, and the device flares
    if (pulseT >= 0 && scan && brain && devs[0]) {
      const a = pulseT < 0.5 ? [scan, brain, pulseT / 0.5] : [brain, devs[0], Math.min(1, (pulseT - 0.5) / 0.5)];
      const e = a[2] < 0.5 ? 2 * a[2] * a[2] : 1 - Math.pow(-2 * a[2] + 2, 2) / 2;
      const px = a[0][0] + (a[1][0] - a[0][0]) * e, py = a[0][1] + (a[1][1] - a[0][1]) * e;
      ctx.fillStyle = rgba(pink, 1); ctx.shadowColor = PINK; ctx.shadowBlur = 14;
      ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
      if (pulseT >= 1) { const fl = (pulseT - 1) / 0.25; ctx.strokeStyle = rgba(pink, 0.8 * (1 - fl)); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(devs[0][0], devs[0][1], 6 + 26 * fl, 0, Math.PI * 2); ctx.stroke(); }
    }

    drawMs = drawMs * 0.9 + (performance.now() - tDraw) * 0.1;
    raf = requestAnimationFrame(frame);
  }
  let drawMs = 0;

  // a label on a dark pill so it reads over the stipple behind it
  function label(text, at, rgb, a, px) {
    if (a <= 0.01) return;
    const w = ctx.measureText(text).width + px * 0.9, h = px * 1.5, x = at[0] - w / 2, y = at[1] - px * 0.1;
    ctx.fillStyle = rgba(hex2rgb(BG), 0.82 * a); ctx.beginPath(); ctx.roundRect(x, y, w, h, h / 2); ctx.fill();
    ctx.fillStyle = rgba(rgb, a); ctx.fillText(text, at[0], y + px * 0.28);
  }

  function roomHull() {
    const c = [];
    for (const x of [-hw, hw]) for (const y of [0, ROOM.h]) for (const z of [-hd, hd]) { const s = project(x, y, z); if (!s) return null; c.push(s); }
    c.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], hi = [];
    for (const q of c) { while (lo.length > 1 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (let i = c.length - 1; i >= 0; i--) { const q = c[i]; while (hi.length > 1 && cross(hi[hi.length - 2], hi[hi.length - 1], q) <= 0) hi.pop(); hi.push(q); }
    return lo.slice(0, -1).concat(hi.slice(0, -1));
  }

  function resize() {
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  window.Stage = {
    mount(el) {
      canvas = el; ctx = canvas.getContext("2d", { alpha: true });
      readTokens(); resize(); window.addEventListener("resize", resize);
      running = true; last = performance.now(); raf = requestAnimationFrame(frame);
    },
    shot(name) { if (SHOTS[name]) shot = SHOTS[name]; },
    set(k, v) { if (k in target) target[k] = v; },
    jump(k, v) { if (k in target) { target[k] = v; level[k] = v; } },
    pulse() { pulseT = 0; },
    stats() { return { drawMs: +drawMs.toFixed(2), points: pts.length, rooms: level.rooms }; }, // smoothed JS draw time per frame
    settle() { // jump camera + levels to their targets (for stills / tests)
      cam.theta = shot.theta; cam.phi = shot.phi; cam.dist = shot.dist; cam.target = shot.target.slice(); cam.ox = shot.offset[0]; cam.oy = shot.offset[1];
      for (const k in level) level[k] = target[k];
      if (pulseT >= 0) pulseT = 1.05;
    },
    setDeviceCount(n) { deviceCount = Math.max(1, Math.min(DEVICE_SLOTS.length, n | 0)); },
    shots: Object.keys(SHOTS),
  };
})();
