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
audible sound. Check output routing/mute physically. `say` may exceed the five
second bus deadline for longer text; keep demo phrases short. OS subprocesses are
limited to min(remaining request budget, four seconds), killed/reaped by subprocess.run
on timeout, and run off the asyncio event loop. An Apple event already delivered
to Music can still have taken effect even if its sender times out.
Executor scheduling time counts against the request budget: a worker which starts
after the deadline refuses the action before invoking the dispatcher.

Direct `say` playback returned success but was inaudible in two actual tests, so
speech is rendered first and played with `afplay`. Both steps share one deadline;
expiry before playback starts sends no audio, while playback timeout is UNKNOWN
and is not retried. Human audible acceptance of this replacement is required.
Tests must preserve Jay’s chosen volume unless he explicitly requests a change.

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
