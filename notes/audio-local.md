# Audio — local Mac owner

2026-10-17 19:59 PT / 2026-10-18 02:59 UTC. Base/deployed voice revision reported by Root: `f228b39963958bc2911b13f8e933ae5aeb4d800d`. No production correction justified by current audio evidence. No runtime restart, live action, output/volume change, web edit, staging or commit performed. Root integrates/deploys; the local tester owns the released live gate. This owner does not maintain `notes/jay.md` or message other chats.

## Frozen acceptance work

- Added `tests/test_reply_voice_acceptance.py`: one composed journey across actual in-memory web handling, controller/context reset, native helper Unix socket, reply policy and Bus. Synthetic native replies and speaker ACKs; the fixture explicitly drives helper choices. Natural-language recognition and hearing remain separate live gates.
- Exact cumulative say counts: **0 → 1 → 2 → 2 → 3 → 3 → 4 → 4** for default text, opt-in, voice follow-up, opt-out/follow-up, one-off, text follow-up, opt-in again, new guest. Also verifies unchanged expiry, cleared prior marker, old-guest denial without another native turn or device send, zero uncertain requests and no volume calls.
- Corrected `agent/AUDIO.md` to match deployed PCM rendering, actual-duration preflight, speech player deadline and per-guest voice contract. No production code changed.
- Independent subagent review found no scoped production blocker at f228b39; final owned files independently reviewed/hash-matched. SHA256: test `73a5f6583cc5c8229395f061a5bfa777229f930e19eb9edf7c7b7f4e578acda1`; docs `ff0d237c5e82c8c8c3c92892c8a224399d57c8fc6182cab1c819a6e84a3e7fc4`.
- Final focused voice/driver suite: **107 PASS, 0 failures/skips**. Corrected acceptance module alone: **1 PASS**. Full shared checkout: **496 PASS in 17.417s**, plus **12 Node PASS**, 0 failures/skips. Combined count includes concurrently owned, uncommitted display projection work; it is not a frozen reviewed/deployed combined revision. Earlier explicit module invocation hit the existing program-test import-path requirement; canonical discovery resolved it. Earlier 490 count included five duplicated imported fixture checks, fixed before final checks.
- Compact machine record with commands, hashes, counts and limits: `tests/evidence/2026-10-17-audio-local-acceptance.json`. Root should integrate only these owned test/docs/evidence/notes after coordination; no commit or staging done.

## Actual evidence and limits

Root's actual HTTPS/WSS/native default trial at f228b39 is recorded in `tests/evidence/2026-10-17-reply-voice-default-live.json`: **TEXT_DEFAULT, 0 say, Leave 200**. It does not establish natural-language opt-in/opt-out, one-off speech or hearing. Policy/source tests cover queued unsent cancellation, exact connection choice, replacement/revoke/expiry and no replay; already started speech may finish.

`tests/evidence/2026-10-17-stop-recovery-live.json` at 0b4a1ec records 21 phone edges, zero failed receipts, 192.774ms median / 575.715ms max RTT. Jay confirmed phone OFF while beat continued for the measured 98.689s interval, then separately confirmed beat stopped with phone still OFF. These are scoped physical stop observations; transport RTT does not measure optical/acoustic alignment.

The actual guest requested 1s ON/1s OFF at 30 BPM, represented by 0.5 beats per state. One beat per state already expresses 2s ON/2s OFF at 30 BPM; source cadence checks exist. There is no invented one-second limit or arbitrary action cap. Optical/acoustic offset remains unmeasured, so no fixed correction or measurement run is justified by these receipts. Physical automatic expiry remains UNVERIFIED; the earlier interrupted attempt and unstarted additional run are not passes. Photo/perception remains gated.

## Tester handoff / next scoped step

At 2026-10-18T02:59:49Z, tester notes record gate release and exclusive live ownership, actual Chat here entry, first native turn pending. The tester found entry copy promising a gated photo; that is an Owen-owned web finding, not justification for an audio source change. No tester audio failure has been recorded yet.

Await its native/policy/device receipts for natural opt-in → follow-up → opt-out → follow-up → one-off → new guest; review actual say deltas and exact enrolled speaker/connection, then make the smallest audio correction only for a concrete failure. Do not issue a competing live action or ask Jay to start a test; only the live test owner requests physical-result confirmation after initiation.

Root clarified that **20 seconds is the intended observation window**, not a new product duration requirement or absolute physical guarantee. Existing explicit program-stop plus an independent watchdog revoking only the named test guest can bound the experiment flow; the engine also retains its actual lease bound. The tester owns establishing those controls and confirming cleanup, and can continue other cases if they are not ready. No duration field is required. My earlier claim that its absence alone blocked this experiment was too strong and is superseded; Audio makes no competing live calls.

## Tester update — 2026-10-18 03:02 UTC / October 17 20:02 PT

Reviewed the tester's recorded Batch1 observations at runtime f228b39. Natural opt-in and a voiced follow-up ACKed (`r_7bc21a95775a49beb5e715d16dea0a4c`, `r_1e703f249616486483657958e96c9da2`); opt-out and contextual follow-up were TEXT_DEFAULT with zero say. Requested one-off phrase ACKed once (`r_d4f9463e7df243c492dc879f26ea6320`), with EXPLICIT_SPEECH_ATTEMPTED suppressing duplicate narration. The post-one-off answer “Marigold.” stayed TEXT_DEFAULT. Tester records Jay's direct hearing and expected-silence confirmation for this voice sequence. This is a scoped actual UI/native/physical voice PASS, not general reliability.

Tester then enabled voice again (ACK `r_3466624a2d124d219a215ebfeb24ecf1`) and left, so the pending new-guest isolation check has a voice-enabled predecessor. Leave showed terminal ended access and disabled the composer; a backend stale-request denial is not inferred from UI prevention. New-guest results remain pending at this snapshot.

No audio source failure is indicated, so no production correction is justified. The tester also found gated-photo entry copy and an empty public transcript despite eight turns; Owen owns web copy and Device Runtime owns the already-planned projection seam. Audio did not overlap either implementation. Machine acceptance JSON now includes this scoped live result and Root's observation-window clarification; owned test/docs hashes and test counts remain unchanged.

## Root closeout — October 17, 20:08 PT

The completed tester batch resolves the pending new-guest check above: the predecessor enabled voice before Leave; the next guest used the same fixed native room conversation, had no marigold context, and started TEXT_DEFAULT with zero say. This is a scoped conversational/generation check, not a complete memory-isolation audit. Jay also confirmed the requested 30 BPM, 2s ON / 2s OFF light train, then phone OFF while the beat continued, then separate beat stop. All nine program edges acknowledged and cleanup confirmed; no calibrated optical/acoustic alignment is established. See `notes/tester.md` and `tests/evidence/2026-10-17-local-e2e.json`.

Jay's latest music direction supersedes further generated-beat trials: actual Daniel Caesar recordings, with the phone following the recording's real beat. Current `beat.prepare/start/status/stop` follows the generated audio process; it does not expose an arbitrary song's playhead or beat phase. Treat song matching as unimplemented. Before a future trial, identify the simplest reusable playback/timing source and a confirmed pause/cleanup path; do not claim a guessed BPM plus separately started flashes is synchronization. No new playback, source changes or timing trial was started for this handoff.
