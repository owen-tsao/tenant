// This clock only expires received samples. It never invents a beat or audio.
export function createSignal(now = () => performance.now()) {
  let latest = null;
  return {
    sample(value) {
      if (!value || typeof value.playing !== 'boolean' ||
          !Number.isFinite(value.playhead_seconds) || value.playhead_seconds < 0 ||
          !Number.isFinite(value.level) || value.level < 0 || value.level > 1) return false;
      latest = { ...value, received: now() };
      return true;
    },
    current() {
      const fresh = latest !== null && now() - latest.received <= 750;
      return {
        visible: Boolean(fresh && latest.playing),
        level: fresh && latest.playing ? latest.level : 0,
        playhead_seconds: fresh ? latest.playhead_seconds : null,
      };
    },
  };
}
