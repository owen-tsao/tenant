# Tenant — End-to-end Tester

Owner: local Mac tester. Updated 2026-10-18T02:57:24.280648+00:00.

## Current status

**WAITING FOR RELEASE — gate now exists with owner Root / state held / revision f228b39. No guest joined and no device action initiated.**

- Read notes/jay.md, notes/owen.md and notes/demo-testing.md; production sources and all web files are read-only for this owner. No service restarts or replacement room agent.
- Checkout inspected: f228b39963958bc2911b13f8e933ae5aeb4d800d. Deployment f228b39 / 484 Python + 12 Node and review are Root-reported, not independently deployment-attested here.
- Actual supported-CUA display inspection at approximately 2026-10-18 02:56:55 UTC: room8157; Phone light ready; Room speaker ready; no current guest. Last displayed guest left19:56:11 PT. Readiness alone does not establish absence of a running/UNKNOWN program.
- Required `.venv/tenant-runtime/e2e-owner.json` was absent at first inspection. No lock acquired and no live batch started. Root's current verification takes precedence until the explicit release.
- Do not ask Jay for repeated expiry observations. Current automatic physical expiry remains unverified; the earlier interrupted attempt is not a pass.

## Release and stop contract

Before joining, require gate owner exactly `Tenant — End-to-end Tester` and state exactly `ready`; acquire sibling `e2e-test.lock` exclusively, then reread gate. Hold the OS advisory lock across the whole batch; never delete/steal an existing holder's lock. Stop if gate changes, a real guest/performance appears, Jay uses the room, target disconnects, or any action outcome is UNKNOWN. Do not replay uncertain effects or substitute a device.

Check actual display plus available native/program receipts for no active real guest and no running/starting/stopping/unknown program. If authoritative program quiescence cannot be verified, keep device cases blocked. Fresh guest must use the sole fixed native Tenant room conversation, with new guest context cleared. A room reset or restart is outside tester authority.

## First finite batch — risk order

| Order | Natural guest interaction | Expected result and required evidence |
| --- | --- | --- |
| 1 | Enter actual Chat here; ask what can be controlled and give a unique harmless context marker; ask a contextual follow-up. | Visible replies in same guest chat / same native room; no unrequested device effect; native turn and guest correlation; TEXT_DEFAULT and zero say dispatches. Inspect permissions, countdown and Leave. |
| 2 | Explicitly request ongoing spoken replies from the currently enrolled Room speaker; ask a brief follow-up; explicitly disable spoken replies; ask another brief follow-up. | Consent tied to exact current guest/speaker/connection; enabled narration dispatch then disabled policy with zero new narration sends; meaningful text remains visible. ACK separately from human audibility. Stop on uncertainty. |
| 3 | While voice is disabled, ask “Say ‘Tenant test ready’ once.” Then ask another text question. | One explicit say dispatch, no duplicate automatic narration, no persistent opt-in. Ask Jay once for actual hearing only after initiation. |
| 4 | Leave through actual UI; verify ended controls and harmless attempted control denial where UI permits. Join a new guest and ask what it remembers / a brief neutral question. | Ended guest produces no new native/device dispatch; new guest context excludes prior marker and starts text-only, zero say. UI preventing send is UI denial only; backend stale-authority denial needs correlated evidence. |
| 5 | In same new guest, request a finite 30 BPM beat and phone light 2s ON / 2s OFF, bounded to at most20s. Converse briefly during output. | Exact requested cadence retained; program duration explicitly bounded before start; receipts first ON/OFF, no unintended tempo changes or duplicate playback; preserve Mac default output/current volume. Do not start if duration or cleanup route cannot be guaranteed. |
| 6 | During bounded output, explicitly ask phone OFF while beat continues; verify OFF ACK, then separately request beat stop. | Phone no longer pulses; audio still running after phone OFF, then stopped with confirmed cleanup and no late edges. Ask a single consolidated physical question for the initiated window; transport timings are not optical/acoustic timing. |
| 7 | Confirm all outputs stopped, Leave, inspect public display and denial evidence. | Device/program receipts confirm final phone OFF and beat stopped; no new dispatch after Leave. If cleanup UNKNOWN, stop and report incident without replay. |

This is a finite engineering batch, not unbriefed experience evaluation. Full physical expiry, Photon delivery, microphone denial, reconnect/queued races, new-speaker consent, synchronization measurements, reset/restart and independent cold participants remain later separately released cases. Photo/perception/proactive features stay gated.

## Evidence and retest loop

