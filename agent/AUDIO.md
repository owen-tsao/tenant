# Room audio agent

Feature 2 only. Runs on the room Mac, independently of the Brain host. Computer
speakers are sufficient. Always use the Mac’s currently selected default output;
Jay explicitly requested no automatic output switching. An already paired Bluetooth output uses normal macOS
routing; this agent does not discover or pair speakers. Nothing here implements
slides, scenes, photos, guest authorization or reset policy.

## Start on the Mac

Use Python 3.12 and the project's `websockets` dependency (`websockets>=14` supports
the imported asyncio client; tested environment has 16.0). No new package beyond
that existing dependency. No `.env` is opened by the agent. Supply the same device
token and current room code used by the Brain in the process environment without
printing them or putting secrets in command history.

1. Choose the Mac's speakers in System Settings > Sound > Output. Unmute manually
   and set a modest volume. Hardware with fixed volume may reject `volume`.
2. For music, import an existing local audio file you are entitled to use into
   Music and put it in a playlist named `Tenant`. This requires no subscription,
   streaming account, download, API key or configured prior library. Without
   prepared local media the agent advertises speech/volume only.
3. Configure the process environment:

```bash
export TENANT_WS_URL='ws://127.0.0.1:8000/ws/device'
export ROOM_CODE='7F3A'
export TENANT_MUSIC_PLAYLIST='Tenant'
# DEVICE_TOKEN: supply securely from the coordinator's existing environment.
# For a deployed Brain use wss://YOUR_HOST/ws/device.
python agent/laptop.py --check
python agent/laptop.py
```

Optional `TENANT_DEVICE_ID` (default `laptop`) and `TENANT_DEVICE_LABEL` (default
`Room speaker`) distinguish two Macs. Never enroll two processes with the same ID.
The agent does not load environment files or display the authenticated URL.

`--check` reads Music state and may show the macOS Automation consent dialog. It
does not play audio or change volume. Allow Terminal/Python to control Music in
Privacy & Security > Automation if prompted, then rerun the check. An absent app,
missing playlist, empty library, missing first local file or rejected permission omits music capabilities
and prints a recommendation rather than claiming readiness.

## Capability manifest and contract

Uses ARCHITECTURE.md §3 without changing frames: authenticated `/ws/device?t=...`,
hello on every connect, pong to JSON ping, `do` → req-correlated `ok`/`err`.

| Capability | Args | Availability / result |
|---|---|---|
| `music.play` | `{}` | Configured Music playlist with local file tracks; plays its first local track, checks its location and reported `playing` state |
| `music.pause` | `{}` | Same music readiness gate; pauses Music and checks reported `paused` or already `stopped` state |
| `volume` | `{"level":25}` | macOS + osascript; integer 0–100; checks reported output volume; does not unmute |
| `say` | `{"text":"Hello from Tenant."}` | macOS + `/usr/bin/say` and `/usr/bin/afplay`; renders a private temporary file and plays it once through the default output, then removes it |

Unexpected or extra args are errors. The manifest describes the prepared song;
it makes no promise of arbitrary music search. Cloud-only tracks do not qualify.
Every successful result contains `audible_verified:false`: the OS accepting an
instruction or reporting playing is evidence of command completion, not proof of
audible sound. Check output routing/mute physically. Speech uses the caller's
lease-bounded deadline (the reply path allows up to 15 seconds). It renders
explicit AIFF/PCM, reads the actual clip duration, and refuses playback unless
the remaining budget covers that duration plus startup and receipt allowance.
The player receives the remaining budget less the receipt allowance. Other OS
controls retain min(remaining request budget, four seconds). Subprocesses are
killed/reaped by subprocess.run on timeout and run off the asyncio event loop. An Apple event already delivered
to Music can still have taken effect even if its sender times out.
Executor scheduling time counts against the request budget: a worker which starts
after the deadline refuses the action before invoking the dispatcher.

Direct `say` playback returned success but was inaudible in two actual tests, so
speech is rendered first and played with `afplay`. Both steps share one deadline;
expiry before playback starts sends no audio, while playback timeout is UNKNOWN
and is not retried. Human audible acceptance of this replacement is required.
Tests must preserve Jay’s chosen volume unless he explicitly requests a change.

