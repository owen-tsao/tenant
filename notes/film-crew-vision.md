# Film crew — local semantic vision and one-shot policy

Status: **offline implementation ready; reusable validated automatic mode GATED**. Root integrates; Tester alone owns physical/live work, and both real phone views/manual switching must be physically proved first. After that proof, Jay’s requested one host-supervised proactive trial may run through Root’s explicit `--trial` path without asserting held-out replay acceptance. This owner performed no camera acquisition, OBS/UI action, model-room turn, effect, production service change, staging, commit or deployment. Other owners’ film_crew modules and all web/core modules were not edited.

## Model choice and isolated runtime

Passive installed-asset inspection found cached text/audio models (MERT, Whisper, MiniLM, GPT2, XLM-R) but no usable vision checkpoint; main .venv had Pillow/numpy but no torch/open_clip. Installed the established pretrained **MobileCLIP2-S0** candidate in isolated `.venv/film-crew-lab` (824MiB on disk), leaving production packages unchanged. Exact lab pins: `requirements-film-crew-vision.txt`. Public model artifacts are local at `.venv/film-crew-models/mobileclip2-s0` (294MiB on disk); nothing is inferred through a paid API or cloud inference endpoint.

Model: `timm/MobileCLIP2-S0-OpenCLIP`, revision `095906d28bf54d7584dc411e8ffe448f34289e05`. This is an established OpenCLIP adaptation of Apple’s pretrained model, not a newly trained classifier. S0 is the small candidate in this family; measured latency is sufficient to attempt replay, but semantic sufficiency is **not established**. Initial 215MB/53.8M estimate from the model card was superseded by actual artifact/model measurement: **299,663,092 bytes** safetensors (~286MiB), **74,835,073 loaded parameters**. Cache fixed trained text embeddings at startup, retain only the reparameterized visual tower (**11,357,504 parameters**) for frames. Warm once outside the event; no per-frame process or coding-agent launch.

Runtime loads only reviewed local safetensors/config/tokenizer files, with SHA256 checks before model loading; never downloads. Correct preprocessing is explicitly 0 mean/1 std, bilinear shortest-side resize,256 center crop from pinned config. Use the checkpoint’s local tokenizer.json,77-token truncation and EOS49407 padding. The canonical model-name SimpleTokenizer uses different zero padding and is intentionally not used. Preliminary measurements with default local-checkpoint preprocessing were superseded; final results below use the corrected checkpoint preprocessing/tokenizer. No remote code, pickle checkpoint or API key is loaded.

Reviewed runtime artifacts:

```text
43e7162c531e845155dbf47e8fef8fe5718b0eab3d6beefb8d615a2c55b4c1e5  open_clip_config.json  (725 bytes)
ab91a1a0c4330d6b1913e24d5035dfdea15423316aaec649610c6b1c6ddd0e95  open_clip_model.safetensors  (299663092 bytes)
43d4281659ce30b6aca2c7485944b3d73925bb7f87c7234daf3b6b094a6d618c  tokenizer.json  (3642035 bytes)
```

## Narrow API and ownership

```python
classifier = VisionClassifier(
    '.venv/film-crew-models/mobileclip2-s0', device='mps', threads=4)
evidence = classifier.classify(wide_png_bytes, detail_png_bytes)
# evidence.as_dict() is available; classifier is warmed/reused.

policy = OneShotPolicy(
    validation_ready=False, max_age=.5, max_gap=.6,
    min_dwell=.75, min_observations=3, arm_delay=.25)
policy.arm(now=monotonic_time, current_scene='WIDE')
proposal = policy.propose(
    evidence, now=monotonic_after_inference,
    captured_at=min_pair_acquisition_monotonic,
    armed=True, manual_override=False, connected=True,
    sources_fresh=False, current_scene='WIDE')
# Returns None or 'DETAIL'; NEVER invokes OBS.
```

`DecisionEvidence` is frozen: demonstrating, detail_usefulness, confidence, uncertainty in0..1; valid bool; pair_similarity, raw demo/detail margins, detail_advantage, inference_ms and a safe reason. PNGs are single stills ≤8MiB/16M pixels, minimum16px dimensions. Invalid/unreadable/animated/oversized input, classifier contention or model failure yields validFalse/confidence0/uncertainty1. Images/errors/local paths never enter evidence. Importing vision.py does not import torch/load a model. CPU thread configuration is process-wide; keep this classifier in the isolated film-crew process, not production Brain.

