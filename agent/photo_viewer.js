/* Isolated candidate: private photo transport/rendering; no startup on import. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.TenantPhotoViewer = api;
    if (root.document) {
      const boot = () => api.bootstrapPhotoViewer(root);
      if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', boot, { once: true });
      else boot();
    }
  }
})(typeof globalThis === 'object' ? globalThis : this, function (root) {
  'use strict';
  const MAX_BYTES = 5 * 1024 * 1024;
  const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_.-]{1,128}$/.test(value);
  const version = value => Number.isSafeInteger(value) && value >= 0;

  function visibleImage(image, mount) {
    const doc = image.ownerDocument;
    const view = doc && doc.defaultView;
    if (!doc || doc.visibilityState !== 'visible' || !view || !mount.isConnected || !image.isConnected) return false;
    for (let element = image; element && element.nodeType === 1; element = element.parentElement) {
      const style = view.getComputedStyle(element);
      if (style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) === 0) return false;
    }
    const rect = image.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < view.innerWidth && rect.top < view.innerHeight;
  }

  function createPhotoViewer(options) {
    const { viewerId, mount } = options;
    if (!identifier(viewerId) || !mount || typeof mount.replaceChildren !== 'function') throw new TypeError('Invalid viewer configuration');
    const fetcher = options.fetch || root.fetch.bind(root);
    const doc = options.document || root.document;
    const makeImage = options.createImage || (() => new root.Image());
    const makeURL = options.createObjectURL || (blob => root.URL.createObjectURL(blob));
    const revokeURL = options.revokeObjectURL || (url => root.URL.revokeObjectURL(url));
    const raf = options.requestAnimationFrame || root.requestAnimationFrame.bind(root);
    const cancelRAF = options.cancelAnimationFrame || root.cancelAnimationFrame.bind(root);
    const later = options.setTimeout || root.setTimeout.bind(root);
    const cancelLater = options.clearTimeout || root.clearTimeout.bind(root);
    const isVisible = options.isVisible || visibleImage;
    const getHostToken = options.getHostToken || (() => null);
    let active = false, disposed = false, phase = 'idle', stateVersion = -1, stateKey = null, photo = null, photoPending = false;
    let epoch = 0, timer = null, pollTask = null, pollAbort = null, renderTask = null, renderAbort = null;
    let retained = null, staged = null;
    let stateReads = 0;
    const receiptAttempts = new Set();
    const urls = new Set();

    function status() {
      return { active, phase, stateVersion, photoId: photo ? photo.photo_id : null,
        photoVersion: photo ? photo.version : null };
    }
    function request(path, init = {}) {
      return fetcher(path, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', ...init });
    }
    function release(url) {
      if (url && urls.delete(url)) revokeURL(url);
    }
    function restore() {
      if (staged) {
        if (retained) mount.replaceChildren(retained.image);
        else mount.replaceChildren();
        release(staged.url);
        staged = null;
      }
    }
    function invalidateRender() {
      epoch += 1;
      if (renderAbort) renderAbort.abort();
      renderAbort = null;
      restore();
    }
    function clearImage() {
      invalidateRender();
      mount.replaceChildren();
      if (retained) release(retained.url);
      retained = null;
    }
    function frame(signal) {
      return new Promise((resolve, reject) => {
        if (signal.aborted) return reject(new Error('Cancelled'));
        let id;
        const abort = () => { cancelRAF(id); reject(new Error('Cancelled')); };
        signal.addEventListener('abort', abort, { once: true });
        id = raf(() => { signal.removeEventListener('abort', abort); resolve(); });
      });
    }
    function current(generation, signal) { return active && generation === epoch && !signal.aborted; }
    async function refreshCurrent(generation, signal) {
      if (pollTask) await pollTask;
      if (!current(generation, signal)) return false;
      const previous = stateReads;
      await pollOnce();
      return current(generation, signal) && stateReads > previous;
    }
    function visibilityChanged() {
      if (doc.visibilityState !== 'visible') {
        invalidateRender();
        if (active) phase = 'waiting';
      }
    }
    async function render(candidate, generation, controller, reconcile = false) {
      const signal = controller.signal;
      const key = candidate.photo_id + ':' + candidate.version;
      let url = null;
      try {
        const response = await request(candidate.image_url, { signal, headers: { Accept: 'image/jpeg' } });
        if (!current(generation, signal)) return;
        if (!response.ok || response.redirected ||
            (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase() !== 'image/jpeg') throw new Error('Image unavailable');
        const blob = await response.blob();
        if (!current(generation, signal)) return;
        if (!blob.size || blob.size > MAX_BYTES) throw new Error('Image unavailable');
        url = makeURL(blob);
        urls.add(url);
        const image = makeImage();
        image.alt = 'Room photo';
        image.decoding = 'async';
        image.src = url;
        await image.decode();
        if (!current(generation, signal)) return;
        if (!(image.naturalWidth > 0 && image.naturalHeight > 0) || doc.visibilityState !== 'visible') throw new Error('Rendering unavailable');
        if (!await refreshCurrent(generation, signal)) throw new Error('Rendering unavailable');
        staged = { image, url, key };
        mount.replaceChildren(image);
        phase = 'rendering';
        if (!isVisible(image, mount)) throw new Error('Rendering unavailable');
        await frame(signal);
        await frame(signal);
        if (!current(generation, signal)) return;
        if (!isVisible(image, mount)) throw new Error('Rendering unavailable');
        if (!await refreshCurrent(generation, signal)) throw new Error('Rendering unavailable');
        if (reconcile) {
          // A lost receipt response is resolved only by fresh authoritative
          // state naming this exact image as retained latest, never another POST.
          if (photoPending) throw new Error('Receipt unconfirmed');
          if (retained) release(retained.url);
          retained = staged;
          staged = null;
          url = null;
          phase = 'displayed';
          return;
        }
        // A decoded visible image plus paint opportunities is a software render
        // receipt, not independent evidence of physical pixels on a named Mac.
        receiptAttempts.add(key);  // Never automatically repeat an uncertain POST.
        const receipt = await request('/photos/viewer/receipt', {
          method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ photo_id: candidate.photo_id, version: candidate.version })
        });
        if (!current(generation, signal)) return;
        if (!receipt.ok || receipt.redirected) throw new Error('Receipt unconfirmed');
        const result = await receipt.json();
        if (!current(generation, signal)) return;
        if (result.ok !== true || result.state !== 'displayed' || result.photo_id !== candidate.photo_id ||
            result.version !== candidate.version) throw new Error('Receipt unconfirmed');
        if (retained) release(retained.url);
        retained = staged;
        staged = null;
        url = null;
        phase = 'displayed';
      } catch (_) {
        if (current(generation, signal)) {
          restore();
          phase = receiptAttempts.has(key) ? 'unconfirmed' : 'unavailable';
        }
      } finally {
        if (url && (!retained || retained.url !== url) && (!staged || staged.url !== url)) release(url);
        if (renderAbort === controller) renderAbort = null;
      }
    }
    function acceptState(value) {
      if (!value || value.ok !== true || !version(value.version) || typeof value.pending !== 'boolean') throw new Error('Invalid state');
      const candidate = value.photo;
      if (candidate !== null && (!candidate || !identifier(candidate.photo_id) || !version(candidate.version) ||
          candidate.image_url !== '/photos/images/' + candidate.photo_id)) throw new Error('Invalid state');
      if (value.version < stateVersion) return;
      const key = value.version + ':' + (candidate ? candidate.photo_id + ':' + candidate.version : 'null');
      if (value.version === stateVersion && stateKey !== key) throw new Error('Invalid state');
      if (key !== stateKey) {
        invalidateRender();
        stateVersion = value.version;
        stateKey = key;
        photo = candidate;
      }
      photoPending = value.pending;
      if (candidate === null) {
        clearImage();
        phase = 'waiting';
        return;
      }
      if (retained && retained.key === candidate.photo_id + ':' + candidate.version) return;
      const photoKey = candidate.photo_id + ':' + candidate.version;
      const reconcile = receiptAttempts.has(photoKey);
      if (reconcile && value.pending) return;
      if (renderAbort || doc.visibilityState !== 'visible') return;
      phase = 'loading';
      const controller = renderAbort = new AbortController();
      const generation = epoch;
      renderTask = render(candidate, generation, controller, reconcile);
    }
    async function pollOnce() {
      if (!active) return status();
      if (pollTask) return pollTask;
      const generation = epoch;
      const controller = pollAbort = new AbortController();
      pollTask = (async () => {
        try {
          const response = await request('/photos/viewer/state', { signal: controller.signal, headers: { Accept: 'application/json' } });
          if (!active || controller.signal.aborted) return status();
          if (!response.ok || response.redirected) throw new Error('State unavailable');
          const value = await response.json();
          if (!active || controller.signal.aborted) return status();
          acceptState(value);
          if (value.version === stateVersion) stateReads += 1;
        } catch (_) {
          if (active && !controller.signal.aborted && generation === epoch) phase = 'unavailable';
        }
        return status();
      })();
      try { return await pollTask; }
      finally { if (pollAbort === controller) pollAbort = null; pollTask = null; }
    }
    function schedule() {
      if (!active) return;
      timer = later(async () => { timer = null; await pollOnce(); schedule(); }, 1000);
    }
    async function start({ enroll = false } = {}) {
      if (active || disposed) return status();
      active = true;
      phase = enroll ? 'enrolling' : 'waiting';
      doc.addEventListener('visibilitychange', visibilityChanged);
      if (enroll) {
        try {
          const token = getHostToken();
          if (typeof token !== 'string' || !token.trim() || token.length > 512) throw new Error('Enrollment unavailable');
          const controller = pollAbort = new AbortController();
          const response = await request('/host/photos/viewer', { method: 'POST', signal: controller.signal,
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
            body: JSON.stringify({ viewer_id: viewerId }) });
          if (!active || controller.signal.aborted) return status();
          if (!response.ok || response.redirected) throw new Error('Enrollment unavailable');
          const result = await response.json();
          if (!active || controller.signal.aborted) return status();
          if (result.ok !== true || result.viewer_id !== viewerId) throw new Error('Enrollment unavailable');
          pollAbort = null;
        } catch (_) {
          if (active) { active = false; phase = 'unavailable'; doc.removeEventListener('visibilitychange', visibilityChanged); }
          return status();
        }
      }
      await pollOnce();
      schedule();
      return status();
    }
    function stop() {
      active = false;
      disposed = true;
      if (timer !== null) cancelLater(timer);
      timer = null;
      if (pollAbort) pollAbort.abort();
      doc.removeEventListener('visibilitychange', visibilityChanged);
      clearImage();
      for (const url of [...urls]) release(url);
      phase = 'stopped';
    }
    return { start, pollOnce, stop, status, whenIdle: async () => { if (renderTask) await renderTask; } };
  }
  function bootstrapPhotoViewer(env = root, makeViewer = createPhotoViewer) {
    const doc = env.document;
    if (!doc || !doc.getElementById('tenant-photo-viewer')) return null;
    const viewerId = 'tenant-mac-viewer';
    const form = doc.getElementById('connect');
    const credential = doc.getElementById('credential');
    const button = doc.getElementById('connect-button');
    const label = doc.getElementById('status');
    const mount = doc.getElementById('photo');
    let viewer = null, busy = false, closed = false, lifecycle = 0, probeAbort = null;
    const current = generation => !closed && lifecycle === generation;
    function storedCredential() {
      try { return env.localStorage.getItem('tenant.host_token') || ''; }
      catch (_) { return ''; }
    }
    async function connect(enroll, generation = lifecycle) {
      if (busy || !current(generation)) return;
      busy = true;
      button.disabled = true;
      if (viewer) viewer.stop();
      const instance = viewer = makeViewer({ viewerId, mount, getHostToken: () => {
        if (!current(generation)) return null;
        const value = credential.value || storedCredential();
        credential.value = '';
        return value;
      } });
      try {
        const result = await instance.start({ enroll });
        if (!current(generation) || viewer !== instance) return;
        if (!result.active || result.phase === 'unavailable') throw new Error('Unavailable');
        form.hidden = true;
        label.textContent = 'Private viewer connected. Waiting for a photo.';
      } catch (_) {
        if (!current(generation) || viewer !== instance) return;
        instance.stop();
        form.hidden = false;
        label.textContent = 'Private viewer unavailable. Connect with the existing host credential.';
      } finally {
        if (current(generation)) {
          credential.value = '';
          busy = false;
          button.disabled = false;
        }
      }
    }
    async function bootstrap(generation) {
      const controller = probeAbort = new AbortController();
      try {
        const response = await env.fetch('/photos/viewer/state', {
          signal: controller.signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
          headers: { Accept: 'application/json' }
        });
        if (!current(generation) || controller.signal.aborted) return;
        if (response.ok && !response.redirected) {
          const value = await response.json();
          if (!current(generation) || controller.signal.aborted) return;
          if (!value || value.ok !== true) throw new Error('Unavailable');
          await connect(false, generation);
          return;
        }
        // Only definite authorization rejection permits deliberate enrollment.
        if (response.status !== 403) throw new Error('Unavailable');
        if (storedCredential()) await connect(true, generation);
        else {
          form.hidden = false;
          label.textContent = 'Connect with the existing host credential.';
        }
      } catch (_) {
        if (current(generation)) {
          form.hidden = false;
          label.textContent = 'Private viewer unavailable. Connect with the existing host credential.';
        }
      } finally {
        if (probeAbort === controller) probeAbort = null;
      }
    }
    form.addEventListener('submit', event => { event.preventDefault(); connect(true); });
    env.addEventListener('pagehide', () => {
      closed = true;
      lifecycle += 1;
      busy = false;
      credential.value = '';
      if (probeAbort) probeAbort.abort();
      if (viewer) viewer.stop();
      viewer = null;
    });
    env.addEventListener('pageshow', event => {
      if (!event.persisted) return;
      closed = false;
      lifecycle += 1;
      busy = false;
      credential.value = '';
      form.hidden = true;
      label.textContent = 'Connecting private photo viewer…';
      bootstrap(lifecycle);
    });
    return { ready: bootstrap(lifecycle) };
  }
  return { createPhotoViewer, bootstrapPhotoViewer };
});