## Conversation reply voice

Each new guest/controller starts text-only. The native helper's `reply-voice`
operation enables brief future replies only after an explicit guest request and
selection of one exact enrolled, say-capable speaker connection. A newly enrolled
bridge may be offered once in the next genuine turn; discovery never enables
speech. Reconnection requires a fresh choice. There is no OS/Bluetooth route
observer; output and volume remain those already selected on the Mac.

Opt-out, revoked access and a new guest fence queued unsent narration. Already
started speech may finish. Requested one-off `say` remains available without
enabling future replies and suppresses automatic narration of that same turn,
including after UNKNOWN. Text delivery precedes optional reply audio. Synthetic
acceptance is in `tests/test_reply_voice_acceptance.py`; it explicitly drives
helper choices and does not prove natural-language consent recognition or hearing.

## Selected real recording and phone beat timing

The optional song adapter currently selects **Daniel Caesar — CYANIDE**, the
official recording at https://www.youtube.com/watch?v=Jnm3ukzmJe4. It is a
selected-song path, not arbitrary catalog search. A manually downloaded file is
not required. The offline preparation command resolves that exact public source
through existing yt-dlp, decodes it through FFmpeg into a private canonical PCM
cache, and runs librosa's recording-derived beat tracker. No account, purchase,
browser cookies or generated replacement is used. Media stays outside Git.

Prerequisites are mpv, yt-dlp and FFmpeg from their official distributions, and
the optional analysis dependencies in `requirements-song-analysis.txt`. Prepare
without playback using:

```sh
uv pip install --python .venv/bin/python -r requirements-song-analysis.txt
.venv/bin/python -m agent.prepare_song --directory .venv/song-assets/cyanide
```

The existing agent entry point discovers that prepared manifest, or the host may
set `TENANT_SONG_MANIFEST` to another explicitly prepared manifest. Driver/Brain
code needs Root's coordinated deployment; preparing an asset does not hot-reload
the already-running bridge. No `song.*` capabilities are advertised without a
valid asset/checksum and mpv. Extraction failure does not invoke a sign-in,
cookie, download retry or alternate artist/source fallback.

`program-start` with exact `song_id` from inventory prepares mpv paused, then
starts the analyzed bytes once. The existing mpv window identifies the artist
and title. Its private inherited JSON IPC provides live `audio-pts`, pause,
buffering and EOF state. The default Mac output and current system volume are
preserved. Phone timing uses individual beat timestamps from those same bytes,
not a guessed BPM or independently started generated loop. Fractional cadences
interpolate neighboring beat timestamps; the song default is one beat per ON
and OFF. Song BPM updates are rejected because time stretching is not implemented.

The Brain maps a playhead sample using its own Bus dispatch/receipt bracket and
reports its uncertainty. Stale/buffering or ambiguous samples report pending and
fence unsent ON; seeking reanchors only future beats without catch-up.
Fresh reads with frozen or implausibly slow progress also stay pending. Timing
resumes only after a coherent advancing segment, with accumulated progress checked
against elapsed time so each read cannot reset a jitter allowance. First-cycle
ON+OFF ACKs establish participation, not hearing or physical alignment. End of
analyzed beats detaches the phone without inventing a constant-BPM tail. Manual
pause, actual EOF, access ending, disconnect and explicit stop clean the owned
program. Phone OFF remains independent and can leave the song playing. Player
EOF on owner disconnect plus a local monotonic expiry watchdog bounds playback
even if the Brain cannot deliver cleanup. UNKNOWN start/edge is never replayed.

The tracker estimates musical beats; it does not prove metrical level or
optical/acoustic alignment. Source/playhead checks, human hearing and actual
light-to-song phase acceptance remain distinct. Root/tester owns the released
finite experiment and asks Jay only for its physical outcome afterward.

Speech goes through stdin and playlist/volume through argv into constant
AppleScript. No shell, user-generated AppleScript, hard-coded voice or account.

## Reconnect and outcome rules

