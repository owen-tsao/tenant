# Independent room-audio review

Baseline: `f3d919f`, `jay/room-audio`. Reviewed `jay.md`, `owen.md`,
`PLAN.md`, and `ARCHITECTURE.md`. No shared contract or Owen-owned files changed.

## Contract contradictions and reserved integration decisions

- **Epoch invalidation is incomplete:** ARCHITECTURE §3 says retaining the
  highest observed epoch prevents any queued action firing after reset. A device
  cannot reject an old action until it learns the new epoch. `welcome` carries
  no epoch; no independent epoch/reset frame is specified. Local rejection of
  lower epochs is useful but cannot establish the claimed global guarantee.
- **Restart epoch ambiguity:** §12 permits Brain restart with lost state and
  device reconnection. Keeping an old epoch can reject a new server's valid
  commands; clearing it on reconnect loses stale protection. Resolving this
  needs the coordinator's reset/access design; audio must not invent a contract.
- **Data-model omission:** `jay.md` requires `Room.epoch`; ARCHITECTURE §2's
  `Room` dataclass omits it despite §3/§9 requiring it.
- **Timeout guidance conflicts:** §12 invites the guest to try again; §3 says a
  timeout has unknown outcome and must not be blindly resent. Audio must never
  automatically repeat a physical action after an unknown result.
- **Music arguments unspecified:** §8 shows a playlist-name example but no
  exact argument schema. A locally documented schema can expose prepared media
  without changing `do/ok/err` frames; Brain tools must consume the advertised
  manifest rather than assume a playlist API.
- **Older summary frames differ:** PLAN §2/§4 use `can` and simplified `do`/`ok`
  shapes. ARCHITECTURE §3's `caps`, `type`, `req`, `epoch`, and `deadline_ms`
  are authoritative.
- **Scope:** §8 also lists brightness and slides. The explicit room-audio task
  limits this implementation to `music.play`, `music.pause`, `volume`, `say`;
  deferred features must not be advertised.

## Implementation review

Initial implementation reviewed. Two findings sent to implementation owner:

1. `MUSIC_PROBE` counts file-track records but does not check whether the first
   selected record has a local location/file. `MUSIC_PLAY` checks location later,
   so readiness can advertise music when the prepared media cannot play.
2. `deadline_ms` is passed only as a subprocess duration. Thread-executor wait
   occurs outside that bound. Reproduced using a single occupied executor:
   `deadline_ms=10`, executor released after 50 ms, action started at 51 ms and
   returned `ok`. Capture an absolute expiry at receipt and check remaining time
   inside the worker before invoking any OS command; do not cancel `to_thread`
   and assume that stopped the OS action.

Positive checks from source inspection: shell is not used; AppleScript is fixed
source with playlist as argv; speech is stdin; subprocess failures do not echo
user content/secrets; each action has one subprocess; heartbeat receive handling
remains independent of action tasks; req ledger survives reconnection and
records unknown outcome before dispatch; disconnect waits for active actions
without moving replies to a new connection; lower observed epochs are rejected.

## Fix verification and evidence

Both demonstrated findings are addressed in the reviewed source:

- `MUSIC_PROBE` and `MUSIC_PLAY` now select the same first file track, reject
  missing `location`, and run `get info for localFile` before readiness/playback.
  This checks a real local file rather than merely a library record. Actual
  installed Music dictionary and file behavior still need the Mac check.
- Session records `time.monotonic()` at receive. The worker computes remaining
  time from that absolute expiry before dispatch and refuses expired work.
  `DeadlineRegression.test_expired_in_executor_queue_never_dispatches` verifies
  the saturated-executor failure case no longer starts an action.

Reviewer executed from the isolated checkout:

```bash
python -m unittest discover -s tests -v
python -m py_compile agent/laptop.py
python agent/laptop.py --check
```

Results: **30 tests passed, 0 failed**; compile passed; Linux readiness reported
`caps: {}`. Coverage includes malformed arguments, injection-safe argv/stdin,
missing commands/app/media, permission failure, timeout/unknown result, volume
bounds/readback, async heartbeat during work, stale epoch, duplicate suppression,
full ledger, disconnect/lost acknowledgment, and automatic reconnect over an
actual loopback WebSocket. That socket test substitutes OS effects; it establishes
transport behavior, not sound or a working guest demo.

No additional demonstrated implementation blocker remains after the fixes.
The coordinator-owned epoch/reset contradictions above remain. No physical Mac,
installed Music dictionary, Automation consent, audible output, Bluetooth, or
guest-chat observation has been performed by this reviewer. Follow the short
real-Mac sequence in `agent/AUDIO.md` before calling audio accepted physically.

## Final acceptance gate — BLOCKED

Jay's reopened gate supersedes any earlier completion implication: **feature 2
is BLOCKED, not complete or merge-ready**. The reviewer independently reran
`python -m unittest discover -s tests -q` (**30 passed, 0 failed**) and
`python -m py_compile agent/laptop.py` (**PASS**) after the handoff gate update.
Code and tests are unchanged. Automated correctness does not establish audible
effects or integrated guest authorization.

The actual Mac + Tenant guest path must record playback, volume reduction,
pause, speech, speech over music, and reconnect without replay, with revision,
timestamp, req, returned status, and Jay's audible observation. Coordinator
permission/revocation/device-adaptation gates must also pass. Preserve current
audio effects when access ends absent explicit host cleanup; no automatic retry
or substitution after unknown outcome. No physical evidence has been collected
here, and this review does not authorize merge to main.
