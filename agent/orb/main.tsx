import { useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { Orb } from './orb';
import { createSignal } from './signal.mjs';

const signal = createSignal();
function report(value: object) {
  (window as any).webkit?.messageHandlers?.tenantOrb?.postMessage(value);
}
(window as any).tenantOrb = { sample: (value: object) => signal.sample(value) };
window.addEventListener('error', (event) => report({ type: 'error', message: String(event.message).slice(0, 500) }));
window.addEventListener('unhandledrejection', (event) => report({ type: 'error', message: String(event.reason).slice(0, 500) }));

function App() {
  const container = useRef<HTMLDivElement>(null);
  const level = useRef(0);
  useEffect(() => {
    let frame = 0, ready = false;
    const update = () => {
      const current = signal.current();
      level.current = current.level;
      if (container.current) container.current.style.opacity = current.visible ? '1' : '0';
      const canvas = document.querySelector('canvas');
      const context = canvas?.getContext('webgl2') ?? canvas?.getContext('webgl');
      // A real draw, not merely an allocated canvas, confirms shader compilation.
      const renderer = (window as any).tenantOrbRenderer;
      if (!ready && context && !context.isContextLost() && renderer?.info.render.calls > 0) {
        ready = true;
        report({ type: 'ready', webgl: true, transparent: context.getContextAttributes()?.alpha === true });
      }
      frame = requestAnimationFrame(update);
    };
    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, []);
  return <div className="orb" ref={container}>
    <Orb seed={7} volumeMode="manual" inputVolumeRef={level} outputVolumeRef={level} />
  </div>;
}

createRoot(document.getElementById('root')!, {
  onUncaughtError: (error) => report({ type: 'error', message: String(error).slice(0, 500) }),
}).render(<App />);
