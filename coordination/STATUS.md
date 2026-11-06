# Current Status

Updated: 2026-11-06

## Active

User-requested Codex takeover: C-088 is signed off. Luna generated the offline review-only five-rung fine-residual fidelity/runtime ladder; independent review verified all five NC/preview hashes against the report, zero added omission on the full-fidelity rung, and monotonically increasing omitted artwork across coarser rungs. Run F (C-018 to C-020) reached its checkpoint after C-020; all three tasks are implemented pending planning review. Keep all artifacts offline/review-only and preserve unknown machining facts as release blockers. C-110 through C-112 are signed off.

Machine-first Pine and background CAM (C-098–C-112) and the instruction and hardware records work (C-113–C-116) are signed off. Evidence includes offline CAM, offscreen desktop and isolated simulator tests, and the packaged Python entry-point smoke check. Real machine data cutover remains an operator maintenance action.

Run C-096 reached its review checkpoint: /root implemented and verified the offline design-to-CAM workflow and backend API discovery. All three bundles replay byte-for-byte; 145 focused tests passed. See HANDOFFS.md. No live application or hardware interaction.

C-095 implemented by /root for design review: wider tapered rays, preserved motifs, rebuilt lettering, 30-degree V-bit surface rendering from exact emitted paths, and strict row-order water clearing. Offline candidate is not approved or released for cutting; ray positions were visually interpreted, ply colors unknown, and water-interface floor metric is not assessable at the intentional tapered outer edge. See HANDOFFS.md.

C-094 implemented by /root/auto_continuation_implementation. Explicit per-job API/CLI automatic continuation after recovered homing, fresh verified saved-zero return and normal application start authorization. Strict simple G0/G1 milling replay dialect; prior retract boundary before accepted-32, original source mapping preserved; max3 continuation attempts, 120s return timeout. Machine/tool configuration, saved XYZ, source identity and independent safety input bind permission; operator pause/abort/manual motion/config changes cancel it. Policy recorded but requires re-enable after backend restart. Source only, active job untouched; primary owns activation. Focused backend suite59 passed; added repeat-loss/timeout tests bring auto suite to16 passed. See docs/AUTOMATIC_CONTINUATION.md.

C-092 implemented by /root/recovery_home_completion: watchdog recovery stays active during home-requested and transitions to recovered only after a newer fresh Idle/spindle0 report and trusted reference; disconnect retries the saved endpoint. Nine focused tests passed; no hardware/process/GUI interaction. Primary owns activation and continuation.

C-091 implemented by /root/approved_design_geometry: offline approved-image dark-mask vectorization, concentric local broad and fine residual CAM in `artifacts/ornaments/hawkeye/two-bit/c091-approved-raised-plane/`. Exact SHA `2cba5384...`: 77,893 commands, 67.28 nominal minutes, 0.9303% cutter-inaccessible dark area. Exact-file per-depth full-width verification passes with zero excess sweep; final rendered depth preview inspected. Primary owns integration and hardware execution; existing test cuts remain irreversible.

Run C-077/C-078 implemented by codex-primary: Pine GUI was reloaded with the corrected live-overlay transform. The full optimized C-069 flow profile was loaded into the same saved 100 mm work frame and started by explicit user authorization. Do not interrupt the active job.

C-079 (codex-pause-revision): implemented source-only. Pause ignores telemetry revision races and reaches JobService even under the motion gate. Focused test: 5 passed. Requires later normal backend activation; the current active run was not touched.

C-080 (codex-layer-visibility): implemented. Run-page checkboxes independently toggle current cutting layer, all cutting paths, and rapid paths; preview categories are separate for raster and small vector jobs. Focused preview/QML tests passed. Source only; current running job and Pine process were not disturbed. UI changes await the next authorized app reload.

C-081 (codex-watchdog-autorecover): implemented source-only. Silence watchdog already sends realtime feed-hold/soft-reset; recovery retries saved Wi-Fi up to 8 times, requests M5 after each connection, retries if M5 acknowledgement or fresh Idle/0-RPM confirmation is lost, then invokes existing guarded home. The failed engraving is never resumed or restarted automatically. Focused tests: 8 passed. No live app/backend/controller interaction or restart.