Heartbeat replies continue while OS commands run. One audio action is accepted
at a time; a concurrent request receives BUSY. A process-local ledger retains
4096 req results, including an unknown-outcome marker before execution. Duplicate
reqs never execute again, including across WebSocket reconnects. On disconnect,
finish recording in-flight outcomes before reconnecting. Responses are never
transferred to a new socket. Connection failures retry after 0.5–4 seconds; no
physical action is retried. A full ledger rejects new actions until host restart
instead of evicting replay protection. A fresh process loses that ledger: the
Brain must never resend unknown-outcome actions after an agent restart either.

The highest observed epoch persists across reconnects; lower epochs receive STALE.
This hint cannot discover an unseen revocation or cancel a delivered action. The
Brain persists room identity/epoch/enrolled aliases but never guest credentials.
No audio is automatically paused or replayed on reconnect/reset. If room code
changes, authenticated welcome updates the saved invitation used on reconnect.

## Required physical acceptance (not performed on Linux)

Before first use, inspect the actual Mac's Music scripting dictionary via Script
Editor > File > Open Dictionary > Music, or `sdef /System/Applications/Music.app`.
Confirm playlist/file track/location/play/pause/player state terms. The build
environment cannot verify that installed dictionary, Automation permissions,
local media, speaker route or audibility. Apple primary references:

- [AppleScript commands: set volume, get volume settings, say](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html)
- [Opening a scripting dictionary](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/OpenaScriptingDictionary.html)

With the local playlist prepared, unmuted output and agent connected, use the
coordinator's authenticated host.do path (or temporary protocol test harness) in
this sequence:

1. `volume {"level":25}`, then `music.play {}`: hear the configured local song.
2. `volume {"level":15}`: hear the reduction.
3. `music.pause {}`: hear the song stop.
4. `say {"text":"Hello from Tenant."}`: hear the phrase at modest volume.

Record real outcomes separately from subprocess/protocol tests. Also check one
short phrase while music plays, reconnect without repeated playback/speech, and
a missing/empty playlist produces an honest omission/error. Guest chat → tool →
Brain → Mac remains dependent on the coordinator's access flow and lighting
runtime; none of the simulated tests establishes that end-to-end physical path.


## Prepared ambient TV window

`python -m agent.prepare_visual --manifest .venv/song-assets/cyanide/song.json`
prepares a silent1280×720/60fps MP4 using the existing recording and beat map.
FFmpeg supplies the moving background; numpy/Pillow render translucent iridescent membranes, deformed by the actual PCM spectrum
and smoothly pulsed from the analyzed beat markers.
It creates a proposed `song-with-fluid-visual.json`, leaving the live manifest unchanged.
It needs the already-installed FFmpeg, numpy and Pillow; no microphone,
loopback audio driver, browser capture, account or media download is involved.

The optional `visual` manifest object contains path,sha256,source_sha256,width,
height,fps,duration_seconds,description. Both assets are checksum-verified at
load and again before preparing a player; visual source identity and duration
must match the canonical recording. Missing or changed optional assets reject
that configured recording rather than claiming its visuals are available.
The original manifest without `visual` preserves audio-only behavior.

For this prepared host setup, the visual loads as an external video track in
THE SAME owned mpv process as the canonical WAV, with explicit canonical audio
and external-video selection and audio-driven A/V synchronization. It opens a
NORMAL window on screen1 with1600×900 geometry, never native fullscreen, and
preserves the default output and volume (Jay requests20%). The existing
program-stop, access cleanup and host reset close that player, so its music and
visual window share cleanup. No second player or independent visual clock.
The prepared scene is advertised in song.prepare's description, which the
existing native-agent inventory exposes as the song label; no new Brain route,
MCP server, dashboard/UI edit or general media integration is needed.

Prompt: “Play the prepared Cyanide track with its circular visuals on the TV.”
Stop: “Stop the music and visuals.” This is one cached track/preset; arbitrary
Spotify/browser audio or arbitrary vibe-video selection is not established.
Analyzed beat markers are estimates; a small software A/V offset is not a
physical audio/display synchronization measurement.

Primary references: [mpv external files and tracks](https://mpv.io/manual/stable/#options-external-files),
[mpv video synchronization](https://mpv.io/manual/stable/#options-video-sync),
[FFmpeg gradients](https://ffmpeg.org/ffmpeg-filters.html#gradients).