For every case record UTC window, full deployed revision or explicit attestation limit, expected/actual, raw harmless input, visible reply, same guest/native turn correlation, request/program IDs in private notes only, relevant policy/dispatch/ACK counts, observed result, PASS/FAIL/BLOCKED and final cleanup. Never print tokens, private URL fragments or phone numbers. Read audit JSON through a strict allowlist; do not dump logs or environment.

1. Capture read-only baseline and audit offset after release/lock.
2. Drive one natural UI request; inspect UI and exact native/device receipts.
3. Compare against predeclared expected outcome; distinguish no-send, sent/ACK and actual human effect.
4. Record failures without altering production; no automatic retry after UNKNOWN.
5. For deployed fixes, verify new revision/gate and run only failed case plus necessary context/cleanup regression under a new finite batch.
6. Release lock only after recording final cleanup or explicitly unresolved outcome; preserve failure history.

## Results

No tester-owned guest or physical trials yet. Gate absent at initial inspection, then created as owner Root / state held / revision f228b39. Tester has not attempted to acquire the lock while held.

- 2026-10-18T02:57:39.528686+00:00: Read-only planning complete. Await explicit ready release to this tester. Current program-start schema has no requested duration field; verify a supported finite output bound before case5. Do not assume asking for20s makes the engine stop after20s. If unsupported, record this case BLOCKED and report without starting output. Default-text/context/voice cases may proceed independently after release.

## Batch1 — live actual UI, released f228b39

- 2026-10-18T02:59:32.826075+00:00: Gate ready for this owner; exclusively created and flock-held e2e-test.lock (holder process6581 session). Reread gate after acquisition. Actual display room8157, both devices ready, no guest; latest program requested_stop had phone/audio cleanup confirmed. Audit baseline offset129745.
- Joined via actual /j/8157 → Chat here, no direct join/WS substitute. First request: “Hi! What can I control here? For this chat, remember the word marigold.”
- **FAIL — entry capability copy:** join page advertises “Ask for a light, some music, a photo.” Photo is still gated; no photo action attempted. Guest screen permits both devices, countdown and Leave. Native first turn pending at time of entry.

- 2026-10-18T03:01:44.087171+00:00: **PASS, actual UI/context/voice, runtime f228b39**. First reply identified online phone/speaker and retained marigold; audit TEXT_DEFAULT, no say. Natural opt-in replied with marigold + enabled message; narration ACK r_7bc21a95775a49beb5e715d16dea0a4c. Follow-up phone-capability reply narration ACK r_1e703f249616486483657958e96c9da2. Explicit opt-out and contextual follow-up both TEXT_DEFAULT, zero say. One-off requested phrase dispatched say once, ACK r_d4f9463e7df243c492dc879f26ea6320; automatic narration EXPLICIT_SPEECH_ATTEMPTED suppressed. Jay directly confirmed hearing these replies/phrase and silence for text-only turns. Human confirmation covers this voice sequence, not later effects.
- Root clarified20s as experiment observation window, not product duration requirement. Watchdog may revoke ONLY this test guest via existing authenticated host endpoint; no reset/rotation. Cases5–6 will use this safety bound if established; no durationfeature requested.

- 2026-10-18T03:02:24.084225+00:00: Post-one-off contextual reply “Marigold.” remained TEXT_DEFAULT. Re-enabled ongoing voice and received a further narration ACK r_3466624a2d124d219a215ebfeb24ecf1 before Leave, so the next guest isolation check begins after a voice-enabled predecessor. Leave reached terminal “Your access has ended” and disabled composer/send. This proves UI ending/prevention; no forged stale request has been sent, so a separate backend rejection is not inferred.
- **FAIL — room-screen promise at f228b39:** after this guest’s eight actual turns, public display conversation still shows “Waiting for their first message…” (only ordinary ledger sentences appear). Entry promises requests are shown on the room screen; Root already identified this missing projection seam. Historical headline also remains Guest1 joined despite Guest2 just leaving. No production fix by tester.

## Batch1 completed — October17,20:04 PT

**QUIET HANDOFF: both test guests LEFT; final phoneOFF/audioSTOP confirmed; watchdog DISARMED without firing; gate HELD for Root rollout; no more effects until a new ready release.** Lock release immediately follows this entry.