C-082 (codex-status-payload): implemented source-only. Root cause was the client decoding snapshots with the 256 KiB request limit while the protocol allows bounded responses up to 1 MiB. Client now uses the response bound for success and error payloads. API suite: 11 passed; no active process or machine interaction. Requires normal future Pine reload for activation.

C-083 (codex-safe-continuation): implemented offline. Reproducible continuation bundle starts at source command 4063, the next retract/XY rapid/approach/plunge boundary after command 4000; exact source suffix and parser/safety checks pass. Primary owns physical loading/start.

C-084 (/root/runtime_cam): implemented offline broad-only candidates with full-width-verified stay-down links, generic parsed-motion analysis and the reusable nominal-only runtime helper. Higher-fidelity 0.08 mm and lower-command 0.50 mm candidates, exact hashes, sweep previews, and quantified coverage/runtime tradeoffs are in `artifacts/ornaments/hawkeye/two-bit/c084-runtime-45m/README.md`. The 45-minute goal is aspirational; no completed comparable run exists for a physical estimate. No candidate was loaded or started.

C-085 (codex-runtime-diagnostics): implemented offline. Current estimate understates observed prefix duration by about 4.8–5.1×; details and evidence are in HANDOFFS. CAM workload reduction is dominant; current streamer already uses character-counting, and historical Bf:0 samples show the planner full during slow cutting. Machine-specific acceleration/junction settings remain uncollected.

C-086 (/root/performance_workflow): implemented offline. G-code analysis adds relative short-segment/junction/retract metrics and optional conservative target comparison using profile-matched completed runs. One or more completed runs produce a provisional projection; three or more label it established. Target comparison is informational only and never blocks execution. Workflow instructions document the estimate's limits.

C-087 (codex-hybrid-pocket): implemented offline. The assumed 3.175 mm endmill has no conservative center-accessible area in the approved art; smaller-tool sensitivity is documented, and no endmill job was emitted to avoid fidelity loss. The exact C-069 V-bit comparison parses at 89.85 nominal minutes and retains its previously verified sweep/coverage. The 45-minute goal is aspirational. Evidence: `artifacts/ornaments/hawkeye/two-bit/c087-hybrid-pocket/`; no physical readiness claim.

C-088 (luna-execution): done after independent planning review. Five progressively coarsened fine-residual variants preserve exact C-084 broad paths; exact parsed G-code, conservative full-width sweeps, coverage, motion and nominal runtime tradeoffs are documented in `artifacts/ornaments/hawkeye/two-bit/c088-detail-ladder/`. All NC and preview hashes match the report, the full-fidelity rung adds no omission, and omitted artwork increases monotonically across coarser rungs. No physical readiness claim or machine action.

C-089 (codex-primary): implemented offline by current user request. `artifacts/ornaments/hawkeye/two-bit/c089-adaptive-regions/` contains a 7,669-command, component-local broad-only candidate (SHA `31c2773c...`) with 92 concentric components, five local stay-down links, and a verified scanline fallback in the reusable planner. It is materially simpler than C-084 (19,744 commands), but has 70.75 mm² additional broad-art omission because it remains broad-only. The active job was not loaded over, interrupted, or otherwise touched.

C-090 (codex-primary): implemented offline. `artifacts/ornaments/hawkeye/two-bit/c090-full-fidelity-completion/02-detail-c090-fine-residual-completion-review-only.nc` (SHA `fabf3a2d...`) is the aligned shallow Z−0.04 mm completion required after C-084. Combined C-084 broad + C-090 fine coverage leaves only 23.74 mm² (0.985%) inaccessible to the specified cutter, consistent with the full-detail C-069 treatment; broad-only intentional omission is eliminated. No physical job action occurred.

C-077 (codex-primary): implemented. The frontend now maps through the PreserveAspectFit painted rect and backend's 12 px letterboxed source content rect; preview test passed and Pine was reloaded.

C-078 (codex-primary): implemented. C-069 flow SHA f38e959b… preserves bounds X0–98.9343/Y0–98.1448/Z−1.625–3.0 and the 30° 0.1 mm V-bit settings. Fresh execution is running from work (0,0,0); do not interrupt.

C-076 (codex-reset-auto-home): implemented. A positively detected GRBL banner/reset now enters saved-Wi-Fi recovery and automatically requests guarded home only after M5 acknowledgement and a fresh Idle/0-RPM report. Watchdog silence still requires explicit Continue-to-home/Cancel. Recovery/API/application contract tests: 66 passed; compileall passed. Source/tests only; Main.qml and live process/backend/GUI/hardware untouched. Evidence: HANDOFFS.md.

