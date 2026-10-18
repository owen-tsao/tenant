# Room audio integration handoff

Base: `f3d919f8ba268ecbc0fce5f80ab4a079af6b0a86` (current main inspected).
Isolated branch: `jay/room-audio`.

Scope: `agent/laptop.py`, audio-specific documentation and deterministic tests.
No Brain, dependency scaffold, shared contract, or Owen-owned UI edits.
No features 3–7, slides, perception, new speaker integration, or reset policy.

Execution environment: Linux, Python 3.12.14. It is not either user's Mac.
Implementation and simulated protocol evidence must be distinguished from
physical acceptance. Playback, speech, Bluetooth routing, macOS permission,
and end-to-end guest chat are BLOCKED pending real-Mac execution.

## Integration boundaries

Use ARCHITECTURE §3 `hello/caps`, `do/req/cap/args/deadline_ms/epoch`,
`ok/err` and `ping/pong`. Do not use PLAN's older simplified summary frames.
Brain must consume the advertised argument definitions; no hard-coded music
playlist assumptions. Brain owns per-device serialization and authorization.

No dependency file is edited concurrently. Agent requires only Python standard
library plus the already-planned `websockets` runtime dependency.

Coordinator-owned contradictions are recorded in `AUDIO_REVIEW.md`. In
particular, highest-seen epoch is not an independent revocation signal. A
rotated room code and restarted Brain require an explicit coordinator decision;
this agent must not guess a new room or silently clear an epoch to bypass it.

## Continuation

No unattended continuation is configured. Available scheduling tools are
reminder/recurring automation tools, not a bounded coding-goal executor. The
bounded loop remains open in this chat, BLOCKED on the real-Mac check.

## Exact startup and capability contract

See `AUDIO.md` for setup and the four-step physical sequence. Use Python 3.12;
shared runtime must supply `websockets>=14` (this executor: 16.0). No requirements
file was modified. Load DEVICE_TOKEN securely into the existing process
environment; do not paste it into commands or logs. Set:

```bash
export TENANT_WS_URL='wss://YOUR_HOST/ws/device'
export ROOM_CODE='CURRENT_CODE'
export TENANT_MUSIC_PLAYLIST='Tenant'
python agent/laptop.py --check
python agent/laptop.py
```

Use `ws://127.0.0.1:8000/ws/device` for a local Brain. Default device ID `laptop`;
use `TENANT_DEVICE_ID` if the other Mac also enrolls. The label is `Room speaker`
(default), configurable with `TENANT_DEVICE_LABEL`. `--check` probes without
playing audio or changing volume; Music may launch/show Automation consent.

Manifest is computed on startup. macOS with executables exposes `volume`
(`level`: integer 0–100) and `say` (`text`: nonempty, max 160 chars). Only a
configured Music playlist with an existing first local file additionally exposes
`music.play` and `music.pause`, both accepting `{}`. Playback uses that prepared
track, with no music-search/streaming promise. Run `--check` again and restart
after preparing or repairing media. Results include `audible_verified:false`.

## Verification evidence

Final commands executed on Linux, Python 3.12.14:

```bash
python -m unittest discover -s tests -p 'test_laptop_audio.py' -q
python -m py_compile agent/laptop.py
python agent/laptop.py --check
git diff --check
```

- Unit/protocol/transport suite: **30 passed, 0 failed** (0.627 s final run).
- Python compilation: passed.
- Linux capability check: `caps: {}`; no Mac capabilities advertised or invoked.
- Diff whitespace check: passed.
- Independent reviewer challenged code and contracts (`AUDIO_REVIEW.md`). Two
  demonstrated findings fixed: media discovery previously counted unavailable
  records; deadlines previously excluded executor queue delay.
- Tests cover bounds/types/extra args, text/playlist injection-safe data passing,
  missing executable/app/media, OS errors/permission/timeout, no false playback
  state, off-loop dispatch, deadline expiry before side effects, BUSY, stale
  epoch, ledger exhaustion, duplicate requests, lost acknowledgments, heartbeat,
  reconnect. Transport test uses actual loopback sockets and a fake dispatcher;
  it proves transport behavior, **not audible playback or Brain integration**.

## Remaining acceptance / genuine blocker

No access to a real Mac in this executor. All of these are **unperformed**:
installed Music dictionary validation; Automation prompt; prepared local track;
actual computer-speaker playback; volume reduction; pause; spoken phrase; speech
over music; Bluetooth (optional); reconnect under real Mac load; guest chat via
coordinator's Brain/access design. No mock is presented as a working demo.

Short Mac sequence after selecting/unmuting computer speakers and preparing
playlist `Tenant`: start agent; dispatch `volume {"level":25}` then
`music.play {}`; lower to `volume {"level":15}`; `music.pause {}`; then
`say {"text":"Hello from Tenant."}`. Listen to each result. Keep phrases short.
Record audible pass/fail separately from `ok`. Audio is not automatically stopped
on lease release/reset because that policy belongs to the coordinator.

## Applying the isolated change

All changes are confined to `agent/` audio files and
`tests/test_laptop_audio.py`. Cherry-pick the room-audio commit from
`jay/room-audio` into the coordinator's checkout, or apply the supplied Git patch
with `git am /absolute/path/tenant-room-audio.patch`. Do not copy over dependency
or Brain scaffolding from this checkout; it contains no implementation of those.

Remote delivery: Git push was attempted and rejected with `No anonymous write
access` / authentication failed. The branch and commit are local, not published
on GitHub. A complete `git format-patch` artifact is provided for `git am`;
no remote branch or PR is claimed. Resolve the local commit with
`git rev-parse jay/room-audio`.

## Gate status — Jay's 2026-10-17 instruction supersedes completion language

**Feature 2 status: BLOCKED; not complete, not merge-ready.**
Automated checks and independent code review are PASS. Real-Mac physical effects
through the integrated Tenant guest path are BLOCKED: this Linux executor cannot
hear or operate Jay's Mac, and main currently contains no Brain runtime to test.
The coordinator must also pass permission/revocation/device-adaptation checks
before the core gate opens. No merge to main is authorized by this handoff.

Fetched main `887e1bb` and read `notes/owen.md` and `notes/jay.md`; only decision
logs changed since the implementation base. Shared notes remain coordinator-owned
for consolidation. Coordinator note to copy into notes/jay.md: room audio code
and 30 automated checks PASS; physical integrated playback/volume/pause/speech
BLOCKED pending Mac execution; do not mark merge-ready. All workstreams must
retain their required hardware/access gates until evidence is recorded.

Approved policy: ending access preserves current audio effects unless explicit
host-configured cleanup exists. An unavailable requested device must produce an
explanation and suggestions, then wait for guest choice. Unknown-outcome actions
must never be retried or substituted. Audio implements no cleanup/substitution;
the coordinator owns guest behavior and permission checks.

Required integrated record: local final revision, ISO timestamp per request,
request ID from Brain/device logs, requested cap/args, returned status, and Jay's
heard observation. For `laptop`, after secure enrollment and playlist preflight:
volume 25 -> music.play (song heard); volume 15 (quieter); music.pause (stopped);
say "Hello from Tenant" (phrase heard). Use guest chat, not a standalone OS
command. Also observe speech over music and reconnect without repeated effects.
The coordinator records access-denied/no physical action after ending access,
while preserving the current effect. Never infer audible PASS from `ok` alone.
No physical rows have been collected; their state is BLOCKED, not PASS.