| Case | Result | Evidence / limits |
| --- | --- | --- |
| Default text + contextual follow-up | PASS | Actual guest UI retained marigold and offered voice choice; TEXT_DEFAULT with zero say. Same fixed native room conversation, not a replacement agent. |
| Natural ongoing voice opt-in/opt-out | PASS | Two opted-in replies ACKNOWLEDGED; opt-out and subsequent contextual replies TEXT_DEFAULT. Jay directly confirmed hearing the expected voice and silence between. |
| One-off say while opted out | PASS | Exactly one say ACK; EXPLICIT_SPEECH_ATTEMPTED suppressed duplicate narration. Next contextual reply remained TEXT_DEFAULT. Jay heard “Tenant test ready.” |
| Fresh guest context + voice default | PASS | Prior guest re-enabled voice and received ACK before Leave. Next guest first reply stated it saw no prior remembered word, omitted marigold, used generation5 in SAME native thread, and TEXT_DEFAULT with no say. This is conversational+structural generation evidence, not a full independent memory-isolation audit. |
|2sON/2sOFF30BPM | PASS within smoke scope | Actual UI requested30BPM and2sperstate. Program p_99aa5c4b65b8416fb24d4178c6b3dce0 emitted9 alternating phone edges; all ACK OK, all8 target intervals exactly2000ms. First edge20:03:03.842PT; final program edge20:03:19.937PT. Jay confirmed roughly2s visible ON/OFF plus audible beat. No calibrated optical/acoustic timing or synchronization claim. |
| Separate phoneOFF / beatstop | PASS | Fresh phoneOFF request native turn01a14cf6-a346-7ac3-9ff5-8b3572728635; OFF ACK r_a70135914a724c098f0337190c9812e2 at20:03:20.262PT. Guest text confirmed unchanged30BPMbeatcontinuing. Separate beatstop turn01a14cf6-e26c-7c53-abe9-c0c0bef1c1a8; requested_stop cleanup phone/audio both confirmed20:03:37.774PT. Jay confirmed phone remainedOFF while beatcontinued, then beatstopped. No late pulse rows afterward. |
| Finite experiment cleanup | PASS | One-shot60s watchdog privately armed for ONLY secondtestguest via existing /host/revoke. Normal UI stop achieved confirmedcleanup; watchdog DISARMED20:03:41.966PT before deadline, neverfired.20s was observation target, not runtime durationfield: actual phone pulse train~16s; firstphoneedge→fullstop~34s. No scheduler, reset, invitationrotation, service restart, outputswitch or volumechange. |
| Leave / ended UI / reconnect | PASS within UI scope | Both guests reached terminalended access with disabled input/send; secondguest Leave20:03:54.068PT. Reloading secondguest remainedterminalended, no restored controls/native turn/physical dispatch. The disabledUI prevents a stale control request, so a separate backend actiondenial is not inferred. |

Audit totals since offset129745:12 distinct native turn IDs (14 cmd rows include2 device-action rows); zero UNKNOWN audit outcomes; no tester host/device command except natural guestactions. Newguest firstturn native01a14cf5-ee86-7481-a57c-274b07a5c0f9, fixedthread01a14c77-6542-7e42-9067-bb1d28aec72b. Private filtered correlation evidence: /Users/jay/Documents/Codex/2026-10-17/tenant-e2e-tester/work/batch1-private-evidence.json. Screenshots: outputs/guest-performance-stopped.jpg and outputs/guest-access-ended.jpg in the tester chat workspace. No credentials/fragments/phone numbers in evidence.

Failures retained for owners:
1. Entry advertises photo while feature remainsgated.
2. f228b39 publicconversation absent despite entrypromise; display says waiting after actual guestturns. Root reports independentlyreviewed c7e902b candidate fixes this seam; NOT deployed/tested by this tester yet.
3. Display headline and rail consume oldest publiclog first (f228b39 display.html177,218). At20:04:08PT headline still19:56:03 Guest1joined and visible rail ends20:03:05 despite confirmedstop20:03:37 and leave20:03:54. Actual screenshot/AX observed; no Owen-owned fix made.

Physical expiry, calibrated AV alignment, Photon, microphone input/denial, queued cancellation races and unbriefed participantjourney remain outside this batch. No repeated expiry prompt, no missing-asset retry and no features unlocked. Next release should be text/display-only c7e902b check after Root rollout, as requested.

- Handoff concurrency note: final compare-before-write gate check detected Root had already changed the gate, so tester did NOT overwrite it. Exclusive test lock RELEASED successfully; no effects attempted after the change. See latest observed gate state in this chat.

## Jay steering — 2026-10-18T03:05:08.437278+00:00

Stop further pure generated-beat + phone-light tests. Jay is interested in actual music playback (YouTube or similar) plus beat matching, restricted for now to **Daniel Caesar**. This supersedes further standalone beat/light trial planning; do not play other artists or substitute a generic/calm generated backing track. No new playback initiated; current gate Root/held and test lock released.