Trained image/text embeddings score fixed generic positive descriptions of someone presenting a held object, against empty-hand waving, talking/ordinary motion and empty-room descriptions. Detail is compared against held-object closeups and empty/blocked/blurry/face-only/unrelated-view descriptions, with an advantage versus the wide view plus image-embedding relevance. These are trained-model semantic scores with deterministic conservative transforms. No skin-color/motion heuristic/manual cue is substituted for AI. Pair cosine is only a relevance hint and does not establish same-object identity; there is no identity/person tracking or transcription.

**All scores, including the field named confidence, are uncalibrated prompt-relative evidence, not empirical correctness probabilities.** Relative text margins cannot prove active intent from one still or reliably distinguish every incidental object hold from a demonstration. Temporal dwell is a guard, not a trained action model. High scores or passing software tests do not establish semantic validation. Root distinguishes an explicitly authorized host-supervised trial from reusable validated automatic mode; any internal enable interlock used for the trial records host permission only, not a claim of empirical model accuracy.

WIDE is the caller’s initial scene. Explicit arm requires validation_ready exactlyTrue and WIDE; ≥3 distinct acquisitions sustained for≥.75s, after arm delay, must pass all thresholds. Every DETAIL proposal consumes that arm immediately, even if the switch fails; no repeated cut or automatic WIDE restoration occurs. Manual override, external scene change, disconnect, false armed or false/missing sources_fresh disarms until an explicit new arm. Invalid/uncertain/stale/future/reordered observations clear dwell. Repeated timestamps do not accumulate observations. Thresholds remain provisional pending replay.

`policy.reset_observations()` only clears accumulated positive dwell/count; it preserves the current arm, arm time, last capture and clock history, and never rearms a consumed/disarmed policy. Root calls it when a skipped/incomplete per-pair pixel-novelty observation must interrupt earlier semantic progress. The focused regression proves two old positives cannot complete a cut after reset, a full fresh dwell can still use the original arm, and calling reset after the cut cannot rearm. This narrow API addition changes no model scores or semantic thresholds; prior independent review predates the addition, and Root owns composed controller review.

Snapshot acquisition time is **not source-frame freshness**. Root’s separate decoded-RGB pixel-change watchdog supplies sources_fresh; metadata-only PNG changes must not count, initial snapshots establish only a baseline, and repeated identical decoded pixels must not seed new policy observations. This is only a conservative recent-change interlock: it cannot prove sensor authenticity/live provenance, can be fooled by changing replay, and can reject a genuinely static view. Root’s controller owns current manual/switcher revision and finite deadline checks before/after inference and immediately before execution. Interface fit with OneCutDirector was reviewed read-only. A recent-change-only watchdog gap that allowed identical pairs to accumulate dwell was reported to Root for correction; no Root file was edited.

## Measured timing

Mac16,7 / M4 Pro from earlier passive inventory. No live feed was used. Times include PNG decode, preprocessing, paired image inference and numeric scoring, with explicit MPS synchronization. They exclude OBS capture/transport and switch acknowledgment. Model constructor includes artifact verification, text embedding cache and three warm pairs.

| Corrected path | Input | Pairs | Median | p95 | Max |
| --- | --- | ---: | ---: | ---: | ---: |
| CPU |640×480 public cats PNG pair|25|215.62ms|249.52ms|253.73ms|
| MPS |640×480 public cats PNG pair|25|16.41ms|18.26ms|31.46ms|
| MPS |1280×720 procedural PNG pair (~2.13MB each)|30|29.64ms|33.82ms|34.74ms|

Fresh-process MPS startup/warm for1280 benchmark: **3.80 seconds**. Corrected combined benchmark started CPU in4.05s then MPS in2.78s with imports reused. First-ever pre-correction cold constructor took12.98s; no claim that every cold startup is4s. Warm before arming, and measure actual capture-to-decision latency before approving live timing budgets. Default .5s acquisition age/.6s inter-observation gap is compatible with measured model latency; Root can configure bounded timing after measuring capture cost, without pretending screenshot receipt establishes source freshness. Dwell imposes intentional observation time; no frame-by-frame narration is implemented.

