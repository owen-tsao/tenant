import { build } from 'esbuild';
import { cp, mkdir } from 'node:fs/promises';

await mkdir(new URL('./dist/', import.meta.url), { recursive: true });
await build({
  entryPoints: [new URL('./main.tsx', import.meta.url).pathname],
  outfile: new URL('./dist/orb.js', import.meta.url).pathname,
  bundle: true, minify: true, format: 'iife', target: 'safari17', jsx: 'automatic',
  loader: { '.png': 'dataurl' },
  define: { 'process.env.NODE_ENV': '"production"' },
  banner: { js: 'try {' },
  footer: { js: '} catch (error) { window.webkit?.messageHandlers?.tenantOrb?.postMessage({type:"error",message:String(error)+" "+String(error.stack)}); }' },
});
for (const file of ['index.html', 'style.css']) {
  await cp(new URL('./' + file, import.meta.url), new URL('./dist/' + file, import.meta.url));
}
await cp(new URL('./public/perlin.png', import.meta.url), new URL('./dist/perlin.png', import.meta.url));