Next musical acceptance should establish: actual permitted Daniel Caesar recording visibly selected and audibly playing; preserved default output/current volume; repeatable connection between the phone pulses and the recording’s real beats (phase as well as tempo); conversation and explicit phoneOFF/musicstop remain usable. Generatedbeat timing/ACKs do not establish song beatmatching. If current runtime cannot analyze/follow actual music, report the capability gap to Root in these notes rather than claiming a match or starting a competing generatedbeat. Only ask Jay for unobservable physical/acoustic results after initiating a released finite trial. Root’s pending text/display rollout check is read-only with respect to physical outputs and may proceed on its next release.

## Batch2 — c7e902b actual UI display recheck, October17 20:05–20:06 PT

**COMPLETE / QUIET.** One fresh guest, one harmless text exchange, no device effects. Test guest LEFT20:06:15.067PT. Lock released immediately after this record; gate held for Root.

- Exclusively created/flock-held testlock; gate ready c7e902b. Initial display room8157, both devices ready, no guest/log since Brain-only restart.
- **PASS joining ring / countdown:** guest joined20:05:40.487PT; display1:59 and “next2min”; at1:56 nearlyfull ring had143drawnrects and maximum occupiedangle343.07degrees. This actual DOM geometry corroborates120-second denominator rather than a600-second~70degreewedge. Deployedsource c7e902b snapshot uses joining_total120; no page-state globals read.
- **PASS active original600:** firsttext sent20:05:49.731PT; display immediately9:50 (not restarted10:00), later9:32; ring at9:32 had140rects/max328.24degrees, consistent with600-second originalgrant and visualleadingfade. Issuance→activation consumed~9s as expected.
- **PASS actual room conversation projection:** guest “Hello! This is the cobalt display check. Please reply briefly with ‘Welcome, display tester.’ No device actions.” appeared under Conversation at20:05:49; roomreply “Welcome, display tester.” appeared20:05:53. Same visible strings in guest UI; no private IDs/credentials in publiccopy. This innocuous exchange validates publication, not an adversarial live redaction proof; secrets were not injected. Root’s redaction sourcechecks remain supporting evidence.
- **PASS current displayed controller for this singleguest:** Guest1 and its actualconversation selected. Multiple simultaneousguest ordering was NOT exercised in this oneguest check; source snapshot prioritizescontroller thenactive.
- **PASS departure:** Leave terminalended disabledcomposer; publicdisplay showed “Guest1left.2devicesarestillhere.” with fadingconversation, then “Nobodyishere” and no publicconversation after normal6sdeparturewindow. Persistent ledger sentences remain expected. Headline oldest-event issue stillvisible20:05:40joined vs20:06:15left, retained from batch1.
- Audit from146571: one native turn01a14cf9-019f-7e90-9db0-6b573f369a2f, generation1, TEXT_DEFAULT, no sayreq, ZERO deviceactionrows; no output/volume changes, resets or restarts by tester. Screenshots in tester outputs: display-joining-c7e902b.jpg, display-conversation-c7e902b.jpg, display-after-leave-c7e902b.jpg.
- Previous batch1 physicalanswer is RESOLVED: Jay explicitly confirmed all2sON/OFF, phoneOFFwhilebeatcontinued, thenbeatstop. No pendingquestion/repetition.
- Jay’s newest scope remains actual DanielCaesar music + matchingthemusicbeat; no further puregeneratedbeat/light tests. No music playback started in this display-only release.

## Prepared next music trial — no playback yet

Jay said continue after restricting the music scope to DanielCaesar. Candidate actual recording: **CYANIDE**, official YouTube artist recording https://www.youtube.com/watch?v=Jnm3ukzmJe4 (search verified DanielCaesar / CASESTUDY01 / officialartistchannel; no assumedBPM). Prefer this album recording over similarly titled SpotifySingles, remixes or fanreuploads. No page opened that could autoplay; no otherartist played.

Proposed natural request once effecttesting is released: “Play DanielCaesar’s CYANIDE onYouTube. Have the phone light follow the actual song’s beat. Don’t add a generated backing beat or change my volume/output.” First confirm actualsong playback/source, then add phone only if engine can explain/use a songphase source. Explicitstop phone and music separately; establish test-only watchdog appropriate to actualmusic because program revocation may not stop an independently opened YouTube tab. A browser player needs its own confirmedpause/cleanup path before playbacktest.

Current roomprogram source is specifically a generatedbeatbridge: beat.prepare/start/status/stop phase reference is its generatedaudio processlaunch, not arbitraryYouTube playhead/onsets. Treat songmatching as a capability gap until a supported actualsongtiming seam is identified; no guessedBPM + independentlystartedpulse accepted as beatmatching. No productionimplementation by tester, no extra purebeat trial.