C-072 (codex-recovery-state-machine): Implemented a three-attempt exact saved-Wi-Fi reconnect after the backend job watchdog trips, then requests M5, waits for its acknowledgement and a fresh Idle/0-RPM report, and exposes explicit Continue-to-home and Cancel actions. Homing never starts automatically. Focused recovery/CLI/API/application-contract suite: 64 passed; compileall and scoped diff check passed. No live backend, GUI, or hardware interaction.

C-073 (codex-pause-bookmark): Implemented pause bookmarks only after a post-request Hold report and fresh backend status. Persisted evidence binds exact program SHA, tool report/offset, run and machine IDs, accepted/sent counts, plus a review-only recovery fence. Backend restart downgrades it to historical evidence and clears live-Hold confirmation; no automatic resume. Focused backend/API/adapter/Qt/application suite: 145 passed. No live process, hardware, or motion interaction.

C-075 (codex-cam-order-metrics): implemented offline CAM release metrics for rapid/cut/plunge distances, retracts, stay-down links, short segments and junctions. Exact emitted G-code is cross-checked; settings and output hashes are bound into reports. Safe path order/direction scheduling is verified against unchanged cutter-sweep coverage. Focused tests: 44 passed. No live app/backend/hardware interaction.

C-071 (codex-primary): Implemented source-only active Run visualization without touching the current job. Backend produces a bounded current-cutting-layer vector overlay; UI draws that layer green above the complete raster and a fresh work-coordinate cutter dot orange in the same job coordinate frame. Run timing now separates planned feed-based duration, observed active time, and nominal plan-left; it explicitly says physical ETA is unavailable until position-progress tracking is calibrated. Tests: 66 backend/adapter/contracts passed and QML shell 61 passed. Activation requires a later normal restart; no controller/backend/GUI-process interaction occurred.

C-070 (codex-primary): Implemented source-only durable recovery record for both Pine UI and agent/backend snapshot. It persists exact program SHA/path, machine ID, sent/accepted/total counts, terminal reason, and review requirement; backend restart reclassifies active records as interrupted. UI labels it as review context, not a position-safe resume. No controller, GUI-process, or backend-process interaction occurred; active job was not interrupted. Focused backend/API suite 53 passed; backend/CLI/adapter 26 passed; QML shell 61 passed.

C-069 (codex-primary): Operator confirmed the C-069 stop was unintentional. Fresh reconnect state was Idle/spindle0 with MPos reset 0,0,0 and untrusted reference. Guarded home completed; persisted XYZ was restored and verified at work (0,0,0). Exact SHA `bef0b50e...` first-boundary-smoothed candidate is reloaded; envelope preflight passed; user-authorized retry is active. At 540 accepted commands it was fresh Run/spindle command 1000. A 16-sample active-window feed median was 112 mm/min (17–359) despite F675; target-closeness remains unproven. Do not disturb active job; collect evidence and plan next change only after authorized stop.

Run C-061–C-068 closed after integration: full suite 894 passed in 232.99 seconds. Preview, exact-hash provenance, job lifecycle, timing/telemetry and offline analyzer complete; twin NC control and Review-step mismatch fixed; stale test fixtures updated. Running app/backend unchanged; source requires a future separately authorized restart. No app or hardware interaction.

C-059/C-060 review checkpoint complete: reusable CNC guidance added; QML no longer draws a fictional preview and labels feed-based estimates and envelope checks accurately. Focused tests 29 passed. Running app/backend unchanged; source changes require future authorized restart. UX audit identified additional provenance, large-preview, and historical-job-state work.

C-058 implemented offline: operator abort verified fresh Wi-Fi Idle, spindle command 0, job inactive. The independently verified replacement reduces nonzero XY moves 158857->88676 and the opening boundary 5966->665 while retaining modeled full-diameter containment; approved-black omission increases 7.1765 mm2. Candidate is not loaded and physical throughput is unverified. No restart, motion, GUI interaction, load, or new start occurred during repair.

Optimized 450/120 deep+fine candidate loaded; fresh Wi-Fi Idle, homed and returned to saved zero, live preflight passes, can_start true, job idle. No start sent. Physical throughput unverified; estimated ~118min excludes acceleration. C-056/057 independent sweep and streamer audit passed; backend event-wake source active after restart.

