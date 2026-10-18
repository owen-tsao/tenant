# Batch4 follow-up — combined software acceptance

Scope: only frozen Audio helper-transport certainty and Tester native continuation/context fixes. No web/sources edits, real model/room/UI/service/device/player/audio/photo calls, output/volume changes, restarts, deployment, staging or commits. Root owns deployment and the newly authorized remaining real E2E.

Frozen source base: `083be0ca2299937cfe2b0b9754be179e15714cb8` (documentation on reported deployed `e4b8426`). Final private manifest: `.venv/acceptance/post-batch4-combined-final-manifest.json`; copied source: `.venv/acceptance/post-batch4-final-software-gyhwmo7i`. The105-file map is `17fc721f5ecfba433b834d27aaf31790bc6cf9857e8824be726f7625c85f7b57`; every shared file matches. Exact source/test map and owner hashes are recorded in `tests/evidence/2026-10-17-batch4-followup-software.json`. Earlier source-evidence manifests are preserved.

## Transparent validation result

Initial frozen full offline discovery ran761 canonical checks in26.804s:735 passed,26 failed,0 errors/skips. All26 stopped at the same old `ProgramIntegrationTests.begin()` assertion requiring context length<=4000; intentional new guidance generated5464–5465 characters under the new6000 transport bound. A narrow30-check reproduction established the common cause. No production correction was needed.

Tester repaired only the fixture: import `MAX_APPLICATION_CONTEXT` and use it in that assertion. All30 affected module checks then passed in6.897s with independent review. That closes26 previous failures and repeats4 earlier passes. Dedicated new transport checks still enforce6000 accepted/6001 rejected before native submission. All original production hashes stayed frozen.

Retain the735 unchanged canonical passes, the26 repaired closures,16 explicit metadata checks (0.432s),7 explicit photo-wiring checks (0.095s), and12 unchanged Node checks (2.270s): **784 distinct Python checks and12 Node checks covered successfully**. Per Root direction, no redundant full-suite rerun was performed. This is composed successful coverage, not a fabricated clean final full-suite run. Independent final scoped SOFTWARE PASS verified all105 shared/snapshot hashes with zero mismatches, the fixture-only delta, all five owner hashes and clean whitespace checks; no broad rerun or live action by the reviewer.

## Behavior and rollout handoff

Helper failures provably before sendall are known unsent; any failure from immediately before sendall onward remains UNKNOWN/no retry. Actual backend responses pass through unchanged. Native input text stays exact; private application context requires the current helper prefix verbatim and fresh owned playback-status evidence after phone OFF/detach. An OFF ACK proves only the light state. Even a valid advancing ready song status supports a recent observation, not a guarantee of continued playback. Guidance does not itself establish model compliance.

RoomSession and ConversationAgent load in Brain; the private helper command executes the CLI file afresh for each invocation. No laptop/song driver changed, so a Brain refresh is sufficient by source inspection; Root must still establish runtime readiness. Preserve default-silent replies, lease/turn authority, late cancellation, no UNKNOWN replay, existing output and volume.

Real continuation/ordinary separate-stop acceptance remains outstanding after Batch4's external pause. Actual song audibility/perceived alignment and phoneOFF observations remain scoped passes. Pause origin and historical helper UNKNOWN stage remain unproven; these fixes do not rewrite that history. Long-duration physical expiry and Owen's photo UI/physical acceptance remain separate gates. Root alone publishes, refreshes and releases live testing.
