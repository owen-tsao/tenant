# Tenant live orb

Uses Jay's supplied `agent-orb/orb.tsx` and `perlin.png` (downloaded from his Antibody project, originally from 21st.dev). This is the supplied shader, not a rendered movie. Keep its upstream provenance; no new upstream license is asserted here.

The local adaptations embed the supplied noise texture for reliable offline loading, expose the renderer for a real WebGL draw receipt, and connect the component's existing manual volume refs to samples from the owned music player. The shader and default palette are unchanged. This is isolated from Owen's `web/` pages.

Build from the repository root:

```sh
npm ci --prefix agent/orb
npm run --prefix agent/orb build
mkdir -p .venv/orb
swiftc agent/orb_host.swift -o .venv/orb/TenantOrb -framework AppKit -framework WebKit
```

The native host uses AppKit + WKWebView. It opens an 820-point maximum, transparent, borderless, click-through window centered on the external display (main display if none). It does not activate fullscreen, move existing windows, play audio, request a microphone, or change output or volume. macOS WebKit's `drawsBackground` flag is needed in addition to CSS transparency; this local prototype uses that WebKit flag through KVC, so verify compatibility on a different Mac.

Only the owning audio bridge launches it:

```text
.venv/orb/TenantOrb --assets /absolute/path/to/agent/orb/dist
```

Input: newline-delimited JSON objects `{playhead_seconds, level, playing}` on stdin. Output: one real-render readiness receipt `{type:"ready", webgl:true, transparent:true, width, height, x, y}` on stdout. No local HTTP port, public token, audio capture, or second audio player. The source playhead and verified recording energy are supplied by the owning bridge.

The orb fades when playback pauses or samples become older than 750 ms. The native window exits after three seconds without samples, stdin EOF, or a renderer error. Hiding the orb leaves music and lights running; stopping its owned song/access closes it.

For isolated QA only, `--snapshot /absolute/probe.png --seconds 8` writes a native WebKit snapshot and exits within the requested interval (maximum 60 seconds). These flags are never exposed to a guest.

Scope: an already playing **managed, selected recording**. Arbitrary browser/Spotify audio is not analyzed by this path. The animation's fluid motion is generated live; its energy input follows the player's actual audio playhead. This is not a measured optical/acoustic phase calibration, and it does not control the TV's hardware backlight.

Checks: `npm test --prefix agent/orb` tests attachment position, pause, stale samples and rejected input. Python tests cover source identity, owned attachment/hide/cleanup and program authority. Native shader/alpha checks and actual guest UI acceptance are separate evidence.
