'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { bootstrapPhotoViewer } = require('../agent/photo_viewer.js');
const SECRET = 'private-bootstrap-test-token';
const json = (value, status = 200) => ({ ok: status === 200, status, json: async () => value });
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function harness({ cookie = json({ ok: true }), stored = '', result = { active: true, phase: 'waiting' } } = {}) {
  const nodes = Object.fromEntries(['tenant-photo-viewer', 'connect', 'credential', 'connect-button', 'status', 'photo'].map(id =>
    [id, { hidden: id === 'connect', value: '', textContent: '', disabled: false, events: {}, addEventListener(name, fn) { this.events[name] = fn; } }]));
  const events = {}, fetches = [], starts = [], instances = [];
  let reads = 0, writes = 0;
  const replies = [cookie];
  const env = {
    document: { getElementById: id => nodes[id] },
    localStorage: { getItem(key) { assert.equal(key, 'tenant.host_token'); reads++; return stored; }, setItem() { writes++; throw new Error('No storage writes'); } },
    addEventListener(name, fn) { events[name] = fn; },
    async fetch(url, init) { fetches.push({ url, init }); return await (replies.length ? replies.shift() : json({ ok: true })); }
  };
  const makeViewer = options => {
    const instance = { options, stops: 0, async start(args) {
      const token = args.enroll ? options.getHostToken() : null;
      starts.push({ args, token, viewerId: options.viewerId });
      return typeof result === 'function' ? result() : result;
    }, stop() { this.stops++; } };
    instances.push(instance); return instance;
  };
  const boot = bootstrapPhotoViewer(env, makeViewer);
  return { boot, env, nodes, events, fetches, starts, instances, replies, get reads() { return reads; }, get writes() { return writes; } };
}
test('valid cookie starts without enrollment or reading host credential', async () => {
  const h = harness({ stored: SECRET }); await h.boot.ready;
  assert.deepEqual(h.starts, [{ args: { enroll: false }, token: null, viewerId: 'tenant-mac-viewer' }]);
  assert.equal(h.reads, 0); assert.equal(h.writes, 0); assert.equal(h.nodes.connect.hidden, true);
  assert.equal(h.fetches[0].url, '/photos/viewer/state');
  assert.equal(h.fetches[0].init.credentials, 'same-origin'); assert.equal(h.fetches[0].init.redirect, 'error');
  assert.ok(!JSON.stringify(h.nodes).includes(SECRET));
});
test('definite cookie rejection reuses existing host credential once without storing it', async () => {
  const h = harness({ cookie: json({ ok: false }, 403), stored: SECRET }); await h.boot.ready;
  assert.equal(h.starts.length, 1); assert.equal(h.starts[0].args.enroll, true); assert.equal(h.starts[0].token, SECRET);
  assert.equal(h.writes, 0); assert.equal(h.nodes.credential.value, ''); assert.ok(!JSON.stringify(h.nodes).includes(SECRET));
});
test('missing stored credential shows a private explicit connect form', async () => {
  const h = harness({ cookie: json({ ok: false }, 403) }); await h.boot.ready;
  assert.equal(h.starts.length, 0); assert.equal(h.nodes.connect.hidden, false);
  h.nodes.credential.value = SECRET;
  let prevented = false; h.nodes.connect.events.submit({ preventDefault() { prevented = true; } }); await tick();
  assert.equal(prevented, true); assert.equal(h.starts[0].args.enroll, true); assert.equal(h.starts[0].token, SECRET);
  assert.equal(h.nodes.credential.value, ''); assert.equal(h.writes, 0);
});
for (const status of [500, 401, 404]) test('HTTP ' + status + ' does not automatically rotate viewer enrollment', async () => {
  const h = harness({ cookie: json({ ok: false }, status), stored: SECRET }); await h.boot.ready;
  assert.equal(h.starts.length, 0); assert.equal(h.reads, 0); assert.equal(h.nodes.connect.hidden, false);
});
test('network failure and malformed probe do not automatically enroll', async () => {
  for (const reply of [Promise.reject(new Error(SECRET)), json({ nope: SECRET })]) {
    const h = harness({ cookie: reply, stored: SECRET }); await h.boot.ready;
    assert.equal(h.starts.length, 0); assert.equal(h.reads, 0); assert.ok(!JSON.stringify(h.nodes).includes(SECRET));
  }
});
test('failed enrollment does not claim connected and clears typed secret', async () => {
  const h = harness({ cookie: json({ ok: false }, 403), result: { active: false, phase: 'unavailable' } }); await h.boot.ready;
  h.nodes.credential.value = SECRET; h.nodes.connect.events.submit({ preventDefault() {} }); await tick();
  assert.equal(h.nodes.connect.hidden, false); assert.equal(h.nodes.credential.value, '');
  assert.match(h.nodes.status.textContent, /unavailable/); assert.equal(h.instances[0].stops, 1);
});
test('page departure disposes viewer and aborts pending cookie probe', async () => {
  const pending = deferred(), h = harness({ cookie: pending.promise, stored: SECRET });
  h.nodes.credential.value = SECRET; h.events.pagehide();
  assert.equal(h.fetches[0].init.signal.aborted, true); assert.equal(h.nodes.credential.value, '');
  pending.resolve(json({ ok: false }, 403)); await h.boot.ready;
  assert.equal(h.starts.length, 0); assert.equal(h.reads, 0);
});
test('back-forward restore uses fresh cookie-first bootstrap and subsequent departure cleans again', async () => {
  const h = harness({ stored: SECRET }); await h.boot.ready;
  h.events.pagehide(); assert.equal(h.instances[0].stops, 1);
  h.events.pageshow({ persisted: true }); await tick();
  assert.equal(h.fetches.length, 2); assert.equal(h.instances.length, 2);
  assert.deepEqual(h.starts.map(x => x.args), [{ enroll: false }, { enroll: false }]); assert.equal(h.reads, 0);
  h.events.pagehide(); assert.equal(h.instances[1].stops, 1);
});
test('late pre-departure enrollment result cannot mutate restored lifecycle', async () => {
  const pending = deferred(); let count = 0;
  const h = harness({ cookie: json({ ok: false }, 403), stored: SECRET,
    result: () => ++count === 1 ? pending.promise : { active: true, phase: 'waiting' } });
  await tick(); assert.equal(h.starts.length, 1);
  h.events.pagehide(); h.events.pageshow({ persisted: true }); await tick();
  pending.resolve({ active: false, phase: 'unavailable' }); await h.boot.ready; await tick();
  assert.equal(h.nodes.connect.hidden, true); assert.match(h.nodes.status.textContent, /connected/);
  assert.equal(h.instances[1].stops, 0);
});
test('HTML follows external-script CSP and has a password field, empty image mount, no public photo', () => {
  const html = fs.readFileSync(__dirname + '/../agent/photo_viewer.html', 'utf8');
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  assert.equal(scripts.length, 1); assert.match(scripts[0][1], /src="\/photos\/viewer\.js"/); assert.equal(scripts[0][2].trim(), '');
  assert.match(html, /type="password"/); assert.match(html, /id="photo"[^>]*><\/div>/);
  assert.ok(!/<img\b/.test(html)); assert.ok(!html.includes(SECRET));
});
test('browser script does not start a viewer on unrelated pages', () => {
  const src = fs.readFileSync(__dirname + '/../agent/photo_viewer.js', 'utf8');
  let fetches = 0;
  vm.runInNewContext(src, { document: { readyState: 'complete', getElementById: () => null }, fetch() { fetches++; } });
  assert.equal(fetches, 0);
});