C-057 claimed: optimize fine pass, which contains ~79% of XY segments; C-056 independent full-diameter verification in progress. No hardware motion.

C-056 primary: audit speed candidate, discovered possible radius/diameter mismatch in swept-area metrics; do not load until corrected. No motion.

C-052/053 diagnostic complete, C-054/055 offline candidate/source tested, not active; original 600/160 aborted job loaded. Reported physical speed improvement not verified. No motion or restart.

C-055: investigate/fix streamer polling throughput with fake transports; C-054 offline path optimization. No hardware motion.

C-054 offline optimization: actual run feed telemetry ~77mm/min max in retained events despite F600, inspect short segments/planner. No hardware motion.

C-053 feed diagnosis: quantify actual controller feed vs programmed speed on prior aborted run; no machine interaction.

C-052 offline 2x feed candidate; run aborted by operator at 621 commands, physical cause and spindle setting pending user. No machine motion authorized during preparation.

C-051: deep+fine file loaded, preflight passed, Wi-Fi Idle and zero trusted, not started. Broad 1.625mm, fine .04mm, 94.36min, 0.664% black omitted; in-app preview unavailable, prior failure remains historical state.

C-051 claimed: add separate fine detail pass to deep engraving, verify and load; user instructs do not start.

Deep broad-only test loaded but NOT started per user: 1.625mm, three passes, 600/160, 1000 RPM, ~46min, 27.7% source black omitted including aircraft outlines. Wi-Fi fresh Idle, reference and saved zero confirmed, preflight fits, can_start_job true; old failed job remains historical display. Ply interface unverified.

C-049: diagnose Wi-Fi job failure after 143 commands. C-050: 2x feed offline candidate. Primary owns reconnect/home/zero/retry; no motion until machine status verified.

C-046–C-048 implemented and 134 tests passed; restart needed to activate GUI sync and spindle-off guard. Previous Start rejected before motion; corrected file prepared, not loaded. Await explicit restart authorization per AGENTS; preserve reference/work zero until then.

C-048 stream-review: fresh spindle-off job-start enforcement, no hardware interaction.

C-047 gui-freshness: GUI shows no loaded job although backend has program. Diagnose and repair; no motion until operator can observe job.

C-046 primary: streamer rejected initial M5 before motion; correct program and verify GUI freshness, then user-authorized start if current state permits.

First engraving loaded and backend start-ready: user-confirmed setup, fresh Wi-Fi Idle, homed and XYZ confirmed, plate removal acknowledged without motion, preflight passes. Start not sent. Large-job in-app preview unavailable; external sweep preview supplied. Cutout 3.25mm prepared separately; second-tool setup remains after engraving.

C-044 probe popup investigation; C-045 cutout for measured 3.25 mm stock, offline. User reports puck/clip removed; no movement authorized.

C-043 active: optimize 30-degree detail and prepare first job for user to start; primary verifies hardware state and cutting parameters. Do not start job or move machine. Independent machining-parameter review in progress.

C-040/C-041 source tested and app/backend restarted; fresh Wi-Fi Idle, reference requires home, no agent motion. C-042 assigned to workflow audit for actionable guidance and Home projection alignment.

C-041: remove circular XYZ and unnecessary XY work-zero prerequisite from Z probe; keep actual motion checks. Live controller Wi-Fi fresh Idle, reference trusted, plate ready, but work-zero not confirmed. No motion by agent.

C-040 claimed by codex-stale-status for source diagnosis/repair; primary owns live backend checks and user-authorized restart, no motion.

C-039 offline review candidate generated and visually checked: 189.2min and 1.71% omitted, still impractical; faster alternative 130.7min and 3.24% omitted. Further optimization and cutting release remain. C-042 source guidance tested but not activated in running app.

C-038 complete: recorded user-supplied 30-degree / 0.1 mm V-bit and flagged earlier detail draft as mismatched. Regenerate detail for actual tool.

C-037 source complete, 131 focused tests passed. Backend was disconnected with no saved record during inspection; historical WCO X19.733 Y21.000 is not verified current. Running app not restarted; no motion or GUI interaction.

C-036 source repair and focused review complete: 82 tests passed. Running instance remains on old code; real-machine acceptance not performed. No motion or GUI interaction.