The public COCO cats sample is a negative sanity/latency input, not a held-out semantic benchmark or paired real phone angle: demonstrating≈.2705, detail usefulness≈.2935, uncertainty≈.6339, so it does not meet policy thresholds.1280 noise images are **latency inputs only**, not positive/negative accuracy validation. Raw timings/manifests are scratch files under `work/film-crew/`; do not publish them as physical proof.

## Checks and remaining release gates

` .venv/bin/python -m unittest discover -s tests -p test_film_crew_policy.py -v `: **42 tests PASS**, zero errors/failures/skips (35 pure policy cases +7 vision parser/failure boundaries). Coverage includes one-shot/rearm, validation gate, dwell/distinct timestamps, freshness interlock, clock/time validation, manual/disconnect/scene overrides, malformed/animated/truncated/oversized PNG, busy/error fallback, resource/lock cleanup, and rejected unreviewed local weights. No test needs torch, network, camera or OBS. Independent read-only review found no code blocker; its overlapping policy checks and13 ad hoc vision boundary checks are not added to suite totals. Reviewer confirmed preprocessing/tokenizer agreement and nonfinite-output denial. Offline real model invocation and timing pass on CPU/MPS; those prove execution/latency, **not semantic accuracy**.

Small replay plan after Tester proves both feeds/manual switching: freeze prompts/config/model hashes, capture matched WIDE+DETAIL stills privately at known moments, and keep calibration separate from held-out replay. Use at least6 held-out real object-positive events (e.g. book, mug, tool/gadget, different grips/positions; detail shows useful features),6 negative events (empty-hand wave, talking/ordinary motion/no object, object present but not demonstrated, empty/blocked/blurry/wrong-subject detail), plus static/disconnect/manual override trials. Include timestamped sequences covering dwell and both-view pixel novelty, with random event order and human labels recorded before inspecting scores. Do not tune on held-out outcomes; if tuning is needed, discard that set as calibration and collect new held-out events. For reusable validated automatic mode, accept only if all held-out negatives cause no proposal and intended positives can produce one correctly justified DETAIL after dwell; report misses/ambiguities rather than calling a hand cue a model decision. This6+6 replay is confidence/validation work, **not a mandatory12-event prerequisite to Jay’s first requested experiment**. Root may run **one** explicitly authorized host-supervised `--trial` after actual manual two-feed switching acceptance, using the same one-cut, freshness/novelty, manual override, deadline and final switch-state guards. Stop automatic choices afterward until rearmed, verify the physical angle usefulness, and record the actual outcome. Trial acceptance/host authorization is separate from held_out_replay_passed: the latter remains false unless actually demonstrated. Default enable remains closed; a trial is never reported as calibrated semantic accuracy or reusable automatic-mode PASS.

## Host-supervised trial versus reusable validation

Root’s explicit `--trial` is the narrow human-authorized experiment after phase1 manual switching proof. It does not fabricate a held-out acceptance receipt and does not waive software guards. A successful physical trial would prove that particular observed choice, while general semantic separation remains unknown. The6+6 held-out plan applies to reusable validated automatic mode. No classifier/policy/model/threshold code changed for this clarification.

## Frozen owned files

```text
cac13fbccc66a073b9ad35d87c2d5953f16140be191328ed35c31450a2c23188  film_crew/vision.py
01970da7d71583cea6f8d6d0f01201b4bfe68be3a6f0fafaf57f4c92c379d299  film_crew/policy.py
d5bb0077fcc1db774296a5b8ae314c83c028c203a1869ec5ef2e3951277795ff  tests/test_film_crew_policy.py
d7468db3faecabb4ec35d59ee33b317303096c4eb2e7b633a480f6dc5a8b8762  requirements-film-crew-vision.txt
```

No other owner’s source was changed. Root owns config/controller/CLI/base dependencies and execution; Tester owns manual physical proof/live testing. Model/input data remain in the isolated local lab. No stage/commit/deploy performed.

References: [Apple model code](https://github.com/apple-aiml-research/ml-mobileclip), [model card and supported OpenCLIP usage](https://huggingface.co/timm/MobileCLIP2-S0-OpenCLIP), [pinned config](https://huggingface.co/timm/MobileCLIP2-S0-OpenCLIP/blob/095906d28bf54d7584dc411e8ffe448f34289e05/open_clip_config.json), [public negative sample](https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/coco_sample.png).