C-032: current probe reports ready; original block reason unresolved. C-033 saved-zero display and return source complete and tested; restart needed to activate. C-035 instructions updated. C-034 candidate saved separately: 98.47 min estimate, but coverage and preview remain unverified; baseline restored. No hardware motion or GUI interaction.

### Two-bit slice — completed review checkpoint — 2026-11-01

User withdrew single-bit design. C030 closed with restart completed and its
one-bit draft retained as abandoned review evidence. C031 completed by
codex-two-bit-slice: restored approved detailed art with60degreeV-bit file and
separate assumed3.175mm endmill hole/profile file, common110mm stock frame,
partcenter55,55. PreserveXY and re-probeZ aftertoolchange. No further restart,
homing or cutting authorized. Workers Luna extra-high only.

Review files and independent-verification.json saved in artifacts/ornaments/hawkeye/two-bit. Detail estimate 182.62 minutes; cutout 8.71 minutes. Review only: no spindle startup, nominal tooling/material assumptions remain; detail runtime needs optimization before production. Parser, cutter sweep, hashes, clearances and visual review passed. Neither file loaded or executed.

### Previous one-bit slice and activation — 2026-11-01

C-030 claimed by codex-one-bit-slice. User authorized app/backend restart
and single-endmill slicing, not cutting or homing. Verify connected Idle and
spindle-off before restart. Create offline review artifact with all assumptions
and exact cutter sweep; do not silently release unverified production files.
Workers Luna extra-high only. Checkpoint: restart verification and slice report.
Restart complete: backend was reconnected and fresh Idle/spindle0/clear configured
homing gates verified first; exact project GUI process identity checked, then
closed and guarded backend shutdown accepted. New backend and GUI started;
Pine window/process present, new touch-continue-to-surface/live-jog-renew actions
advertised, Wi-Fi192.168.86.31 fresh Idle. Reference/workzero false; no homing or
cut authorized/performed. C027-C029 changes nowactive; slicing review in progress.

### Z-probe completion run — 2026-11-01

C-027/C-028/C-029 source is implemented and independently reviewed.
All workers after the model correction used Luna extra-high. Z probe now
shows verified result after retract+fresh Idle, one removal Continue and Z-only
slow descent to work0, with completion after ACK+fresh target Idle. No XY move.
Legacy removal ack cannot bypass continuation. Failures invalidate work zero.
Confirmation fingerprints ignore raw telemetry; meaningful changes still bind.
Stop commands bypass stale revision and cache replay. Held jog uses400ms press
lease/100ms renewal and <=200ms feed segments, waiting for newer Idle at target
and ACK before another; stale position/input trust cancels. Inner precision rose
controls pass offscreen1180/1500 geometry tests. No hardware motion/GUI access.

Final focused98 tests passed; earlier focused101 passed before final small
integration refinements. Full regression838 passed, same3 existing homing/NC
simulation workflow failures remained (no new regression). Scoped compile and
diff checks passed. User subsequently authorized backend AND GUI restart in
C030, completed above: the new controls and backend contracts are active. No
physical jog/probe test has been performed; prior C015 failures remain separate.

### Wi-Fi bootstrap run — 2026-11-01

C-025 is implemented and independently checked; C-026 is done.
USB is setup-only in production; backend verifies same-socket Wi-Fi handoff
before closing USB and invalidates reference/zero/token/status trust. Existing
Wi-Fi configuration is required; no password extraction or controller restart.
Focused suite120 passed; ownership/Windows/bootstrap suite75 passed. Full
suite795 passed,3 failed in homing NC debounce and guided twin progression
(test_homing_nc_integration, test_simulation_h6, test_ux2_batch_ef).
No claim of a clean full suite. Independent triage reproduced those3 failures outside the C025 policy path:
free-navigation expectation, Home prerequisite expectation, and simulated
raw-versus-logical NC limit polarity. They remain with in-flight C015 work.
C-026 replaces Windows signalling liveness probes with query-only handles and
repairs the missing authenticated-health version-validator import.

Source checkpoint reached. Running backend/GUI/hardware remains untouched.
User subsequently explicitly authorized restart and homing. Backend restarted
safely from connected Idle/spindle-off, then reconnected directly over verified
Wi-Fi192.168.86.31:23. Guarded homing completed; fresh Idle, spindle0 and trusted
reference verified. New production USB-setup-only policy is now active. Physical
USB-to-Wi-Fi handoff was not exercised because direct Wi-Fi succeeded.
No further execution task in this bounded run is eligible before that boundary
or disposition of the separate in-flight C-015 simulation/workflow failures.

### Ornament runtime correction — 2026-11-01

C-024 is done after primary sign-off and independent verification.
Corrected bounded path scheduling/stay-down links and added optional explicit
vertical approach clearance. Final regression suite: 123 passed. Nominal
real-art comparison: 625.63 min baseline ->238.67 min scheduling only with
unchanged settings ->146.94 min using an explicitly assumed .2 mm vertical
approach. Single-pass projection75.74 min additionally assumes .25 mm stepdown;
not tested on wood. XY rapid remains at3 mm. Default approach remains unchanged.
These are engraving-only estimates; no production release, no depth/feed/tool
measurements or physical commissioning. Remaining raster/detail limitations
require C-019/C-020 strategy changes. No hardware, GUI or backend interaction.
Checkpoint closed; other planned ornament tasks remain unexecuted.

### Previous ornament run — 2026-11-01

Run closed at its planning/review checkpoint: C-016 and C-017 are done.
Primary planning review accepted the code-backed backlog and independently
reviewed offline engraving exporter after 110 targeted/regression tests passed.
The exporter and a real-artwork diagnostic package are available; the package
is not released for cutting. At illustrative settings, aircraft contours are
lost (9.34% black area unreachable; eight components omitted), and the estimate
is about 626 minutes. The next planned work is C-018, then C-019/C-020 to resolve
physical inputs, fine-detail fidelity, hanger clearance, shared XY and runtime.
C-018 through C-023 are not authorized for execution by this bounded run.
No machine, GUI or backend interaction occurred. Existing C-015 ownership and
its earlier run scope remain unchanged.

### Existing application run (preserved)

`C-015` is in progress, owned by `codex-execution`, immediately after C-014's
software slice was implemented. C-014 replaces the legacy operator-facing
manual-reference and close-time return path with explicit guarded homing now
that homing switches are physically available. C-001 through C-014 remain
implemented pending combined planning sign-off; C-013 has a fail-closed
software contract but remains blocked at physical commissioning.

Authorized run delta: `C-015` is active immediately after implemented `C-014`.
The execution agent should complete C-015's software, visual-layout, backend
connection, documentation, and regression work without waiting for an
intermediate review. Backend-only hardware testing for C-014 is authorized if
necessary, subject to the exact readiness and no-GUI conditions in the task and
AGENTS.md; C-015 adds no physical-motion scope.

Latest C-015 slice replaces segmented/snap live jogging with one continuous,
travel-bounded GRBL jog canceled on release/focus loss; simplifies precision
steps; adds disabled-control explanations; adds confirmed click-to-position on
the virtual envelope; exposes guarded `move-to` through the backend contract;
and reduces the Home step to Home plus the retained jog controls. The running
backend has not been restarted, so it will not advertise `move-to` until an
operator-authorized restart loads this source revision.

## Blocked

The physical portion of `C-013` remains blocked at the commissioning boundary.
No electrical review, parts choice, wiring, energization, or machine acceptance
is authorized in this run.

## Next

Machine-first Pine and hardware records reached their software checkpoint. See [initiative details](BACKLOG.md#machine-first-pine-and-background-cam) and the C-112 handoff.

Complete `C-015` before returning the accumulated diff and evidence for combined
planning review/sign-off. The physical portion of C-013 can resume only after
separate machine-specific electrical authorization.

Review checkpoint: after `C-015` is implemented, or sooner only if a
genuine blocker prevents all eligible work. The planning agent then reviews the
combined C-001–C-015 software diff/evidence, requests repairs, and signs off.

## Repository context

- The working tree contained pre-existing modified and untracked files when this
  coordination system was created.
- No application instance was inspected or disturbed.
- Physical commissioning and hardware interaction remain outside the queued work.
- `C-013` captures physical E-stop integration, but the current software run does
  not authorize purchasing, wiring, energizing, or commissioning hardware.
- Backend/frontend separation is now the leading architecture initiative. Its
  target is one authoritative, persistent backend with restartable GUI and agent
  clients—not multiple application controllers or direct hardware access.



























