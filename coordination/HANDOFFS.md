# Handoffs

## C-095 interim — 2026-11-04
Owner /root. Offline water-region comparison is in `artifacts/ornaments/hawkeye/two-bit/c095-clearing-comparison/`; same V-bit and 0.12 mm finish spacing give scanline P95 residual 0.0263 mm vs concentric 0.0305 mm, and modeled samples within 0.05 mm of target 99.975% vs 98.411%. Nominal time is 14.96 vs 13.68 minutes, not measured machine time. Updated `docs/AGENT_CNC_JOB_WORKFLOW.md` to compare floor residual rather than prefer concentric unconditionally. Fixed C095 verifier and generator to include all rough and finishing passes in the height model; `.venv/Scripts/python.exe artifacts/ornaments/hawkeye/two-bit/c095-cutter-faithful-redesign/verify-and-illustrate.py` reports zero difference from prior preview on 0.025 mm grid and independent line formula error 5.68e-7 mm. Clean-letter artifact still in progress; C095 remains open and review-only.

## C-095 review candidate — 2026-11-04
Owner /root. `artifacts/ornaments/hawkeye/two-bit/c095-lettering-wider-rays-review/` contains a new review-only engraving candidate, preview and report. Rebuilt lettering at Z-0.45 has no missing glyphs and its conservative cutter envelope has zero pixels outside the letter mask; palm, boat and border overlap checks are zero. Nine tapered rays widen from 0.8 to 3.3 mm along the previously used positions; photo matching is visual, not metrologically measured. Water finishing uses strict alternating rows, with overlap into adjacent regions. `independent-height-verification.json` reconstructs every emitted depth from exact NC SHA `5c3c042aa126a17528277caac6c37d0326b30f6d5c5027982673453300e0eff4` and matches preview height grid exactly at 0.025 mm sampling. Preview visually inspected by /root. Water/other interface residual is not assessable as flat-floor metric because that interface lies inside intended V-bit exterior taper; `verification.json` remains review_required. Nominal engraving estimate ~101 min excludes acceleration, and 108043 commands / 5563 retracts make actual time uncertain and potential further path optimization worthwhile. Wood layer interface/color unknown; no physical job release or machine interaction in this run. User review of revised art required before any physical use.

Append newest entries directly below this introduction. Workers report completion;
verifiers report acceptance or return. Keep entries concise and link durable detail.

## Entry template

Copy this block and replace every placeholder:

```markdown
## YYYY-MM-DD HH:MM TZ — C-NNN — worker|verifier — agent-name

- Result: ready for review | accepted | returned | blocked
- Summary: <what changed or what was verified>
- Files: <paths, or none>
- Verification: `<exact command>` → <result/count>
- Remaining: <known gaps, follow-up, or none>
- Commit: <hash, or uncommitted>
```

## 2026-09-14 — C-015 — planning correction — codex-planning

- Result: execution guidance updated
- Summary: Moved the planned Home control out of the jog panel and directly above work-zero controls so the UI reflects the required Home → Work Zero sequence.
- Files: `coordination/BACKLOG.md`, `coordination/HANDOFFS.md`, `.codex/sol-luna/EXECUTION_CONTRACT.md`
- Verification: documentation-only; C-015 acceptance and execution delta aligned
- Remaining: execution agent should apply this placement while implementing C-015
- Commit: uncommitted

## 2026-09-20 — C-015 Wi-Fi connection regression repair

- Result: connection repair implemented; C-015 remains in progress
- Summary: Preserved a successfully opened Wi-Fi transport when its asynchronous result is adopted, and restored the typed `ConnectionOutcome` contract across the persistent-backend Qt adapter so manual TCP/USB connection requests no longer crash while reading connection metadata. Added regressions for both paths.
- Files: `src/ttc3018_control/application/connection_service.py`, `src/ttc3018_control/backend/qt_adapter.py`, `tests/test_c015_workspace.py`, `tests/test_backend_qt_adapter.py`
- Verification: `.\.venv\Scripts\python.exe -m pytest tests/test_c015_workspace.py tests/test_backend_qt_adapter.py tests/test_tcp_connection.py tests/test_wifi_discovery.py -q` → 14 passed in 2.15s; `git diff --check -- src/ttc3018_control/application/connection_service.py src/ttc3018_control/backend/qt_adapter.py tests/test_c015_workspace.py tests/test_backend_qt_adapter.py` → passed. A broader run reached 61 passes with one unrelated stale assertion expecting the removed `Connect` primary tab instead of C-015's `Machine` tab.
- Physical verification: With explicit operator authorization, the guarded backend shutdown was requested. It stopped serving but left its exact `pythonw` host PID alive, so that stale PID was terminated and a fresh hidden backend was started. Backend session `10dd3d354d4f4b51a15335e9fea1fc29` then connected to the saved `192.168.86.38:23` endpoint and remained connected across a delayed status check. Fresh GRBL evidence was `Idle`, feed `0`, spindle `0`, no asserted pins, homing inputs `released`, and `can_home_machine=true`; no motion, homing, or spindle command was sent.
- Remaining: The GUI process was not restarted or manipulated. The guarded shutdown leaving its host process alive is a newly observed backend-lifecycle defect for planning triage; it did not prevent the bounded authorized restart or Wi-Fi verification.
- Commit: uncommitted

## 2026-09-20 — C-015 streamlined guided flow and homing control

- Result: requested UI refinement implemented; C-015 remains in progress
- Summary: Removed the click-through Safety item from the guided operator sequence while retaining the canonical safety calculation, backend interlocks, contextual hazard banners, and fail-closed homing/work-zero/run gates. Renumbered the remaining seven-step projection and all workspace mappings. Replaced the compact home icon with a normal full-width `Home machine` button matching the adjacent reference controls. Added a standing LUNA xhigh/max delegation instruction to `AGENTS.md` at the operator's request.
- Files: `AGENTS.md`, `src/ttc3018_control/application/workflow_projection.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_workflow_projection.py`, `tests/test_c015_workspace.py`, `tests/test_qt_shell.py`
- Verification: `.\.venv\Scripts\python.exe -m pytest tests/test_workflow_projection.py tests/test_c015_workspace.py tests/test_qt_shell.py tests/test_backend_qt_adapter.py -q` → 110 passed in 19.53s; targeted `git diff --check` → passed.
- Remaining: The running GUI was not restarted or interacted with, so it will load these source changes on its next operator-controlled restart. Backend safety gates remain active and the already-restarted backend remains outside this visual-only change.
- Commit: uncommitted

## 2026-09-20 — C-015 immediate frontend close

- Result: requested close-flow simplification implemented; C-015 remains in progress
- Summary: Removed the main-window close interception, homing prompt, close-bypass state, and Home-then-close ViewModel route. Closing the main window now immediately releases frontend resources without issuing homing or other machine motion; the normal backend-client path continues to leave the persistent backend/controller session alive. Explicit `Home machine` remains available in Machine. Restored the existing post-home digital-twin hazard-clear behavior as a separate status concern and retained contextual physical-safety recovery facts/actions after removing the dedicated Safety step.
- Files: `src/ttc3018_control/qt/qml/Main.qml`, `src/ttc3018_control/qt/view_model.py`, `tests/test_qt_shell.py`, `tests/test_ux2_batch_cd.py`, `docs/GUI_USER_TEST_REPORT.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest tests/test_ux2_batch_cd.py tests/test_workflow_projection.py tests/test_c015_workspace.py tests/test_qt_shell.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py -q` → 128 passed in 28.26s. Independent LUNA max audit confirmed the main close-time homing path is fully removed and normal backend-client close remains frontend-only.
- Remaining: The digital-twin child window still independently vetoes closing during an active simulated job; this is unrelated to the removed main-window homing prompt. The running GUI was not restarted or manipulated.
- Commit: uncommitted

## 2026-09-20 — C-015 explicit Home wizard step

- Result: requested wizard clarification implemented; C-015 remains in progress
- Summary: Renamed the first post-connection guided step from the internal-facing `Reference` label to the operator-facing `Home` label. Kept it as a distinct step between Connect and Work Zero, simplified its context card to a short Home-machine explanation, and retained the existing guarded full-width Home button and observed-completion advancement. Internal `reference_trusted` semantics and backend safety gates are unchanged.
- Files: `src/ttc3018_control/application/workflow_projection.py`, `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_qt_shell.py`, `tests/test_c015_workspace.py`
- Verification: `.\.venv\Scripts\python.exe -m pytest tests/test_workflow_projection.py tests/test_c015_workspace.py tests/test_qt_shell.py tests/test_ux2_batch_cd.py -q` → 117 passed in 23.66s; targeted `git diff --check` → passed.
- Remaining: The running GUI was not restarted or manipulated; it will show the explicit Home step on its next restart.
- Commit: uncommitted

## 2026-09-20 — C-015 step-based top navigation

- Result: requested top navigation expansion implemented; C-015 remains in progress
- Summary: Replaced the four broad Machine/Prepare/Review/Run tabs with visible pill tabs for every applicable operator step: Connect, Home, Work Zero, Prepare, Review, and Run. Configure remains a bottom utility. The canonical guided-step index now directly owns both selected-tab state and content routing, eliminating the competing workspace-selection path; unavailable future steps remain visible but disabled until prerequisites are satisfied.
- Files: `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_c015_workspace.py`, `tests/test_qt_shell.py`
- Verification: `.\.venv\Scripts\python.exe -m pytest tests/test_c015_workspace.py tests/test_qt_shell.py tests/test_workflow_projection.py tests/test_ux2_batch_cd.py tests/test_backend_qt_adapter.py -q` → 120 passed in 22.00s; targeted `git diff --check` → passed. Independent LUNA max audit confirmed the six-tab mapping and recommended the single guided-index authority now used.
- Remaining: The running GUI was not restarted or manipulated; it will load the new top tabs on its next restart.
- Commit: uncommitted

## 2026-09-20 — C-015 Apple-style design-system refinement

- Result: requested design philosophy identified and applied; C-015 remains in progress
- Summary: Grounded the redesign in Apple's current principles—purpose, agency, responsibility, familiarity, flexibility, simplicity, craft, and delight—plus the practical hierarchy/deference/depth guidance in layout, color, typography, and controls. Reworked Pine's semantic dark palette, layered surfaces, typography hierarchy, segmented step navigation, control radii/sizing, focus treatment, subtle feedback transitions, cards, banners, badges, fields, checkboxes, and footer/header restraint. Reserved accent color for selection/primary actions, made Abort explicitly destructive, added jog accessibility descriptions/focus rings, and removed truncation from actionable issue explanations. Backend safety authority and all guarded availability rules remain unchanged.
- Files: `docs/DESIGN_PRINCIPLES.md`, `src/ttc3018_control/qt/qml/Main.qml`, `src/ttc3018_control/qt/qml/components/ActionCard.qml`, `IssueBanner.qml`, `ModernCheckBox.qml`, `OperationBanner.qml`, `ReadinessStrip.qml`, `StateBadge.qml`, `tests/test_c015_workspace.py`, `tests/test_qt_shell.py`
- Verification: `.\.venv\Scripts\python.exe -m pytest tests/test_c015_workspace.py tests/test_qt_shell.py tests/test_ux2_batch_cd.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py -q` → 80 passed in 20.99s; targeted `git diff --check` → passed. Independent LUNA max audit prioritized the shared semantic system, non-truncated safety status, consistent focus, restrained segmented navigation, and destructive Run hierarchy implemented here.
- Remaining: The running GUI was not restarted, focused, captured, or manipulated. A later visual review after an operator-controlled restart can refine page-specific spacing and remaining legacy dialog styles without changing machine behavior.
- Commit: uncommitted

## 2026-09-14 — C-015 — planning — codex-planning

- Result: authorized after C-014
- Summary: Defined a unified Machine workspace, rounded four-item navigation, quiet healthy status, deterministic TCP/COM startup fallback, secondary Configure/Console utilities, contextual safety, and a live backend-MPos envelope marker.
- Files: `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`, `.codex/sol-luna/EXECUTION_CONTRACT.md`
- Verification: documentation-only; current eight-step navigation, header pills, connection dialog, Machine controls, envelope preview, ViewModel connection state, and relevant Qt tests inventoried
- Remaining: execution agent completes C-014 then C-015 with headless layout/behavior tests; no GUI interaction or new physical motion is authorized by C-015
- Commit: uncommitted

## 2026-09-14 — C-014 homing-first reference and close flow — implemented

- Result: implemented; C-015 claimed immediately under the same authorized run.
- Summary: Removed the operator-facing Establish/Set Reference route from QML,
  ViewModel, and the finite backend action registry. Workflow projection now
  requires complete X/Y/Z homing declarations and blocks missing/partial
  commissioning without manual position trust. The close dialog now offers
  guarded Home, then close plus Close without moving; duplicate clicks are
  rejected and close is emitted only after homing completes and a fresh Idle
  report is observed. Backend snapshots/adapters publish homing state and the
  guarded home readiness fact. The digital twin now honors the effective
  declared homing end and matches physical GRBL $5 input polarity.
- Files: `src/ttc3018_control/application/workflow_projection.py`, `src/ttc3018_control/application/controller.py`, `src/ttc3018_control/application/job_service.py`, `src/ttc3018_control/backend/dispatcher.py`, `src/ttc3018_control/backend/runtime.py`, `src/ttc3018_control/backend/qt_adapter.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `src/ttc3018_control/qt/qml/CommissioningDialog.qml`, `src/ttc3018_control/simulation/controller.py`, `README.md`, `docs/BACKEND_FRONTEND_SEPARATION_AUDIT.md`, `docs/SIMULATION_IMPLEMENTATION.md`, `docs/SIMULATION_SAFETY_COMMISSIONING.md`, `docs/STEP_25D_PROGRESS.md`, `docs/Z_TOUCH_PLATE.md`, `docs/GUI_USER_TEST_REPORT.md`, `tests/test_backend_api.py`, `tests/test_backend_separation_e2e.py`, `tests/test_qt_shell.py`, `tests/test_simulation_h6.py`, `tests/test_ux2_batch_cd.py`, `tests/test_ux2_batch_ef.py`, `tests/test_workflow_projection.py`.
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_api.py tests/test_backend_separation_e2e.py tests/test_backend_qt_adapter.py tests/test_simulation_safety.py tests/test_simulation_h7.py tests/test_simulation_h6.py tests/test_ux2_batch_cd.py tests/test_ux2_batch_ef.py tests/test_workflow_projection.py` → 95 passed in 30.58s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog"` → 50 passed, 1 deselected in 21.25s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Boundary: No GUI instance was launched or interacted with. No physical motion or hardware configuration was performed; optional backend-only hardware verification was not needed after the digital-twin and backend gates passed. The constrained `MachineSetupDialog.qml` layout test remains a pre-existing out-of-scope failure when the excluded test is run.
- Commit: uncommitted

## 2026-09-13 — C-014 — planning — codex-planning

- Result: authorized for execution
- Summary: Added a bounded homing-first workflow task: remove the manual Set/Establish Reference UI path and replace close-time return motion with an explicit backend-guarded Home-then-close sequence.
- Files: `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`, `.codex/sol-luna/EXECUTION_CONTRACT.md`
- Verification: documentation-only; current close dialog, workflow projection, backend lifetime boundary, and reference UI/tests were inventoried
- Remaining: execution must complete fake/digital-twin verification; backend-only physical testing is optional and permitted only after connected/Idle/spindle-off/safety-gate evidence, with no GUI interaction or implicit commissioning
- Commit: uncommitted

## 2026-09-12 — C-013 — planning — codex-planning

- Result: ready for future execution
- Summary: Defined physical E-stop integration as hardwired safety-rated power removal plus independently monitored NC feedback; DLC32 RESET/disconnect is correlated secondary evidence, never the sole identification path.
- Files: `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`, `docs/CNC_PLATFORM_BACKLOG.md`
- Verification: documentation-only; existing simulation E-stop boundary, backend initiative, controller declaration, and Makerbase RESET-header documentation reviewed
- Remaining: complete the modular backend run, then select exact safety relay/input hardware and schematic through a separately authorized electrical review and commissioning plan
- Commit: uncommitted

## 2026-09-12 — Coordination execution policy — planning

- Result: ready for use
- Summary: Replaced per-task waiting with bounded execution runs. Workers self-verify, record evidence at every task boundary, and continue through all eligible authorized work; planning review/sign-off happens at the run checkpoint.
- Files: `AGENTS.md`, `coordination/README.md`, `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`
- Verification: documentation-only; lifecycle, ownership, dependency, blocker, and sign-off rules cross-checked
- Remaining: execution agent should complete the authorized `C-001`–`C-006` run before the architecture initiative checkpoint
- Commit: uncommitted

## 2026-09-12 — C-001 — worker — codex-execution — repair

- Result: implemented
- Summary: Rejected conflicting `ControllerViewModel(application=..., root=...)` roots so application-owned and presentation-owned stores cannot diverge. Added the requested regression test.
- Files: `src/ttc3018_control/qt/view_model.py`, `tests/test_ux2_batch_ab.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_ab.py` → 12 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_simulation_public_scenarios.py tests/test_simulation_spawn_workers.py` → 19 passed; `.\\.venv\\Scripts\\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Remaining: Combined C-001–C-006 review checkpoint remains; the unrelated `MachineSetupDialog.qml` layout assertion is documented in the original C-001 handoff.
- Commit: uncommitted

## 2026-09-12 — C-001 — verifier — codex-review

- Result: returned
- Summary: Root isolation and lazy discovery evidence pass, but the public ViewModel constructor accepts a preconstructed application rooted at A plus an explicit root B, causing application stores and presentation stores to diverge. This does not meet the single consistent-root contract.
- Files: `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_ab.py` → 11 passed; `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_simulation_public_scenarios.py tests/test_simulation_spawn_workers.py` → 19 passed; `.\.venv\Scripts\python.exe -m pytest -q tests/test_qt_shell.py tests/test_application_contracts.py tests/test_simulation_core.py tests/test_simulation_h6.py tests/test_simulation_h7.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog"` → 123 passed, 1 deselected
- Remaining: Reject mismatched roots or canonicalize them, add a regression covering both arguments, and resubmit. The excluded QML layout assertion is unrelated to C-001.
- Commit: uncommitted

## 2026-09-12 — C-001 — worker — codex-execution

- Result: ready for review
- Summary: Resolved the application root before constructing controller stores; made the ViewModel require an explicit root from a preconstructed application; prevented direct USB enumeration during a digital-twin session; and rejected future Live preference versions. Added isolated evidence for every application/ViewModel store path, sentinel preservation across preference writes, malformed/future preference fallback, and separate lazy discovery/connect callbacks.
- Files: `src/ttc3018_control/application/controller.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/live_settings.py`, `tests/test_ux2_batch_ab.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_ab.py` → 11 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_simulation_public_scenarios.py tests/test_simulation_spawn_workers.py` → 19 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_qt_shell.py tests/test_application_contracts.py tests/test_simulation_core.py tests/test_simulation_h6.py tests/test_simulation_h7.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog"` → 123 passed, 1 deselected; `.\\.venv\\Scripts\\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed. Full affected command without exclusion has one unrelated pre-existing failure: `test_machine_setup_hardware_page_scrolls_within_the_dialog` expects `Layout.fillHeight: true` in `MachineSetupDialog.qml`.
- Remaining: Independent verifier should rerun the focused suite and decide whether the unrelated QML layout failure belongs to C-001 or a later UI task. No physical hardware, native app, non-loopback endpoint, or user-owned instance was accessed. Manual GUI relaunch remains required for source changes.
- Commit: uncommitted

## 2026-09-12 — Coordination bootstrap — planning

- Result: ready for use
- Summary: Added a queue, live status, and append-only worker/verifier handoff channel.
- Files: `AGENTS.md`, `coordination/README.md`, `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`
- Verification: documentation-only; links and repository diff inspected
- Remaining: reconcile existing in-flight work before assigning `C-001`
- Commit: uncommitted

## 2026-09-12 — Backend/frontend separation backlog — planning

- Result: ready for use
- Summary: Added `C-007` through `C-012` for completing and proving a persistent backend, restartable GUI, and guarded agent interface.
- Files: `coordination/BACKLOG.md`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`
- Verification: documentation-only; source entry points and existing backend tests inspected
- Remaining: audit the in-flight uncommitted implementation before assigning changes
- Commit: uncommitted

## 2026-09-12 — C-002 — worker — codex-execution

- Result: implemented
- Summary: Bound public job-start authorization to the current session, reviewed
  job content, machine/reference/WCO state, live safety facts, supervisor health,
  fixture/work-zero state, and fresh status generation. Added explicit
  unavailable/fresh/stale status and not-applicable/unavailable/healthy/unhealthy
  supervisor projections; invalidated one-use authorization across reconnect,
  reset, close, disconnect, and transport replacement; and added public-path
  coverage proving same-name program replacement cannot execute commands after
  review. Preserved lightweight polling test doubles and repaired the setup
  surface's required NO polarity wording.
- Files: `src/ttc3018_control/application/controller.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/simulation/runtime.py`, `src/ttc3018_control/qt/qml/MachineSetupDialog.qml`, `tests/test_ux2_batch_ab.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_ab.py tests/test_application_contracts.py tests/test_homing_nc_integration.py tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog"` → 111 passed, 1 deselected; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_simulation_public_scenarios.py tests/test_simulation_spawn_workers.py` → 19 passed; `.\\.venv\\Scripts\\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Remaining: Full C-001–C-006 review checkpoint remains. The known QML layout assertion is unrelated to this authorization work and remains excluded: `test_machine_setup_hardware_page_scrolls_within_the_dialog` expects `Layout.fillHeight: true` in `MachineSetupDialog.qml`.
- Commit: uncommitted

## 2026-09-12 — C-003 — worker — codex-execution

- Result: implemented
- Summary: Added a small session-local guided completion policy. Public connect,
  reference, homing, manual work-zero, Auto XYZ, and confirmed touch-plate
  actions arm only their current rail step; the rail advances after the
  corresponding controller fact is observed. Deliberate step selection and Back
  cancel pending advancement, reconnect clears it, and Back keeps Run selected
  while a job is active. Existing explicit next-part behavior remains review and
  preflight gated with no automatic restart. Added public transition evidence
  for connect/reference/zero completion and active-run monitoring.
- Files: `src/ttc3018_control/qt/view_model.py`, `tests/test_ux2_batch_cd.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_workflow_projection.py tests/test_simulation_h6.py` → 60 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_ux2_batch_ab.py tests/test_qt_shell.py -k "guided or terminal_run or prepare_load or work_zero_requires or plate_removal or simulation_poll_projects_snapshot"` → 10 passed, 59 deselected; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_simulation_h6.py::test_ux2_public_viewmodel_loopback_guided_progression_and_cleanup` → 1 passed.
- Remaining: Full C-001–C-006 review checkpoint remains; known unrelated QML layout assertion is still documented in prior handoffs.
- Commit: uncommitted

## 2026-09-12 — C-005 — worker — codex-execution

- Result: implemented
- Summary: Extended the public digital-twin acceptance evidence with explicit seed/configuration, application transitions, captured loopback transport commands, expected/observed outcomes, and owned-process cleanup. Added public ViewModel-backed route coverage for manual reference/manual per-axis zero, partial-switch manual fallback, and three-switch homing. The existing completed Auto XYZ/job journey and collision interlock path now have reloadable evidence assertions. Made trace recording preserve source-order monotonic timestamps across backend, supervisor, and application queues so exported evidence can be reloaded deterministically.
- Files: `src/ttc3018_control/simulation/public_scenarios.py`, `src/ttc3018_control/simulation/runtime.py`, `src/ttc3018_control/application/controller.py`, `src/ttc3018_control/simulation/trace.py`, `tests/test_simulation_public_scenarios.py`, `tests/test_ux2_batch_ef.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_simulation_public_scenarios.py tests/test_ux2_batch_ef.py` → 6 passed; `$testFiles = @(Get-ChildItem tests -Filter 'test_simulation_*.py' | ForEach-Object { $_.FullName }); & .\.venv\Scripts\python.exe -m pytest -q $testFiles tests/test_ux2_batch_ef.py --maxfail=1` → 172 passed, 1 warning; representative offscreen shell command → 24 passed, 27 deselected.
- Remaining: C-006 targeted maintainability/documentation pass; the known unrelated QML layout assertion remains documented in earlier handoffs. Physical hardware, native app sessions, non-loopback endpoints, and C-007 architecture work were not accessed.
- Commit: uncommitted

## 2026-09-12 — C-004 — worker — codex-execution

- Result: implemented
- Summary: Kept capability/probe persistence atomic and visible to the editor,
  added true no-op detection so unchanged saves do not invalidate trust, and
  preserved existing axis/probe properties while applying capability drafts.
  Added public probe abort through hold/reset with explicit no-offset-change and
  retry guidance, exposed its active state to the ViewModel, and made the
  movable-Z card offer direct abort recovery. Tightened probe failure, no-contact,
  alarm, offset-mismatch, and cancellation messages with actionable recovery.
- Files: `src/ttc3018_control/application/controller.py`, `src/ttc3018_control/application/probing_service.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_ux2_batch_cd.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_ux2_batch_cd.py tests/test_z_touch_plate_controller.py tests/test_probing_service.py tests/test_application_contracts.py` → 60 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_machine_session.py tests/test_probing_service.py tests/test_z_touch_plate_controller.py tests/test_ux2_batch_cd.py tests/test_ux2_batch_ab.py tests/test_simulation_h5.py` → 44 passed.
- Remaining: Full C-001–C-006 review checkpoint remains; known unrelated QML layout assertion is still documented in prior handoffs.
- Commit: uncommitted

## 2026-09-12 — C-006 — worker — codex-execution

- Result: implemented
- Summary: Added a state-keyed cache for the shared guided workflow projection and its preflight result, including invalidation across machine/profile, connection/status, reference/WCO, job, safety, simulation, operation, and review facts. The state-publication callback now warms that same cache so repeated QML Review/Run and guided-rail reads do not rerun preflight. Updated README to describe the actual eight-step guided flow, shared typed projection, and intentional supported/simulation-only/declared-but-unavailable/hardware-commissioned capability boundary. Added a final batch evidence index while retaining dated audit reports unchanged.
- Files: `src/ttc3018_control/qt/view_model.py`, `README.md`, `docs/BATCH_EVIDENCE_INDEX.md`, `tests/test_ux2_batch_ef.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_ef.py::test_c6_workflow_and_review_projection_cache_until_facts_change -vv` → 1 passed; `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_ef.py tests/test_ux2_batch_cd.py tests/test_workflow_projection.py tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog" --maxfail=1` → 112 passed, 1 deselected; `$testFiles = @(Get-ChildItem tests -Filter 'test_simulation_*.py' | ForEach-Object { $_.FullName }); & .\.venv\Scripts\python.exe -m pytest -q $testFiles tests/test_ux2_batch_ef.py --maxfail=1` → 173 passed, 1 warning; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Remaining: Combined C-001–C-006 planning review/sign-off checkpoint. The known stale `test_machine_setup_hardware_page_scrolls_within_the_dialog` assertion remains excluded because it expects controls removed from the current read-only dialog. No native app, physical hardware, non-loopback endpoint, or C-007 work was accessed. Manual GUI relaunch is required to load source changes into an already-running app.
- Commit: uncommitted

## 2026-09-12 — C-007 — worker — codex-execution

- Result: implemented
- Summary: Reconciled the existing Qt-free backend, loopback protocol, process manager, CLI, Qt composition, ViewModel, Live bridge, README, and architecture contract. Added an authority/lifecycle matrix, complete direct-application call inventory, gap sequencing for C-008–C-013, and explicit ownership/authentication/reconnect/lease/orphan policy notes. Added static targeted gates proving production main composes through `BackendProcessManager`, the ViewModel does not send raw transport bytes, and the dispatcher remains finite and excludes raw transport operations.
- Files: `docs/BACKEND_FRONTEND_SEPARATION_AUDIT.md`, `tests/test_backend_separation_audit.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_separation_audit.py` → 4 passed; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Remaining: C-008 must close the typed snapshot/action/configuration boundary gaps identified by the matrix. No native app, physical hardware, serial/USB, non-loopback endpoint, or C-013 commissioning was accessed.
- Commit: uncommitted

## 2026-09-12 — C-008 — worker — codex-execution

- Result: implemented
- Summary: Completed the typed backend boundary with versioned snapshots, ordered events, capabilities, structured errors, optimistic revisions, idempotent commands, confirmation routing, bounded program projections, discovery/configuration/job/simulation/probing/touch/Auto XYZ action handlers, and a client-backed Qt adapter for the remaining configuration paths. Raw GRBL send/injection remains outside the finite action registry.
- Files: `src/ttc3018_control/backend/contracts.py`, `src/ttc3018_control/backend/protocol.py`, `src/ttc3018_control/backend/runtime.py`, `src/ttc3018_control/backend/dispatcher.py`, `src/ttc3018_control/backend/server.py`, `src/ttc3018_control/backend/client.py`, `src/ttc3018_control/backend/qt_adapter.py`, `src/ttc3018_control/backend/__init__.py`, `tests/test_backend_api.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_api.py --maxfail=1` → 6 passed; `.\\.venv\\Scripts\\python.exe -m compileall -q src/ttc3018_control/backend src/ttc3018_control/qt` → passed; combined backend/API smoke before the final configuration additions → 9 passed; `git diff --check` → passed. The final focused lifetime test invocation was interrupted by the continuation boundary before output and is not counted as passing evidence.
- Remaining: C-009 independent process lifetime is now claimed. Physical commissioning, non-loopback access, and interaction with any user-owned application remain outside scope.
- Commit: uncommitted

## 2026-09-12 — C-009 — worker — codex-execution

- Result: implemented
- Summary: Added an atomic root owner marker with exact-owner release, authenticated live-owner startup checks, conservative dead-PID discovery cleanup, and fail-closed incompatible-client handling. Added a non-mutating client heartbeat and kept frontend close/disconnect independent from runtime shutdown; active runtime shutdown remains rejected unless the explicit safe-abort option is supplied. Synchronized server startup/teardown so immediate stop cannot deadlock the HTTP serving thread.
- Files: `src/ttc3018_control/backend/discovery.py`, `src/ttc3018_control/backend/server.py`, `src/ttc3018_control/backend/client.py`, `src/ttc3018_control/backend/process.py`, `src/ttc3018_control/backend/__init__.py`, `tests/test_backend_lifetime.py`, `tests/test_backend.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_api.py --maxfail=1` → 6 passed after the lifetime changes; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_lifetime.py::test_dead_discovery_record_is_cleaned_before_startup --maxfail=1` → 1 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_lifetime.py::test_process_manager_surfaces_incompatible_owner_without_spawning --maxfail=1` → 1 passed; compileall and `git diff --check` passed. The live-owner test was also added; one invocation was interrupted by the harness during HTTP startup/teardown and is not counted as passing evidence.
- Remaining: C-012 must exercise the persistent process and frontend reconstruction end to end. No native app, physical hardware, or non-loopback endpoint was accessed.
- Commit: uncommitted

## 2026-09-12 — C-010 — worker — codex-execution

- Result: implemented
- Summary: Made the production Qt polling path backend snapshot/event driven, added retry/re-attach after backend loss with session-cursor reset, exposed honest backend availability/state/error properties, rendered backend availability in the QML header, and kept adapter close frontend-only. The explicit in-process `build_engine` seam remains available only for isolated development/tests.
- Files: `src/ttc3018_control/backend/qt_adapter.py`, `src/ttc3018_control/backend/client.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_backend_qt_adapter.py`, `tests/test_backend_separation_audit.py`, `docs/BACKEND_FRONTEND_SEPARATION_AUDIT.md`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py` → 7 passed; the combined adapter/audit/CLI check → 10 passed; `.\\.venv\\Scripts\\python.exe -m compileall -q src/ttc3018_control/backend src/ttc3018_control/qt/view_model.py` → passed.
- Remaining: C-012 integration evidence for frontend destruction/recreation and backend process crash/relaunch.
- Commit: uncommitted

## 2026-09-12 — C-011 — worker — codex-execution

- Result: implemented
- Summary: Replaced the minimal CLI with a documented, scriptable interface over the same backend actions used by the GUI. It supports typed status/capability/event/review inspection, guarded motion/connection/job/probe/spindle/simulation commands, configuration preview/diff then explicit apply, expected revisions, idempotency keys, explicit confirmations, and structured machine-readable failure responses.
- Files: `src/ttc3018_control/backend/cli.py`, `tests/test_backend_cli.py`, `README.md`, `docs/BACKEND_FRONTEND_SEPARATION_AUDIT.md`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_cli.py --maxfail=1` → 3 passed; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_separation_audit.py tests/test_backend_qt_adapter.py tests/test_backend_cli.py --maxfail=1` → 10 passed; compileall and `git diff --check` passed.
- Remaining: C-012 must prove the same contract across process crash, reconnect, duplicate requests, and active digital-twin work.
- Commit: uncommitted

## 2026-09-12 — C-012 — worker — codex-execution

- Result: implemented
- Summary: Added end-to-end separation evidence for an active digital-twin job surviving frontend adapter close and reconnecting with the same backend session, including observer abort recovery. Added a subprocess-backed backend-first/GUI-first lifecycle test covering explicit backend spawn, frontend drop, backend crash, retained stale discovery, explicit relaunch, new session identity, and no automatic job or connection state. Event cursor loss/ordering, duplicate idempotency, version rejection, stale discovery, and capability boundaries are covered by the contract suites. Added the recovery/migration/diagnostics runbook and updated the architecture decision record after observed software behavior.
- Files: `tests/test_backend_separation_e2e.py`, `tests/test_backend_api.py`, `src/ttc3018_control/backend/process.py`, `docs/BACKEND_RECOVERY.md`, `docs/ARCHITECTURE_DECISION_RECORD.md`, `README.md`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_separation_e2e.py::test_active_twin_job_survives_frontend_close_and_reconnect --maxfail=1` → 1 passed in 2.13s; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_separation_e2e.py::test_explicit_backend_relaunch_after_crash_has_new_session_and_no_auto_motion --maxfail=1` → 1 passed in 4.99s; `.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_backend_api.py tests/test_backend_separation_e2e.py --maxfail=1` → 9 passed in 6.72s; compileall and `git diff --check` passed.
- Remaining: C-013 requires separately authorized electrical design, physical safety hardware, bench evidence, and final machine acceptance. No native application, physical hardware, non-loopback endpoint, purchasing, wiring, or energization was accessed.
- Commit: uncommitted

## 2026-09-12 — C-013 — worker — codex-execution — blocked boundary

- Result: blocked
- Summary: Reached the explicit physical commissioning boundary. The queued requirement calls for an electrically independent maintained NC dual-channel E-stop, safety relay/contactor, isolated observation adapter, electrical review of the actual DLC32/spindle/driver topology, measured power removal, and bench/final-machine acceptance. Those actions cannot be safely inferred or performed from the software workspace and are excluded by the current run authorization.
- Files: `coordination/BACKLOG.md`, `coordination/STATUS.md`, `docs/ARCHITECTURE_DECISION_RECORD.md`, `docs/BACKEND_RECOVERY.md`
- Verification: software-only separation evidence is recorded in the preceding C-007–C-012 handoffs; no physical or native-app interaction occurred. The blocker is an authorization/equipment boundary, not an unaddressed software test failure.
- Remaining: Planning must separately authorize an electrical review and physical commissioning plan with machine-specific topology, parts, wiring, and measured safety evidence before C-013 can continue.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — worker — codex-execution — blocked physical remainder

- Result: software slice implemented; physical remainder blocked
- Summary: Added a Qt-free typed `SafetyInputAdapter` contract and deterministic
  `FakeSafetyInputAdapter` seam for two normally-closed channels. The backend
  `SafetyInputMonitor` publishes clear/active/latched/unknown/fault with raw
  channels, sample and observation timestamps, session identity, debounce and
  stale limits, adapter availability, and reasons. Active, disagreement,
  missing, stale, future-dated, and wrong-session feedback latch immediately;
  clear requires a settled dual-channel observation and explicit acknowledgement.
  Runtime trips perform best-effort hold/spindle-stop/jog/probe/job recovery,
  invalidate application safety trust, gate non-recovery actions, publish the
  same status through snapshots and CLI, append local transition audit records,
  and restore a prior latch across backend restart. No physical adapter,
  electrical topology, reset pin, GPIO, wiring, energization, or commissioning
  path was added.
- Files: `src/ttc3018_control/backend/safety_input.py`, `src/ttc3018_control/backend/runtime.py`, `src/ttc3018_control/backend/dispatcher.py`, `src/ttc3018_control/backend/cli.py`, `src/ttc3018_control/backend/__init__.py`, `src/ttc3018_control/application/controller.py`, `tests/test_backend_safety_input.py`, `tests/test_backend_cli.py`, `docs/SAFETY_INPUT_CONTRACT.md`, `README.md`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py tests/test_backend_lifetime.py -k "not backend_root_has_one_owner" --maxfail=1` → 30 passed, 1 deselected in 7.60s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_lifetime.py::test_backend_shutdown_requires_explicit_safe_abort_when_active --maxfail=1` → 1 passed in 0.62s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_cli.py tests/test_backend_api.py tests/test_backend_separation_audit.py --maxfail=1` → 21 passed in 1.23s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Failure note: one earlier combined lifetime invocation hit a transient Windows `PermissionError` removing the owner marker during teardown; the exact failing test passed on immediate isolated retry and the broader rerun passed.
- Remaining: C-013 still requires separate authorization for machine-specific electrical review, maintained NC dual-channel circuit, safety relay/contactor and isolated adapter selection, wiring, measured power-removal evidence, and bench/final-machine acceptance. No native app was interacted with; manual GUI relaunch remains required to load source changes.
- Commit: uncommitted

## 2026-09-20 — C-015 jog, positioning, and Home simplification

- Result: source implementation and focused verification complete; live backend reload pending explicit restart authorization.
- Summary: Replaced repeated 1 mm live-jog pulses and post-release whole-mm correction with one envelope-bounded GRBL jog and immediate, repeatable realtime cancel. Focus loss also stops an active jog. Reworked the UI into a clear hold-to-move pad plus separate 0.1/1 mm precision nudges. Disabled shared buttons and jog controls expose hover guidance. Machine-canvas clicks now select virtual-envelope XY, retain current virtual Z, show a target, and require confirmation before using the guarded safe-position planner. Added the missing typed backend `move-to` action and routed the restartable Qt adapter through it. The Home step now leads with Home and omits Go-to-reference/Retract controls while retaining jogs.
- Diagnosis evidence: live `logs/pine.log` reported `Position move blocked — Arbitrary target motion is not exposed by the backend contract`, identifying the persistent-adapter stub as the live blocker.
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_api.py tests/test_backend_qt_adapter.py tests/test_qt_shell.py tests/test_c015_workspace.py` → 72 passed in 19.24s. No backend or GUI process was restarted; no physical motion was sent.
- Files: `src/ttc3018_control/application/motion_service.py`, `src/ttc3018_control/backend/dispatcher.py`, `src/ttc3018_control/backend/qt_adapter.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_backend_api.py`, `tests/test_backend_qt_adapter.py`, `tests/test_qt_shell.py`, `tests/test_c015_workspace.py`, `coordination/STATUS.md`, `coordination/HANDOFFS.md`.
- Live verification: With explicit operator authorization, gracefully restarted backend PID 9000 as PID 22596, reconnected Wi-Fi `192.168.86.38:23`, confirmed fresh Idle/spindle 0/homing inputs safe/no hazards, homed successfully, then invoked guarded `move-to` at 200 mm/min from virtual `(0,0,40)` to `(1,0,40)`. Backend accepted the action and settled at fresh Idle virtual `(1,0,40)` with spindle 0 and no hazards.
- Remaining: the already-running GUI process still has the pre-change Python/QML modules loaded and must be closed/reopened by the operator or under separate explicit GUI-restart authorization before its canvas uses the verified backend route. A physical hold-jog UX test remains appropriate after that reload.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — verification correction

- Result: post-fix verification passed
- Summary: Corrected the controller-reset diagnostic event indentation and
  added the explicit source field to published safety-input status. The reset
  diagnostic records controller reset telemetry without inferring a physical
  E-stop, preserving the independent-input boundary.
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_separation_audit.py --maxfail=1` → 21 passed in 1.20s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_qt_adapter.py tests/test_backend_separation_e2e.py tests/test_backend_lifetime.py -k "not backend_root_has_one_owner" --maxfail=1` → 9 passed, 1 deselected in 5.35s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_application_contracts.py --maxfail=1` → 42 passed in 0.60s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_machine_session.py tests/test_probing_service.py tests/test_z_touch_plate_controller.py --maxfail=1` → 16 passed in 0.51s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_ab.py tests/test_ux2_batch_cd.py tests/test_ux2_batch_ef.py tests/test_workflow_projection.py tests/test_simulation_h6.py tests/test_simulation_public_scenarios.py tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog" --maxfail=1` → 134 passed, 1 deselected in 52.68s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed.
- Remaining: The physical C-013 boundary is unchanged. Planning review/sign-off is ready; no electrical or native-application action was taken.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — safety-boundary tightening

- Result: post-tightening verification passed
- Summary: Kept auxiliary-channel `clear` distinct from hazardous-power
  confirmation: `power_removal` remains `unknown` in the software-only
  adapter, so non-recovery actions remain blocked even after a settled clear
  and latch acknowledgement. Runtime acknowledgement now also requires a
  connected controller with a fresh GRBL `Idle` report and spindle off. Audit
  serialization remains tolerant of adapter scalar values, and controller
  reset telemetry is recorded without inferring an E-stop.
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_e2e.py --maxfail=1` → 20 passed in 7.13s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Remaining: Physical C-013 still requires separately authorized electrical design, wiring, measured power-removal evidence, and bench/final-machine acceptance. The planning handoff remains ready.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — GUI projection and readiness gate

- Result: software slice complete; physical remainder blocked
- Summary: Exposed the backend-owned `physical_estop` snapshot through the
  restartable Qt adapter and ViewModel, including state, raw channel status,
  reason, session, latch, commissioning, and hazardous-power evidence. Added a
  guided Safety panel with the same diagnostic text and acknowledgement route
  used by CLI. Published safety blocks now suppress GUI motion/return/live-jog
  and job-start readiness while preserving hold, abort, diagnostics, and
  physical-safety guidance. The adapter remains presentation-only and makes no
  local safety decision.
- Files: `src/ttc3018_control/backend/qt_adapter.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `src/ttc3018_control/backend/runtime.py`, `tests/test_backend_qt_adapter.py`, `tests/test_backend_separation_audit.py`, `tests/test_backend_safety_input.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog" --maxfail=1` → 76 passed, 1 deselected in 20.18s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed.
- Remaining: Physical C-013 still requires separate machine-specific electrical review, exact maintained NC dual-channel topology and parts, wiring, measured power-removal evidence, and bench/final-machine acceptance. No native app instance or hardware was interacted with.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — audit record alignment

- Result: documentation aligned
- Summary: Extended the backend/frontend separation audit with the C-013
  software boundary, shared `safety.physical_estop` projection, readiness gate,
  reset-correlation rule, and explicit physical commissioning exclusion.
- Files: `docs/BACKEND_FRONTEND_SEPARATION_AUDIT.md`, `coordination/HANDOFFS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_separation_audit.py --maxfail=1` → passed in the current focused audit suite; `git diff --check` → passed.
- Remaining: Physical C-013 remains blocked pending separately authorized electrical review and measured acceptance.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — client parity and trust-fingerprint audit

- Result: software slice complete; physical remainder blocked
- Summary: Added explicit BackendClient status/acknowledgement methods,
  thread-safe backend safety monitor access, audit recovery resilience for
  truncated trailing records, and controller-reset diagnostics that never infer
  a physical E-stop. Included physical safety state/power evidence in the
  ViewModel workflow/review cache and review fingerprint so a transition cannot
  leave stale operator acknowledgement. Added GUI review/run facts and kept
  the published readiness gate fail-closed while power-removal evidence is
  unknown.
- Files: `src/ttc3018_control/backend/client.py`, `src/ttc3018_control/backend/runtime.py`, `src/ttc3018_control/backend/safety_input.py`, `src/ttc3018_control/qt/view_model.py`, `src/ttc3018_control/qt/qml/Main.qml`, `tests/test_backend_api.py`, `tests/test_backend_separation_audit.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py --maxfail=1` → 27 passed in 5.92s; `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_ab.py tests/test_ux2_batch_cd.py tests/test_ux2_batch_ef.py tests/test_workflow_projection.py tests/test_simulation_h6.py tests/test_simulation_public_scenarios.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog" --maxfail=1` → 84 passed in 38.31s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.
- Remaining: Physical C-013 still requires separately authorized machine-specific electrical review, exact maintained NC dual-channel topology and parts, wiring, measured power-removal evidence, and bench/final-machine acceptance. Planning review is the next action.
- Commit: uncommitted

## 2026-09-12 — C-013 software slice — commissioned-without-adapter fail-closed repair

- Result: software slice complete; physical remainder blocked
- Summary: A runtime configured as commissioned without an adapter now treats
  that startup condition as immediate adapter failure, latches the safety state,
  records an audit entry, applies secondary stop/trust invalidation, and keeps
  readiness projections blocked. This closes the last identified software loss
  path without adding any physical I/O or commissioning claim.
- Files: `src/ttc3018_control/backend/runtime.py`, `tests/test_backend_safety_input.py`, `coordination/BACKLOG.md`, `coordination/STATUS.md`
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_lifetime.py -k "not backend_root_has_one_owner" --maxfail=1` → 19 passed, 1 deselected in 1.16s; `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed.
- Remaining: Physical C-013 still requires separately authorized machine-specific electrical review, exact maintained NC dual-channel topology and parts, wiring, measured power-removal evidence, and bench/final-machine acceptance. No native app or hardware was interacted with.
- Commit: uncommitted


## 2026-11-01 — C-016/C-017 ornament planning and offline CAM

- Owners: primary `codex-ornament-planning`; bounded audit, implementation and
  independent verification workers. Requested legacy luna model was unavailable;
  workers used the inherited available model. No overlapping file writers.
- C-016: audited actual code; reuse existing STEP profile/tab/verification engine
  and backend job authorization. Added `docs/ORNAMENT_CAM_PLAN.md` and queued
  C-018–C-023. Existing C-015 owner/work preserved. Planner sign-off: done.
- C-017: added `src/ttc3018_control/ornament_cam.py` and
  `tests/test_ornament_cam.py`. Explicit square crop/scale/Y flip, physical stock
  placement, V-bit radius erosion, fixed-depth passes, white-counter retention,
  quantized path footprint checks, parser/rapid validation, source hashes,
  omission report and swept-width SVG. Offline CLI exports engraving only;
  separate compensated profile reuse is planned, not reimplemented. No new
  dependencies, backend API or GUI changes. Planner sign-off: done.
- Independent review found and verified fixes for unrepresentable clearance,
  tiny-ratio overflow, excessive stock margin and rounded Z exceeding stepdown.
  Reviewer also checked a white counter with a larger footprint: zero gouge.
- Verification: `.\.venv\Scripts\python.exe -m pytest -q tests/test_ornament_cam.py
  tests/test_gcode.py tests/test_step_engraver.py` → 110 passed in 38.76s.
  Final independent exporter suite → 30 passed. Scoped compileall passed.
  `git diff --check` passed (existing line-ending warnings only).
- Real-artifact command: `.\.venv\Scripts\python.exe -m
  ttc3018_control.ornament_cam
  artifacts/ornaments/hawkeye/approved-artwork-reference.png
  artifacts/ornaments/hawkeye/illustrative-settings.json
  artifacts/ornaments/hawkeye/draft-review-v2` → exported successfully.
  Root reparsed exact output, checked rapid clearance/nonnegative XY, <=127-byte
  stream lines (actual max31), source hash, minZ=-0.25 and absence of M3/M6.
  Rendered SVG to PNG offscreen with QSvgRenderer/QImage (no GUI launched) and
  visually inspected it. `verification.json` records generator/output hashes.
- Important result: the real artwork is NOT production-ready. Assumed .10 mm
  tip/.25 mm depth gives .388675 mm effective width; 9.3409% black area is
  unreachable and eight components disappear. Many aircraft contours are lost.
  6,259 paths/pass, two passes, 101,384 commands, nominal estimate625.626min.
  Fixed-depth V raster floors are scalloped; mockup idealized flat floors.
  The report quantifies morphological accessibility, not full stock simulation.
- Next: C-018 project/verified inputs, C-019 geometry/narrow-detail/hanger reserve,
  C-020 common-XY profile bundle and verified stay-down optimization. Those are
  planned, not execution-authorized by this run. Hardware testing requires
  separate current-request permission and existing safety gates. No physical
  instance/backend/GUI was inspected or disturbed; no live configuration edited.


## 2026-11-01 — C-024 runtime correction after user rejection

- Owner: codex-ornament-optimization with independent verifier; primary owns
  integration and sign-off. Task done. Modified ornament_cam.py and its focused
  tests only; added benchmark configurations/comparison script and reports under
  artifacts/ornaments/hawkeye; updated planning/coordination docs.
- Root parsed baseline: 625.626min =91.812cut +498.764plunge +35.050rapid;
  12,518 plunges through the whole3 mm air gap. Never accept this as production.
- Added deterministic bounded component/endpoint scheduling, cost-aware
  stay-down links with retained original primitives and verified full quantized
  footprint, fallback when slower. optimize_paths defaults true; false preserves
  original ordering. Optional approach_z defaults null/full clearance. Explicit
  approach lowers vertically only after XY at safe_z, then feeds into stock.
  Invalid/above-safe/nonrepresentable approach rejected. All XY rapid still at3.
- Same source/tool width/depth/feed/two-pass comparison: scheduling only238.674min.
  Explicit hypothetical .2mm approach146.944min; projected single .25mm pass
 75.741min (changes max_stepdown from.125, untested). Times engraving only and
  omit acceleration/controller/toolchange/profile. .2mm approach requires
  independently verified stock flatness/clearance. Same9.34% inaccessibility;
  C-019/C-020 must prioritize vector/variable-depth and appropriate fill strategy.
- Independent synthetic A/B: zero white-region gouge, zero loss of original
  coverage, same depth/feed; verified every new link and separate approach/XY
  ordering. Final independent suite43 passed. Primary final command:
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_ornament_cam.py
  tests/test_gcode.py tests/test_step_engraver.py` ->123 passed in42.62s.
  Scoped compileall passed. Source hash frozen before/after final actual export:
  9070b60e4035b13b0e4b4742e3791ab4f6b36eb0214cfbdf678d8887e2b61544.
- Final export: python -m ttc3018_control.ornament_cam [approved source]
  [approach-illustrative-settings.json] [runtime-approach-v1] succeeded.
  compare_runtime.py reparses exact before/after programs and computes the
  single-pass scenario in memory only. Root validated exact final parse,
  safe rapid/nonnegativeXY, minZ-.25, <=127-byte lines and no M3/M6.
  runtime-approach-v1/verification.json records hashes and evidence.
- No machine/app/backend interaction. No live configuration or other task owner
  changes. C-024 checkpoint closed; production geometry/settings still unresolved.


## 2026-11-01 — C-025 USB bootstrap / C-026 Windows owner checks

- C025 implemented with primary safety integration and independent worker
  verification. Existing workers were reused; no further agents/models spawned.
  Production BackendRuntime enables controller/transport USB setup-only policy;
  injected isolated compositions retain compatibility semantics. USB queries
  read-only ESP111 and tries only controller-reported/saved IPv4 addresses.
  Same candidate TCP socket must provide recent Idle/feed0/spindle0 and matching
  finite USB MPos before adoption; closes USB only afterward. Failure keeps USB
  read-only. No provisioning credentials, controller resets or scans added.
- Controller gates operation/readiness, preflight/job, workzero and resume;
  transport allowlist blocks direct/multiline USB motion, spindle start and
  resume while preserving status/hold/M5/reset/jogcancel. Handoff invalidates
  reference/workzero, generation/status and run authorization, then persists
  Wi-Fi. Production auto-connect favors Wi-Fi even after USB setup. Snapshot
  exposes setup_only/operation_transport_ready/wifi_bootstrap. Docs in
  docs/WIFI_BOOTSTRAP.md and README. Test files use temporary roots/fakes.
- Independent fake integration checked same socket retained, USB closed once,
  generation advanced and reference/workzero/fresh status cleared; new status
  required before operation. Independent direct command checks confirmed motion
  rejection and emergency stopping retained.47 bootstrap +3 policy tests pass.
- Focused command: python -m pytest -q tests/test_wifi_bootstrap.py
  tests/test_wifi_operation_policy.py tests/test_application_contracts.py
  tests/test_tcp_connection.py tests/test_connection_settings.py
  tests/test_backend_api.py tests/test_backend_cli.py tests/test_c015_workspace.py
  ->120 passed in4.35s. Scoped compilation/whitespace passed.
- Full-suite first interrupted at owner-liveness test. C026 replaces Windows
  os.kill(pid,0) with query-only OpenProcess/GetExitCodeProcess/CloseHandle;
  access-denied/unknown fails closed to alive. New17 focused tests passed per
  worker. Also added missing validate_versions import in backend/server.py.
  Ownership/Windows/bootstrap/policy subset ->75 passed in5.45s.
- Full-suite final: python -m pytest -q ->795 passed,3 failed in219.64s.
  Failures: test_homing_nc_integration::test_loopback_nc_inputs_debounce_and_release_for_each_axis;
  test_simulation_h6::test_ux2_public_viewmodel_loopback_guided_progression_and_cleanup;
  test_ux2_batch_ef::test_e5_public_twin_reference_and_zero_routes[three-switch-enabled0-guarded homing].
  No clean-full-suite claim. Independent diagnosis requested; preserve the
  separately owned in-flight C015 workflow sources, do not rewrite expectations.
- Source checkpoint reached; C025 implemented, C026 planning sign-off done.
  No backend restart, GUI interaction, live config mutation or hardware access
  during this implementation. Current user-owned live backend retains old policy.
  Applying requires separate restart authorization per AGENTS.md. Restart must
  first verify backend-connected Idle/spindleoff/readiness and must not relaunch
  GUI or automatically move. No further eligible work at this boundary.

- Follow-up independent triage: same3 fail in isolation11.13s, all in direct
  ApplicationController legacy/simulation composition outside production C025.
  H6 expects locked navigation but current ViewModel allows free navigation;
  E5 expects Home step advancement without successful homing despite current
  prerequisite; NC integration has raw/logical simulated limit-polarity
  mismatch. These are separate in-flight homing/workflow issues. No related
  source/test expectations were rewritten to conceal them.


## 2026-11-01 — C-025 activation and authorized home

- User explicitly authorized backend restart and homing. Read-only backend
  snapshot first confirmed connected Wi-Fi, fresh Idle, spindle0, no active job
  or operation and clear configured homing gates. Guarded CLI shutdown accepted.
  BackendProcessManager spawned new headless backend without GUI interaction.
- New backend auto-connect adopted saved192.168.86.31:23; fresh GRBL Idle/spindle0,
  operation_transport_ready=true and can_home_machine=true confirmed. Guarded
  home --confirm accepted; final homing_state=complete, status_fresh=true,
  reference_trusted=true, Idle, spindle0; MPos X1 Y1 Z-1. New policy is active.
- No USB-to-Wi-Fi physical handoff exercised: direct saved Wi-Fi connected first.
  Prior795pass/3 unrelated simulation-workflow failures remain documented.


## 2026-11-01 — C027 probe result / C028 confirmations / C029 held-jog repair

- User requests: known Zpuck only; chose straight-up retract at SAME XY, dialog
  to remove puck/clip, explicit Continue to calculated workZ0. Also remove
  nuisance expired confirmations, fix held jog that stuck and required E-stop,
  place precision MOTION buttons inside rose. Primary prioritized jog safety.
- User explicitly required Luna extra-high workers. Earlier inherited Sol audit
  workers were interrupted; all further delegated work used gpt-6-luna xhigh
  (z_probe_ui, jog_deadman, confirm_cleanup). No furtherSol turns requested.
- C027 backend snapshot z_probe_completion, new touch-continue-to-surface action,
  guarded transaction binds session/reference/puck fingerprint/WCO/XY and finite
  coordinates. Result/removal dialog only after retractACK+fresh safeIdle at
  expectedZ. Continue requires freshIdle/spindle0/Pclear, no competingoperation,
  unchanged frame and valid envelope/direction, then one Z-only jog at slowfeed.
  Plate latch clears only on ACK plus later Idle at target. Legacy removal ack
  rejects active flow; fail/reset cancels context and invalidates workzero.
  Retract status timeout/fault truthfulfailure. No move to machinehome/XY.
  Updated docs/Z_TOUCH_PLATE.md and tests; no live probe performed.
- C028 helper meaningful_status_facts canonicalizes status excluding buffer/raw
  report fields; relevant pose/feed/spindle/input/state remain bound along with
  existingprogram/reference/WCO/safety facts. Replaced misleading expired text
  with concrete canceled/replaced/state-changed messages. Validate confirmation
  bool before consuming token. No arbitrary operator wait timeout added.
- C029 found reproducible stop-drop path: normal Qt invocation attached stale
  snapshotrevision and idempotency cache could reject/replay stop. Stops now
  bypass both; frontend stop/renew invoke ungated. Unique press token with100ms
  QTimer heartbeat, backend400ms lease. Max200ms feed-based segment; ACK AND a
  newer Idle report at expected endpoint required before next segment (not mere
  wallclock, since GRBLACK meansqueued). Backend checks fresh position/input
  trust eachpoll; lostrelease/focus/window/UI destroys renewal and realtime
  cancel; no auto-revival. Bounded segment remains if network cannot carry stop.
  Physical E-stop remains independent. Legacy no-token in-process path only;
  backenddispatcher requires token. InnerXY precision cross and Z steps between
  holdcontrols; shared .1/1selector above. No hitbox overlap at1180x720/1500x920.
- Independent Luna review found legacyackbypass and incomplete retractfailure
  feedback; root repaired both, reviewer acceptedread-only. Final focused
  command: python -m pytest -q tests/test_confirmation_stop_contract.py
  tests/test_jog_deadman.py tests/test_z_probe_completion.py
  tests/test_z_probe_result_ui.py tests/test_confirmation_facts.py
  tests/test_z_touch_plate_controller.py tests/test_backend_api.py
  tests/test_application_contracts.py ->98 passed in8.37s. Earlier101-focused
  set also included probing_service beforefinalpolltrust refinement.
  New UItests10passed; revised bounded livejog UIintegration7cases pass infull.
- Full regression python -m pytest -q ->838 passed,3 failed in228.32s:
  same NC/raw-logical polarity and two guided-workflow expectation failures
  documented under C025. No clean-full-suite claim. Final controller poll trust
  wrapper was narrowly checked after fullsuite collection via focused stale-
  status cancellation test. compileall and scoped diff-check passed.
- All three tasks implemented; stop at activation boundary. Backend/GUI not
  restarted or inspected, hardware not exercised and liveconfig untouched.
  Changes require separately authorized backend+GUI restart underAGENTS.md.
  Current instance still has old jog/probe UI; applying requires reference/
  workzero review before any user-authorized physical test. No automaticmotion.


## 2026-11-01 — C030 authorized app activation

- User requested app restart then single-bit slice. Connected saved Wi-Fi first
  because backend was disconnected. Verified fresh Idle, spindle0, no job or
  active operation and clear configured homing gates before restart.
- Identified exact project run.py pythonw GUI PID/creation/command. Stopped only
  the matching authorized GUI launcher; child exited. Guarded backend shutdown
  returned accepted. Started new headless backend with ProcessManager, then
  pythonw run.py with hidden console. New GUI launcher2248/child22024 has Pine
  MainWindow. New backend advertises touch-continue-to-surface/live-jog-renew.
- Fresh Wi-Fi192.168.86.31 Idle/spindle0 confirmed, reference_trusted=false and
  work_zero_confirmed=false. No homing/probe/jog/spindle/cut sent. Pending slice
  is offline review only with assumed3.175 cutter and nominal3mm stock.


## 2026-11-01 — C030 withdrawn; C031 restored two-tool files

- User explicitly withdrew the single-bit design and requested separate60degree
  V-bit detail and1/8endmill cutout/hole jobs. Stopped the single-bit worker and
  review; retained its draft with withdrawal README. App restart remains done.
  C030 planning-sign-off closed as withdrawn design assessment, not a released
  single-bit machining job.
- C027/C028/C029 source+activation checkpoint signed off done: scoped independent
  reviews and838pass fullsuite with known3 separate simulationfailures recorded;
  newbackend contracts+GUI active. This is not physical probe/jog acceptance.
- C031 claimed. Luna extra-high workers only. Endmillcutout leg generated with
  same110mmstock lower-left origin, partcenter55/55,100diameter/hole55/100D4.
  Root independently parsed02-cutout-review.nc:8.712563min,1482commands,
  seven.45mm depthlevels to-3.15; allholepathsfinishbeforeouterpaths; tabs
  retain.8 nominalwood and reentrysegments<=.5. NoM3/M4/M6, finalM2,
  nonnegativeXY and safeZ3rapid checks passed. Tool3.175/stock3.0/feed300/80
  remainunverifiedreview assumptions. No fileloaded orcut.

## C-031 — two-tool offline review checkpoint — 2026-11-01
Owner: codex-two-bit-slice. User restored 60 degree V-bit detail plus assumed 3.175 mm endmill hole/profile. Luna xhigh workers generated bounded artifacts; primary independently parsed both and visually inspected cutter-sweep previews. Outputs: artifacts/ornaments/hawkeye/two-bit/01-detail-review.nc and 02-cutout-review.nc, reports, scripts, README and independent-verification.json. Common 110 mm lower-left frame, 100 mm part centered 55,55. Detail min Z -0.45, 257628 commands, estimate182.6185min; profile minZ-3.15,1482commands,8.7126min. Checks: report hashes match, nonnegativeXY, XY rapids atZ3, noM3/M4/M6, finalM2; hole before profile, tabs and depth ladder verified. Detail sweep preserves99.0007% black area, preview reviewed. Files are review drafts with initial/finalM5 and no spindle startup; actual bit dimensions, stock, speeds and workholding remain unverified. Detail runtime remains impractical and needs vector/centerline optimization. Restart completed separately; no job loaded or machine motion performed. PreserveXY and reprobeZ between tools. C031 closed at offline artifact review checkpoint, not machining release.

## C-035 — agent instruction update
Added a preference for direct workflows, actionable block reasons, and proportionate machine checks to AGENTS.md. Existing user-owned instance boundaries retained. Verified by inspection.

## C-032 and C-033 — probe diagnosis and saved work zero
Read-only backend reports Wi-Fi, fresh Idle, spindle off, trusted reference and work zero, commissioned plate ready; recomputed workflow reports probe available. No motion or GUI interaction; original block reason remains unknown. C-033 exposes machine-scoped saved offset through backend snapshot, adapter, ViewModel and Work Zero panel; existing return planner uses saved fallback when current zero unconfirmed. Labels distinguish confirmed versus saved target. Worker reports four focused tests passed and three label/planner tests passed; independent snapshot test passed. No running instance restarted.

## C-034 — offline optimization checkpoint
Candidate isolated in two-bit/01-detail-review-optimized-candidate.nc and prepare-detail-optimized-candidate.py. Baseline restored SHA e76235fe07cf1ad71a51f930f90b3b4639799596041972a5200bafdce454d6eb. Candidate estimated 98.47min, passes parser and conservative containment; coverage and preview not verified, so not promoted. See OPTIMIZATION_CANDIDATE_STATUS.md for remaining work. No machine interaction.

## C-036 — Z probe datum and confirmation repair
Read-only event evidence: slow PRB -2.283, stopped MPos -2.311, G10 L20 Z19.37 produced WCO -21.681 vs contact-derived -21.653; safe retract was not sent and completion remained probing. Corrected datum using G10 L2 contact-derived offset, propagate status failures, remove redundant pre-probe modal, bind post-removal Continue to displayed transaction. Independent test: python -m pytest tests/test_grbl.py tests/test_controller_adapters.py tests/test_probing_service.py tests/test_z_touch_plate_controller.py tests/test_z_probe_completion.py tests/test_z_probe_result_ui.py tests/test_simulation_controller_branches.py tests/test_backend_separation_e2e.py tests/test_backend_api.py -q: 82 passed in 9.70s. Running instance not restarted, no motion; real-machine acceptance remains outstanding.

## C-037 — per-axis work-zero persistence
Saved machine-scoped WCO now tracks confirmed axes, merges separately confirmed X/Y/Z, restores matching axes from fresh reports, and preserves current Z when returning to an XY-only saved zero. Legacy records supported. Focused independent regression: 131 passed in 10.63s (test_machine_state, test_machine_records, test_work_zero_persistence, test_application_contracts, test_z_probe_completion, test_z_touch_plate_controller, test_backend, test_backend_qt_adapter, test_simulation_core, test_ux2_batch_cd). Running app not restarted or hardware moved. Backend disconnected and no saved record currently; last historical WCO X19.733 Y21.000, not verified as current.

## C-038 — actual engraving bit
User identified Two Trees solid carbide flat-bottom V-bit, 1/8 inch shank, 30 degree / 0.1. Marked two-bit README: prior 60 degree / 0.05 mm detail files and previews mismatch and require regeneration; assume 30 degree included angle and 0.1 mm flat diameter pending package/drawing confirmation. Endmill profile geometry unaffected. No toolpaths changed or hardware accessed.

## C-040/C-041 — stale status and Z probe availability
E-stop power interruption caused missing status; after release and X input clear, backend restarted and Pine left open, Wi-Fi fresh Idle. UI now marks stale/missing status and USB setup context. Z probe no longer requires X/Y or XYZ confirmation, button remains actionable with rejection reason; Z-only offset preserves X/Y. Independent focused probe tests 79 passed; stale UI/adapter 9 passed. User must home after restart; no agent motion. Full Qt shell: 57 pass, one existing guided navigation failure. Audit found generic primary action blockers and Home Alarm mismatch, assigned C-042.

## C-042 — actionable workflow guidance
Home projection now permits fresh Alarm where guarded Home permits it; inline guidance and disabled reasons added for Continue, Home, held jog, Move safely and Start. Worker focused projection and QML tests 54 passed; Qt shell excluding known guidedStep0 failure 59 passed, 1 deselected. Current Pine instance predates these source changes; not restarted to avoid interrupting operator. No hardware interaction.

## C-039 — 30-degree engraving review checkpoint
Isolated v4-shallow-fine draft: actual assumed included30 degree/0.1mm tip, parser/hash/clearance/containment passed and primary visually reviewed preview; 1.7065% black omitted, 189.197min estimate. v3 alternative 130.744min omits 3.236%. Both remain offline review only with M5 and no spindle start; user previously rejected impractical runtimes, further optimization and machining settings remain. Existing drafts untouched. No machine interaction.

## C-043/C-044/C-045 — job preparation checkpoint
C-043 optimized 30-degree/0.1 mm spindle-enabled single pass candidate, 122.818 minutes, 1.7065% area omitted, parser/geometry/preview verified; 0.45 mm broad depth untested. More conservative two-pass candidate ~177 min; user choice pending. C-045 measured 3.25 mm, through Z-3.40 with four tabs, separate M3 S1000 and G4 P2 candidate, 8.763 min; offline checks passed. C-044 offscreen UI tests reproduce popup correctly for connected state, exact live missing-popup cause unresolved; disconnected edge fixed in source, 25 tests pass; not loaded in live app. User confirms puck/clip removed but live backend still waiting-removal; no Continue/motion sent. 1000 RPM confirmed by user as prior successful setting. Job not loaded or started.

## Start-ready first engraving — 2026-11-01
User selected 30 degree/0.1 mm V-bit single 0.45 mm broad pass, confirmed prior 1000 RPM and physical setup/clearance. Backend loaded c043-runtime/v4-single-pass-1000rpm/01-detail-review-vbit30-1000rpm.nc (131958 commands), Wi-Fi fresh Idle, spindle0, reference/work zero confirmed, plate ready. User confirmed puck/clip removed; backend Continue invoked only after fresh exact current MPos Z equaled work offset, with revision and transaction guard; response confirmed already at Z0, no descent. Live preflight accepted transformed bounds, can_start_job true, job idle. Built-in preview unavailable for large job; external verified sweep preview supplied. 122.818 min estimated, 0.45mm single pass physically untested, spindle dwell2s assumed. No Start sent. Cutout separately generated for 3.25mm sheet; must change tool/reprobe Z before second job.

## C-046–C-048 — start rejection and GUI synchronization
User requested Start; backend rejected before sending motion because initial M5 is forbidden by streamer. Created 01-detail-stream-compatible.nc by removing only initial M5; SHA256 71ac0f9a064b09eaa4d715362eff1c6429e39635cff806a22caed3fa5fb95bc4, parser and streamer transformation passed, final M5/M2 retained, bounds/rapid clearance and estimate unchanged. GUI ViewModel did not project external backend job loads; source fix synchronizes job summary and preview. Spindle-off fresh status added as start prerequisite in source. Independent pytest 134 passed across test_ux2_batch_ab, test_workflow_projection, test_application_contracts, test_wifi_operation_policy, test_z_probe_result_ui. Running app/backend not restarted, source fixes not active; no motion occurred. Await restart authorization; after restart re-establish trusted reference, confirm work zero and reload streamer-compatible file before start. Large-job built-in preview still unavailable; use external sweep.

## C-049/C-050 — faster deep test ready, not started
Prior run failed at 143 acknowledgements after 3s controller silence, no GRBL error; user reports stopping/resetting, exact cause of initial silence uncertain. Reconnected Wi-Fi, homed, returned to saved XYZ, fresh Idle/spindle0. User requested 2x feeds, test to half of measured 3.25mm, acceptable detail loss, then explicitly do not start. Generated/loaded v5-inner-ply-1p625mm-1000rpm/01-detail-stream-compatible-inner-ply-1p625mm-600-160.nc; 600 cut/160 plunge, three passes -0.6,-1.2,-1.625; spindle1000; 71053 commands, 46.25min estimate. 30deg/0.1 tip sweep width .971mm. Independent parser, streamer, hash, bounds and live backend preflight passed; can_start_job true. Broad only 27.697% black omitted including much of aircraft; primary visually reviewed preview. Ply boundary and load/depth untested. Last job state still displays failed historical result although newly loaded program clears restart requirement. No start issued.

## C-051 — deep plus fine detail ready for review
User requested restoring omitted detail with additional pass, no start. v6-inner-ply-plus-fine-1000rpm/01-detail-stream-compatible-inner-ply-plus-fine-600-160.nc loaded in live backend after verification: 265578 commands, 94.36min estimate, 600/160 feed, M3 S1000, deep passes -0.6/-1.2/-1.625 and fine residual -0.04. Actual emitted sweep leaves 0.664% source black omitted; deep and fine containment, preview/hash/parser/streamer checks passed, primary visually inspected. Live Wi-Fi fresh Idle, spindle0, reference and zero trusted; preflight fits and can_start true. No start sent. In-app preview unavailable for >5000 commands; historical job failure remains visible until next start. Fine lines do not reach deep layer, interface and cutting settings untested.

## C-052–C-055 — slow-feed diagnosis and offline candidates
User stopped after 621 acknowledgements for slow motion. Captured 32 Run reports FS35–77 mm/min despite programmed F600; matched 152 moves median0.0718mm, planner Bf:0,1200 (full). Acceleration/short turns likely; throughput alone not established. 2x feed-only review candidate prepared but user subsequently requested moderate rate. 450/120 candidate retains geometry, 118.99 min idealized. Speed-optimized 450/120 candidate reduces broad XY vertices 19.72%, conservative containment passed, 6.1767 mm2 additional omission, 118.181min idealized; actual benefit unverified and not loaded. Worker fixed overwritten v6 report and reverified original hashes. Event-woken bounded backend draining implemented offline, 75 tests independently pass; not active in running instance, fake latency benefit does not establish physical speedup. Machine remains idle, original 600/160 job loaded and aborted, trusted zero retained. No motion/restart sent.

## C-056/C-057 — optimized engraving readiness
Independent audit caught radius-vs-diameter error in speed report; corrected generator sweep calls and path count. Full-diameter independent recomputation: v6 omitted 0.664224%, broad candidate 0.681815%, all cutter envelopes contained. C-057 then simplified fine XY 179945 to105457 (-41.39%); independent full-diameter check and dummy streamer verified exact candidate SHA fd0856cd72fcfa14fee45871f47fe5287b1a398442bc92f09937a5fbe1498995, 177698 commands, depths -0.6/-1.2/-1.625 and -0.04 fine, F450/F120, M3 S1000, M5/M2, 118.18min linear estimate. Actual speed unverified, no 2–3x guarantee. With prior user permission restart/home/return: verified fresh Idle/spindle0/safe, restarted Pine/backend, homed, returned to saved XYZ, loaded exact candidate. Live preflight passes, Wi-Fi fresh Idle, reference/XYZ trusted, plate ready, can_start true, job idle. No job start sent. In-app preview remains unavailable for large file; v6 external preview is representative within verified sweep difference. Previous cut remains on workpiece; physical setup user-controlled.

## C-058 — controller-efficient ornament repair
User aborted the C-057 run after 1121 acknowledgements because motion remained extremely slow and visibly jumpy. Guarded backend abort accepted; follow-up status was fresh Wi-Fi Idle, feed0, spindle0, job inactive/aborted. Offline audit found 158857 nonzero XY moves, median0.0718mm, 61.1% <=0.1mm and 78.8% of junctions >=90deg, confirming pixel stair-steps rather than nominal feed or Wi-Fi throughput as the main cause. New c058-controller-efficient candidate uses adaptive full-cutter-contained vector chords: 88676 moves (-44.18%), median0.1435mm, <=0.1mm moves97010->35045, and >=90deg junctions121605->75136. Opening boundary specifically5966->665 moves, <=0.1mm4231->156, >=90deg5684->138; old command1121 was still inside it while new finishes by673. Three deep levels -0.6/-1.2/-1.625, shallow -0.04 detail, F450/F120 and S1000 remain. Independent exact sweep check: no modeled artwork/keepout/stock violations; omission16.42645->23.60294mm2 (+7.17650). Final candidate SHA a9f17459b112c1324cb082b58471d2ca9174569aca59b04f71723fbaacee474d; parser/clearance checks and dummy 127-byte streamer sent+ACKed all107515 nonterminal commands, max line31. Sixty-six stationary same-coordinate G1 lines intentionally model isolated plunge-only dots and cause no XY motion. Candidate remains offline/not loaded; actual feed improvement requires a deliberate physical run. No restart, GUI interaction, load, home, zero move, spindle start, or new cutting command occurred.

## C-059/C-060 — agent workflow and app clarity
Added docs/AGENT_CNC_JOB_WORKFLOW.md and AGENTS.md pointer: reusable preparation/review prompts, artifact/hash conventions, emitted sweep and segment/junction analysis, and existing exporter command. Removed generic fictional toolpath canvas graphic and display a loaded-but-preview-unavailable notice; Review/Run label envelope checks accurately and Run labels nominal feed-based estimate. `.venv\Scripts\python.exe -m pytest tests\test_ux2_batch_ab.py tests\test_backend_qt_adapter.py -q`: 29 passed. Independent UX audit recommends future structured tool/stock/hash provenance, scalable large-job preview, measured-time estimates, and separating prior attempt state from current loaded job. Running instance untouched; new QML not activated.

## C-061–C-064 — implemented, integration ongoing
Large previews use cached bounded all-segment XY raster with explicit resolution limitation; a 265573-segment file rendered in 0.588s and 120521-byte payload. Loaded G-code raw bytes are hashed; only adjacent reports matching output SHA are displayed, with bounded header notes and clear separation from physical setup. New file load clears prior failure/progress only after successful parse. Backend job snapshots now carry timing; nominal overrun no longer says finishing. New offline `python -m ttc3018_control.job_analysis` reports hash/bounds/time limits/segment statistics. Integrated pytest large-preview, provenance, adapter, analyzer, backend, application contracts, UX2: 96 passed. Qt shell: 60 passed, one pre-existing guided rail checked assertion fails; C-065 assigned. No running instance or hardware interaction.

## C-061–C-068 — integration checkpoint closed
Fixed stale Qt rail and saved-zero fixtures; simulator logical switch control now maps through NC/NO polarity without changing physical input interpretation. Twin journeys now test current direct navigation and actual homing and exposed Review acknowledgement index mismatch, corrected to step 5. Run view separates elapsed, nominal remaining, controller-reported feed, accepted commands and motion draining. Full `.venv\Scripts\python.exe -m pytest -q`: 894 passed in 232.99s. No running app/backend interaction, restart or physical testing; activation requires a future authorized restart. Accurate observed ETA remains unproven; nominal estimate clearly labeled and actual feed exposed.

## C-069 — live trial, target-closeness not yet achieved
User requested improve actual feed, home, saved zero and start; fixture clear. Reconnected Wi-Fi, homed, returned confirmed XYZ. Offline C-069 F675/F120 file SHA f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b differs from C-058 only in 88742 XY feed words (450->675), otherwise identical executable geometry and controls, verified independently and with parser/streamer. Stronger 0.15mm broad simplification only reduced 2601 of 88676 moves and added 3.03mm2 omission, so not selected. Loaded and started F675, user-authorized. First 49 Run samples at Z-0.6 reported median173, range69–675, max675, vs earlier median170.5 at F450; planner Bf0. Improvement to median not proven. Live run active; offline alternatives being investigated. Do not conflate 89.85min feed-only estimate with actual runtime.

User then authorized abort/rehome/restart to improve arc smoothness. Aborted original F675 at706 ACK, confirmed Idle/spindle0. Full broad smoothing rejected (+53.28mm2 omission). First-boundary-only smoothed candidate SHA bef0b50e8b65cd1008854b701d500b508b5ae7334267454786f6aae31372b9a8 passes independently recomputed full cutter sweep, stock/keepout, geometry, parser and streamer; first path 665->463 segments, >=90deg turns138->54, whole-job omission +0.9124mm2 vs C-058; all other paths unchanged, F675/F120. Returned saved zero and started. Run failed at92 ACK due 3s controller silence; sampled feed 675 on some reports. Reconnected Wi-Fi: fresh Idle, spindle0, MPos0,0,0, reference untrusted, indicating controller reset or position lost. Unknown whether operator intentionally stopped/reset or unexpected reset; clarify before rehoming or retrying. No assumption of physical outcome or speed improvement.

## C-069 — unexpected stop recovery and retry — 2026-11-03
Owner: codex-primary. Operator confirmed the stop was not intentional. Read-only reconnect state: Wi-Fi fresh Idle, spindle command 0, released homing inputs, MPos 0,0,0, saved WCO 17.701/22.667/-33.244, and untrusted reference. This establishes lost position/reset state but not power versus transport cause. Guarded `home --confirm` completed with reference trusted; `return-work-zero --confirm` completed and fresh work position was exactly 0,0,0. Verified candidate SHA256 `bef0b50e8b65cd1008854b701d500b508b5ae7334267454786f6aae31372b9a8`; client load request timed out but backend has the expected path and reports can_start_job true. Preflight accepted. User-authorized start accepted. Retry active at 540 accepted commands, fresh Run/spindle command 1000/Z -0.6. First 16 unique status samples median feed 112 mm/min, range17–359; snapshots at commands347 and540 reported301 and124. Visual improvement does not establish a median close to F675. No abort or further motion sent after retry start.

## C-070 — durable job-recovery record — 2026-11-03
Owner: codex-primary. User authorized UI and agent recovery bookmarking without interrupting the active job. Added `backend/job_recovery.py`: atomic versioned JSON persistence of exact program SHA/path, machine ID, run ID, accepted/sent/total command counts, outcome/reason and review requirement. Active records are reclassified as interrupted after a backend restart; no record carries a position, WCO, authorization, or executable resume cursor. Runtime projects `job_recovery` into the additive backend snapshot and persists it independently of the UI; CLI `job-status` now includes it; backend adapter and Pine Run page show it as recovery review context. It explicitly states accepted commands are not proof of executed motion and requires normal homing/work-zero restoration before a restart is prepared. Tests: `pytest tests/test_backend.py` 13 passed; `pytest tests/test_backend.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py` 26 passed; `pytest tests/test_qt_shell.py` 61 passed; `pytest tests/test_application_contracts.py tests/test_backend_api.py` 53 passed. No controller/backend/GUI-process action, restart, or machine motion was sent.

## C-071 — live run visualization — 2026-11-03
Owner: codex-primary. User requested a current-layer path, live cutter position/progress, and estimated time without interrupting an active physical job. Runtime now extracts only non-rapid XY segments at the fresh observed work Z, caps the display to <=5000 selected segments, and publishes `program_detail.execution_layer`; the all-moves large-job raster remains unchanged and complete. Adapter/ViewModel expose a fresh-only numeric work-coordinate marker and exact program bounds. The shared Run canvas overlays current-layer vector green and observed cutter marker orange in job coordinates, including for raster-only large previews. UI labels accepted commands as accepted (not physical completion); time presentation now names planned feed-based duration, observed active time, and nominal plan-left, with explicit physical ETA unavailability. Tests: `pytest tests/test_backend.py tests/test_backend_qt_adapter.py tests/test_application_contracts.py -q` 66 passed; `pytest tests/test_qt_shell.py -q` 61 passed; `compileall` and `git diff --check` passed (only pre-existing working-tree CRLF warnings). No controller/backend/GUI-process action, restart, or machine motion was sent.

## C-074 — live-plot transform correction — 2026-11-03
Owner: codex-primary. Corrected the raster-overlay coordinate conversion: the execution overlay is canvas-local while the base image is parent-relative, so its painted rectangle now subtracts the canvas origin once before applying the backend-published image bounds/padding transform. This removes the fixed canvas-margin offset that misaligned the live cutter/current-layer overlay. Source only; no live process or machine interaction.

## C-075 — CAM path-order release metrics — 2026-11-03
Owner: codex-cam-order-metrics. Extended reusable offline G-code analysis with true XY cut distance, rapid XY/Z/3D distance, feed/plunge distance, retract count, short-segment percentiles, and junction counts. Ornament reports now include those metrics, scheduled primitive/reversal/stay-down link counts and lengths, plus source/settings/output hashes; planned metrics are checked against the exact parsed emitted file. Existing bounded scheduler retains all original paths, reverses where useful, and inserts stay-down links only when the full cutter envelope remains inside the compensated artwork and the nominal link cost beats retract/rapid/plunge. `pytest tests/test_job_analysis.py tests/test_ornament_cam.py -q`: 44 passed. In the deterministic two-component fixture, 210 paths/pass became 2 chains/pass with 208 verified links and 68 reversed primitives; retract cycles 420→4, rapid XY 1422.7863→205.5339 mm, rapid Z 1357.5→15.9 mm, nominal time 33.0796→15.8249 min. Added cut distance was 110.4945 mm (links), while computed inaccessible artwork area stayed equal; exact swept-area test confirms no baseline cutter coverage loss and candidate sweep stays in black artwork. This is a test fixture, not a released Hawkeye job. No hardware, backend, or GUI interaction.

## C-072 — bounded controller-loss recovery — 2026-11-03
Owner: codex-recovery-state-machine. Backend watchdog now enters a bounded recovery state machine: it disconnects the silent session, retries only the configured saved Wi-Fi endpoint up to three times, requests M5 after reconnect, waits for its acknowledgement, then requests status and requires a fresh Idle report at exactly 0 RPM. Backend snapshot publishes recovery state and explicit action availability. Dispatcher and CLI expose `continue-to-home` (CLI requires `--confirm`) and `cancel-recovery`; continue rechecks current fresh Idle/0 and calls the existing guarded home path only after explicit invocation. Digital-twin watchdogs do not reconnect to physical Wi-Fi. Tests: `.venv\Scripts\python.exe -m pytest tests/test_backend_watchdog_recovery.py tests/test_backend_cli.py tests/test_backend_api.py tests/test_application_contracts.py -q` — 64 passed. `.venv\Scripts\python.exe -m compileall -q src/ttc3018_control/backend/watchdog_recovery.py src/ttc3018_control/backend/runtime.py src/ttc3018_control/backend/dispatcher.py src/ttc3018_control/backend/cli.py src/ttc3018_control/application/controller.py` — passed. `git diff --check -- src/ttc3018_control/application/controller.py src/ttc3018_control/backend/runtime.py src/ttc3018_control/backend/dispatcher.py src/ttc3018_control/backend/cli.py tests/test_backend_cli.py` — passed. Unrelated QML composition test still fails at `src/ttc3018_control/qt/qml/Main.qml:1977:38` with `Unexpected token ';'` in an in-flight pause-bookmark Label binding; exact source reported to root, left untouched. No live backend, GUI, or hardware interaction.

## C-076 — reset-aware automatic guarded homing — 2026-11-03
Owner: codex-reset-auto-home, delegated by the primary agent. Runtime now uses the positive reset result from GRBL response handling (banner or `[MSG:Reset]`) to start the existing exact saved-Wi-Fi recovery with automatic-home intent. It disconnects/reconnects, requests M5, waits for acknowledgement and a fresh Idle/0-RPM report, then calls the existing guarded `home_machine()` path automatically. A watchdog silence start leaves automatic-home disabled, so Continue-to-home/Cancel remain available. Tests: `.venv\Scripts\python.exe -m pytest tests/test_backend_watchdog_recovery.py tests/test_backend_cli.py tests/test_backend_api.py tests/test_application_contracts.py -q` — 66 passed in 3.89s; `.venv\Scripts\python.exe -m pytest tests/test_backend_watchdog_recovery.py -q` — 7 passed in 1.61s. `.venv\Scripts\python.exe -m compileall -q src/ttc3018_control/backend/watchdog_recovery.py src/ttc3018_control/backend/runtime.py tests/test_backend_watchdog_recovery.py` — passed. No Main.qml edits, live backend/GUI interaction, restart, controller access, or machine motion.

## C-073 — confirmed pause bookmark — 2026-11-03
Owner: codex-pause-bookmark. JobService now distinguishes the local paused label from controller confirmation: a Hold/Hold:0 status must arrive after the current pause request. Backend persistence additionally requires a fresh current-session status and records exact program SHA/path, machine/run identity, accepted/sent/total counts, the matching provenance report/tool detail, active tool-length offset, controller state, and diagnostic position context explicitly marked as not a resume cursor. The fixed recovery fence disallows automatic/direct recovery resume, rejects accepted-command counts as physical position, requires matching machine/run/program identity and a fresh Hold, and calls for operator review, homing/work-zero re-confirmation after disconnect/restart, and installed-tool verification. Restart preserves the confirmed pause only as historical evidence, clears live-Hold status, and marks the restart fence. Run UI shows current versus historical Hold confirmation and the matched tool context. Verification: `.venv\Scripts\python.exe -m pytest tests/test_application_contracts.py tests/test_backend.py tests/test_backend_qt_adapter.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_qt_shell.py` — 145 passed in 64.34s. No live backend, GUI, controller, or machine interaction.

## C-077/C-078 — precise plot mapping and full-profile restart — 2026-11-03
Owner: codex-primary. Corrected `ToolpathCanvas` so the active-layer overlay and cutter marker first use the actual centered `Image.PreserveAspectFit` painted rectangle, then recreate the backend rasterizer's exact 12 px padded/letterboxed program rectangle before converting work coordinates. This fixes both the fixed centering error and the bounds-aspect-ratio error. Added source assertions to `tests/test_large_job_preview.py`; `.venv\Scripts\python.exe -m pytest tests/test_large_job_preview.py -q` passed (4 passed, 1.87s). The authorized Pine GUI was cleanly reloaded.

For the requested fresh restart, validated `artifacts/ornaments/hawkeye/two-bit/c069-flow/01-detail-c069-flow-675-120-review-only.nc`: SHA256 `f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b`, bounds X0–98.9343/Y0–98.1448/Z−1.625–3.0, 107517 commands, and same saved 100 mm work frame/tooling as the prior engraving. The controller's reset recovery completed guarded homing; fresh state was Idle, spindle0, released limits, trusted reference and persisted XYZ zero. It returned to exact work (0,0,0), preflight passed, then user-authorized start accepted. Fresh check reported Wi-Fi connected, `Run`, 1000 RPM, active cutting layer and 46 accepted commands. No further controller action after start.

## C-079 — pause revision race — 2026-11-04
Owner: codex-pause-revision. Active job snapshots change their semantic revision as telemetry/progress advances; `QtBackendAdapter._invoke_result` attaches that revision to `pause-job`, so a telemetry update between render and click caused the dispatcher to reject a stop request before JobService could issue Hold. Dispatcher now treats `pause-job` as urgent stop intent (clears optimistic revision and idempotency replay metadata) and allows it through the independent motion safety gate so pause remains available as recovery. JobService still applies the actual pause behavior/state. Added regression test invoking Pause twice with an intentionally stale revision and reused idempotency key; each request reaches JobService. Verification: `.venv\Scripts\python.exe -m pytest tests\test_confirmation_stop_contract.py -q` — 5 passed in 0.97s. Source-only; active backend, Pine GUI and machine were not touched. Changes require a later backend activation.

## C-081 — persistent watchdog recovery — 2026-11-04
Owner: codex-watchdog-autorecover. On controller silence the existing job failure path sends realtime feed-hold and soft-reset immediately, clearing queued motion and requesting spindle shutdown. Recovery now retries the saved Wi-Fi endpoint up to 8 times and requests M5 after each connection. If M5 acknowledgement or fresh Idle/0-RPM confirmation is lost, it disconnects and retries rather than stopping at the first transient failure. Runtime enables automatic guarded homing for a stream watchdog only after fresh post-M5 Idle/0 RPM. This does not resume or restart interrupted G-code automatically. Verification: `.venv\Scripts\python.exe -m pytest tests\test_backend_watchdog_recovery.py -q` — 8 passed; `git diff --check -- src/ttc3018_control/backend/watchdog_recovery.py src/ttc3018_control/backend/runtime.py tests/test_backend_watchdog_recovery.py coordination/BACKLOG.md coordination/STATUS.md coordination/HANDOFFS.md` — passed. Source only; no app/backend/controller interaction or restart.

## C-080 — Run plot layer visibility — 2026-11-04
Owner: codex-layer-visibility. Added a compact Run-page “Plot layers” group with independent checkboxes for current cutting layer, cutting paths, and rapid move paths. `ToolpathCanvas` now applies the layer choices to its live vector overlay and static paths. Small jobs expose categorized cutting/rapid vector strokes from parsed segments; large jobs keep the existing all-moves raster for other preview contexts and additionally publish aligned transparent cutting-only and rapid-only rasters. The three raster assets share a 450 KB raw PNG budget so the base64 snapshot remains below the backend response cap. Updated labels/legend to describe which display is active. Verification: `.venv\Scripts\python.exe -m pytest tests\test_large_job_preview.py -q` — 6 passed in 2.69s; `.venv\Scripts\python.exe -m pytest tests\test_large_job_preview.py tests\test_qt_shell.py::test_qt_shell_loads tests\test_qt_shell.py::test_real_qml_shell_constrained_size_and_guided_transitions_offscreen -q` — 7 passed in 5.00s. No Pine GUI/backend/controller interaction or restart; the currently running job was left undisturbed. UI changes activate at the next authorized Pine reload.

C-080 follow-up verification: after adding the small-vector category case, reran `.venv\Scripts\python.exe -m pytest tests\test_large_job_preview.py tests\test_qt_shell.py::test_qt_shell_loads tests\test_qt_shell.py::test_real_qml_shell_constrained_size_and_guided_transitions_offscreen -q` — 8 passed in 3.81s.
## C-082 — bounded status response decode — 2026-11-04
Owner: codex-status-payload. Status snapshots with categorized raster previews could exceed 256 KiB but were still inside the protocol's 1 MiB response limit. The client used `decode_message()`'s request-sized default when decoding responses, then marked the backend unavailable on a valid large snapshot. Updated `BackendClient` to use `MAX_RESPONSE_BYTES` for success and structured HTTP error decoding, with a regression test returning a snapshot payload just over `MAX_REQUEST_BYTES`. Verification: `.venv\Scripts\python.exe -m pytest tests\test_backend_api.py -q` — 11 passed in 1.42s; scoped `git diff --check` passed. No Pine GUI/backend process/controller interaction or restart.

## C-083 — safe continuation after command 4000 — 2026-11-04
Owner: codex-safe-continuation. Added `artifacts/ornaments/hawkeye/two-bit/c083-recovery-at-4000/prepare-c083-continuation.py`, a deterministic offline generator pinned to the verified C-069 source SHA `f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b`. The first complete stroke boundary after executable command 4000 is command 4063: `G0 Z3.0000`, XY rapid, `G0 Z0.2000`, and plunge `G1 Z-0.6000 F120.0000`; it omits commands 1–4062 so the path containing command 4000 is completed before the next retract. Candidate SHA `0006af35317b3c4ec700a7cee4ef452bc0cd6ac171675e1ab59367ffbc045b9a`, 103459 executable commands. The generator verifies the exact original executable suffix, fresh G21/G17/G90/G94/G54 setup, first-move pattern, original 100 mm ornament/110 mm stock work frame, preserved depths and feeds, nonnegative XY, rapid XY at safe Z, one M3, final M5/M2, no M6, and parser success. Parsed bounds X0–98.9343/Y0–98.1448/Z−1.625–3.0; nominal duration 83.03 minutes. Bundle includes JSON hash/report and a 110 mm SVG centerline preview. Run `.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c083-recovery-at-4000\prepare-c083-continuation.py` to regenerate and repeat checks. Candidate remains offline review-only; command-count progress does not prove physical path completion. No controller, backend, or GUI interaction.

## C-085 — controller-throughput and time-estimate diagnosis
Owner: codex-runtime-diagnostics. Offline analysis of exact C-083 continuation SHA `0006af35317b3c4ec700a7cee4ef452bc0cd6ac171675e1ab59367ffbc045b9a`, using `.venv\Scripts\python.exe -m ttc3018_control.job_analysis artifacts\ornaments\hawkeye\two-bit\c083-recovery-at-4000\01-detail-c083-continuation-after-4000-review-only.nc`, found 103,459 commands, 85,089 nonzero XY cut blocks, 13,727 rapid blocks, 30,311 mm XY cutting, 2,186 mm plunge-feed, 31,803 mm rapid XY, 27,809 mm rapid Z, and 4,575 retracts. Median cut block 0.1435 mm; 34,862 (41.0%) <=0.1 mm; 72,718/80,577 (90.2%) cut junctions turn >=90°. The 83.03-minute parser estimate assumes all rapids at 3000 mm/min and excludes acceleration/junction slowdown. Prefix comparison against prior observed run snapshots: accepted command 3310 (3.20%) models 6.16 min vs 31.4 observed; 7626 (7.37%) models 14.18 min vs 68.8 observed, ~5.10x/~4.85x. Accepted count is not physical position, but the command window is too small to explain the discrepancy. Pine `JobStreamer` is already acknowledgement-driven character-counting with bounded buffer fill; historical C-052 records report `Bf:0,1200` while measured FS was 35–77 mm/min at F600, indicating full planner while cutting slowly. C-069 F675 samples median173 (range69–675), vs earlier F450 median170.5; first-boundary C-069 retry median112 despite F675. Evidence supports CAM as the dominant lever: reduce raster-derived blocks, sharp corners, and Z retracts. Increasing F alone will not plausibly meet 45 minutes. Actual `$11` junction deviation, `$120` acceleration, and `$110` axis max rates are not known; do not recommend changing them blindly. Official GRBL references: interface streaming documentation explains 127-character serial RX and 16 motion-block lookahead, and the performance problem of send-response with sequential tiny blocks (https://github.com/gnea/grbl/blob/master/doc/markdown/interface.md#streaming-protocols); settings documentation describes junction deviation (https://github.com/gnea/grbl/blob/master/doc/markdown/settings.md#11---junction-deviation-mm). No Pine GUI/backend/controller/hardware interaction or test execution.

## C-086 — performance-aware CAM workflow and runtime gate — 2026-11-04
Owner: /root/performance_workflow. `job_analysis` now reports short cut segments as percentages, sharp junction percentages, and retract density per 1000 commands, alongside existing absolute motion metrics. Added `performance_budget.assess_runtime_budget`: optional target-time assessment is profile-keyed, ignores partial runs, requires at least three completed comparable physical runs, and projects candidate nominal time using the largest observed actual/nominal ratio. The output distinguishes `needs_calibration`, `profile_mismatch`, `insufficient_calibration`, `over_target`, and `within_target`; it never authorizes physical execution. CLI supports `--target-minutes`, `--machine-profile-key`, and optional `--calibration-json`. Updated `docs/AGENT_CNC_JOB_WORKFLOW.md` with planner-aware CAM review, calibration schema and use, target gate invocation, and limits. Verification: `.venv\Scripts\python.exe -m pytest tests\test_job_analysis.py -q` — 3 passed in 0.59s; `git diff --check -- src\ttc3018_control\job_analysis.py src\ttc3018_control\performance_budget.py tests\test_job_analysis.py docs\AGENT_CNC_JOB_WORKFLOW.md coordination\BACKLOG.md coordination\STATUS.md coordination\HANDOFFS.md` — passed. Offline only; no Pine, backend, controller, or hardware action.

## C-086 correction — informational estimates only — 2026-11-04
Per user's explicit direction, removed all target-gate/pass/block semantics. Public helper is now `estimate_runtime_with_calibration`; analyzer adds `runtime_estimate`, which may report `nominal_only`, `provisional_projection`, `calibrated_projection`, or `profile_mismatch`. It estimates with the largest observed completed-run actual/nominal ratio, records run IDs and source G-code SHA-256 hashes, and labels one/two runs provisional versus three-plus established. An optional target comparison only emits a warning string; it does not authorize or block any operation. Updated workflow instructions accordingly. Reverification: `.venv\Scripts\python.exe -m pytest tests\test_job_analysis.py -q` — 3 passed in 0.96s; scoped `git diff --check` passed. Offline only.

## C-084 — linked broad-pass Hawkeye candidates — 2026-11-04
Owner: `/root/runtime_cam`. Generated offline review-only candidates from C-069 source SHA `f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b` in `artifacts/ornaments/hawkeye/two-bit/c084-runtime-45m/`. Both keep the 100 mm ornament frame, 110 mm stock coordinates, 30° 0.1 mm V-bit, S1000, F675/F120, and depth passes −0.6/−1.2/−1.625 mm. The fine residual stage is intentionally omitted and the coverage cost is quantified.

The linker schedules 349 simplified broad primitives into 101 chains per pass with 248 stay-down connectors per pass (744 total). Each connector is checked with a conservative full-diameter cutter buffer at final depth; each complete rounded chain is swept again. Economic cap is 14.458 mm and longest accepted connector 11.293 mm. Candidate 0.08 mm SHA `60d6405c0fc7556f90807fd00932a95ef7c4ff64113464efcb6f18581bee0718`: 19,744 commands, 33.06 nominal minutes, 303 retracts, 18,459 parsed XY cut segments, median 0.798 mm, 12,480 junctions >=90°, 4,086 mm rapid distance, 697.48 mm² (28.95%) uncut artwork, and 0.96 mm² sweep difference from C-069 broad. Candidate 0.50 mm SHA `c409a7b0c0ad4bfb4536be95fa80d12dea443a0b639731c9f8b3560f5fc30466`: 11,404 commands, 29.41 nominal minutes, 303 retracts, 10,119 parsed XY cut segments, median 1.212 mm, 6,873 junctions >=90°, 4,086 mm rapid distance, 748.99 mm² (31.09%) uncut artwork, and 71.85 mm² difference from C-069 broad. Both modeled full-depth cutter diameter 0.9708 mm and remain inside stock/artwork bounds.

Historical accepted-command pace of 105.4–110.8/min gives contextual projections of 178–187 min and 103–108 min. This is not a completed-run calibration or proof of physical position. The shared `job_analysis.analyze_program` supplies exact parsed motion/junction/retract metrics; `estimate_runtime_with_calibration` returns nominal-only because no completed comparable run exists. The 45-minute goal is aspirational, not a release blocker. Exact generator, settings, report, hashes, and physical-scale SVG previews are bundled in `c084-runtime-45m/README.md`. Verification: `.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c084-runtime-45m\prepare-c084-broad-only.py` regenerated and parsed both exact outputs; it checked nonnegative XY, rapid XY safe Z, unchanged depth passes, identical geometry at each depth, bounds, and full cutter-sweep containment. `.venv\Scripts\python.exe -m ttc3018_control.job_analysis` on both exact candidates matched report hashes and motion metrics. `.venv\Scripts\python.exe -m py_compile artifacts\ornaments\hawkeye\two-bit\c084-runtime-45m\prepare-c084-broad-only.py` and `git diff --check` passed. No GUI/backend/controller/hardware interaction. C-084 marked implemented for planning review.

## C-087 — hybrid endmill/V-bit feasibility — 2026-11-04
Owner: codex-hybrid-pocket. Evaluated a round-endmill broad pocket stage against the unchanged 1254×1254 source mapped to the shared 90 mm canvas in a 110 mm stock / 100 mm part frame, with the existing 3 mm hanger keepout. The assumed 3.175 mm endmill needs a conservative 1.588178 mm radius inset; the inset is empty, so no contained broad pocket paths exist and no endmill NC was emitted. At smaller tool diameters, center-accessible area is only 25.5825 mm² (1.062% of 2409.2226 mm²) for 2 mm, so it would be a different tool and still not a broad-pocket solution. The exact C-069 comparison file was parsed with `.venv\Scripts\python.exe -m ttc3018_control.job_analysis artifacts\ornaments\hawkeye\two-bit\c069-flow\01-detail-c069-flow-675-120-review-only.nc`: SHA `f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b`, 107,517 commands, 89.85196 nominal minutes, bounds X0–98.9343/Y0–98.1448/Z−1.625–3.0. Existing C-069 report/verification binds the exact-file full-diameter sweep, hanger exclusion, and 23.6029 mm² omission. Generalizable full-sweep multi-tool decision rule and limitations are in `artifacts/ornaments/hawkeye/two-bit/c087-hybrid-pocket/README.md`; machine-readable evidence is in `c087-hybrid-pocket-report.json` and `c087-hybrid-pocket-verification.json`. The 45-minute goal is aspirational; no fidelity loss was forced to chase it. No Pine/backend/controller/hardware interaction or physical readiness claim.

## C-089 — localized adaptive region comparison — 2026-11-04
Owner: codex-primary. Added reusable `plan_adaptive_region_engraving` in `ornament_cam.py`: it completes compensated regions in nearest-next order, uses bounded concentric inward offsets (maximum 32 rings per component), and falls back to local boundary-plus-scanline clearing when offsets are not suitable. It schedules and links only within each component, preserving the no-interleaving invariant, and checks every rounded final-depth cutter sweep against approved artwork. A Hawkeye C-089 review bundle was generated at `artifacts/ornaments/hawkeye/two-bit/c089-adaptive-regions/`. Exact G-code SHA `31c2773cf30017b15b62a66a2c54cffe5944c644823d37d2b8702210218f9f1a`: 7,669 commands versus 19,744 for C-084 0.08; 13.62 versus 33.06 nominal feed-based minutes; 5,993.8 versus 19,085.0 mm cut travel; 1,725.9 versus 1,979.7 mm rapid XY; 23.4% versus 68.9% >=90° cut junctions. Its broad-only omission is 768.23 mm² versus 697.48 mm², so it is a performance candidate rather than a fidelity-equivalent production substitute. The report binds source/baseline/output/preview hashes and parses the exact output, validates nonnegative XY, safe-Z XY rapids, unchanged three broad depths and full cutter-sweep containment. Verification: `.venv\Scripts\python.exe -m pytest tests\test_ornament_cam.py tests\test_job_analysis.py -q` — 47 passed in 4.65s; `py_compile` passed for the reusable module and generator; exact `job_analysis` completed; `git diff --check` had no content errors (only pre-existing CRLF advisory warnings). No Pine GUI/backend/controller/hardware action; active job untouched.

## C-090 — full-fidelity fine-residual completion — 2026-11-04
Owner: codex-primary. User correctly identified that broad-only work cannot be the final design. Generated `artifacts/ornaments/hawkeye/two-bit/c090-full-fidelity-completion/02-detail-c090-fine-residual-completion-review-only.nc`, SHA `fabf3a2dfb077c9c8c58cc914a34a20c3c7859176f5dd6ca0adbc73093a83a99`, as the aligned Z−0.0400-only companion to exact C-084 0.08 broad SHA `60d6405c0fc7556f90807fd00932a95ef7c4ff64113464efcb6f18581bee0718`. The completion has 85,494 commands and 46.26 nominal feed-based minutes; it does not repeat broad cuts. Parsed output validates nonnegative XY, safe-Z rapid XY and fine-only depth. A recomputed combined C-084 broad + C-090 fine full-diameter sweep remains inside approved artwork/hanger keepout and leaves 23.7389 mm² (0.9853%) unreachable by this tool/depth assignment, versus the intentional ~29% broad-only loss. Verification: generator ran successfully, `py_compile` passed, and `.venv\Scripts\python.exe -m pytest tests\test_ornament_cam.py tests\test_job_analysis.py -q` — 47 passed in 4.84s. No Pine GUI/backend/controller/hardware action; active job untouched.

## C-091 — approved raised-plane full-detail CAM — 2026-11-04
Owner: /root/approved_design_geometry. Converted the actual approved generated concept using luminance130 into a dark relief mask (visually inspected), with no hand-authored aircraft polygons. Shared 110mm stock frame/100mm disc and hanger reserve retained, concept mapped to99mm padded square; prior test-stock cuts cannot be cosmetically restored. Full sequence includes concentric localized broad clearing at -.6/-1.2/-1.625 and fine residual at-.04 using 30deg/.1mm V-bit S1000 F675/F120. Guarded vector chords reduced first candidate176266 commands to77893, nominal67.28min; no physical ETA claim. Final SHA2cba53849eeb5e7b255fdeb1d7fd332c71205d2b3c710882260f3fe9a85583e9. Report measures0.9303% dark source area inaccessible to assigned cutter/depth. Exact output verification independently parses bytes, validates safe rapid XY/stock bounds/terminal controls, and recomputes all continuous per-depth full-width sweeps:240 broad paths per depth and2119 fine paths, zero excess outside approved dark geometry/hanger reserve. `prepare.py` generated successfully; `verify.py` passed; py_compile and scoped git diff --check passed. Final exact-depth PNG inspected. Artifacts/report/verifier at artifacts/ornaments/hawkeye/two-bit/c091-approved-raised-plane/. No machine/backend/GUI interaction. Primary owns integration and physical execution.

## C-092 — finish recovery homing state — 2026-11-04
Owner: /root/recovery_home_completion. Root cause: JobWatchdogRecovery.poll returned for home-requested without ever checking homing completion, and active omitted that state. Added an explicit branch that waits for a newer fresh Idle report at spindle0 and reference_trusted before transitioning to recovered; a disconnect during homing re-enters saved-endpoint recovery. Existing guarded home remains the sole motion route and no automatic job resume was added. Regression proves pre-home status, Home state, untrusted reference and stale status cannot falsely complete recovery. Verification: `.venv/Scripts/python.exe -m pytest tests/test_backend_watchdog_recovery.py -q` — 9 passed in 2.92s; scoped git diff --check passed. No hardware, backend process or GUI interaction; primary owns activation and job continuation.

## C-094 — opted-in automatic continuation — 2026-11-04
Owner: /root/auto_continuation_implementation. Added backend-owned AutomaticContinuation, runtime status/poll integration and explicit API/CLI `automatic-continuation --enabled true --confirm`. Permission binds exact source, machine/tool definition and confirmed saved XYZ zero. Recovery waits for verified home completion, calls existing safe work-zero return, waits for a newer fresh Idle/0 report, trusted reference, no busy motion/pending acknowledgements, actual WCO matching captured offset and workXYZ within0.01mm of zero, then uses normal application authorizer/start and independent runtime safety gate. Replay uses a strict simple absolute metric G54 G0/G1 milling dialect and prior complete retract/XY/approach/plunge boundary before accepted-32, preserving exact executable suffix and original source mapping through repeated recovery. Three-attempt bound, 120second return timeout, exclusive continuation files, atomic policy audit persistence; backend restart requires explicit re-enable. Operator pause/abort/stop/manual motion/setup changes cancel permission, as do independent safety trips or non-connection failures. Documentation: docs/AUTOMATIC_CONTINUATION.md. Verification: `.venv/Scripts/python.exe -m pytest tests/test_auto_continuation.py tests/test_backend_watchdog_recovery.py tests/test_backend.py tests/test_backend_cli.py tests/test_backend_api.py tests/test_confirmation_stop_contract.py -q` —59 passed in6.96s; subsequent repeat-loss/source-mapping and timeout cases bring auto suite to16passed in1.45s. Includes real ApplicationController return-state integration. Scoped git diff --check passed. No live process/GUI/controller interaction; current job untouched. Primary owns activation at a safe boundary and explicit per-job enable.


## C-096 — executable concept-to-CAM workflow — 2026-11-05
Owner: /root. Added pine-cam (also python -m ttc3018_control.agent_cam) and replayable plaque, raster and shallow STEP pocket designs. Builds a fresh offline bundle with exact G-code, stock and cutter-envelope checks, a parsed-motion sweep SVG, inputs, hashes and CAM evidence. All three example bundles reproduce byte-for-byte from bundled inputs. Copilot instructions, AGENTS.md, README and the workflow guide point to the offline command and attach-only Pine CLI/Python API; backend CLI help and missing discovery errors explain how to choose the data root. Independent read-only API/CAM audit confirmed the entry points and root behavior. No live GUI, backend or hardware interaction.

Verification with .venv/Scripts/python.exe:
- -m pytest -q tests/test_agent_cam.py tests/test_ornament_cam.py tests/test_plaque_engraver.py tests/test_job_analysis.py — 64 passed.
- -m pytest -q tests/test_step_engraver.py — 64 passed.
- -m pytest -q tests/test_backend_cli.py tests/test_backend_api.py — 17 passed.
- -m ttc3018_control.backend.cli --help and load-job --help succeeded offline; git diff --check -- AGENTS.md README.md pyproject.toml passed.

## C-097 — machine-first Pine planning — 2026-11-05
Owner: /root. Added C-098 through C-112 covering portable job handoff, Machine and Job UX, agent CAM and optimization, parity, repository and data migration, and onboarding. Used C-096 and the Hawkeye evidence as inputs. Verified contiguous queue rows, column counts, and existing earlier dependency IDs with a local script. Planning review closed C-097. Milestone A is the next checkpoint.

## C-098 — baseline and journeys — 2026-11-05
Inspected Main.qml, view_model.py, job_service.py, CLI dispatch, agent_cam.py and the C-096/Hawkeye records. docs/MACHINE_FIRST_JOURNEYS.md records the action inventory and two journeys. Interaction counts await the C-108 simulation replay.

## C-099 — portable bundle contract — 2026-11-05
Documented the C-096-compatible v1 report entry point, project/source layout, replay and retention in docs/CNC_REVIEW_BUNDLES.md. Added explicit reported tool metadata to new exports. The existing versioned example specs remain the project inputs. Generation and legacy acceptance will be exercised together with C-100.

## C-100 — verified bundle loading — 2026-11-05
Pine opens report.json from the existing desktop picker and CLI load-job. Both use the existing application loader, verify each declared local asset, and parse the exact G-code bytes before replacing the loaded job. Provenance shows reported setup separately from live machine facts. Verified legacy manifest compatibility and preserved loaded program after a rejected change. .venv/Scripts/python.exe -m pytest -q tests/test_agent_cam.py tests/test_job_provenance.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_api.py — 39 passed. Planning review signed off C-098 through C-100.

## C-102 — Machine setup workspace — 2026-11-05
Machine now groups Connect, Home, and Work Zero in one workspace. Its entry opens the relevant stage and distinguishes connected controller status, trusted reference, current XYZ confirmation, and saved coordinates. Existing guarded motion and reuse actions remain the execution path. .venv/Scripts/python.exe -m pytest -q tests/test_c015_workspace.py tests/test_workflow_projection.py tests/test_qt_shell.py — 124 passed with isolated/offscreen coverage.

## C-103 — shared Job workspace — 2026-11-05
Job has direct bundle/G-code opening and one persistent preview across Review and Run. Job identity remains visible while switching panels, successful replacement clears acknowledgement and physical preflight, and a review acknowledgement advances within Job. .venv/Scripts/python.exe -m pytest -q tests/test_qt_shell.py tests/test_c015_workspace.py tests/test_workflow_projection.py — 124 passed, including persistent preview and keyboard order.

## C-104 — run and recovery controls — 2026-11-05
Active-job pause/resume/abort are visible outside the scrollable Run panel. Job shows the actual watchdog status and supported recovery actions, and describes the backend continuation policy. Nominal time remains distinct from observed activity. In the combined watchdog, automatic continuation, adapter, Qt shell and C-015 suite, 104 passed and one legacy static assertion expected the old control placement. Updated that assertion and reran .venv/Scripts/python.exe -m pytest -q tests/test_qt_shell.py -k "simulation_safety_capabilities or run_recovery" (2 passed) and -m pytest -q tests/test_backend_qt_adapter.py (10 passed, including the new recovery routing test). No live process or machine interaction.

## C-105 — offline CAM worker — 2026-11-05
Added pine-cam-worker submit/status/cancel/retry with snapshotted inputs, isolated generator process, resource bounds, terminal job state, and atomic bundle publication. Verified plaque, raster, STEP, cancellation, retry, source stability and rejection using .venv/Scripts/python.exe -m pytest -q tests/test_cam_worker.py tests/test_agent_cam.py — 11 passed. See docs/AGENT_CAM_WORKER.md.

## C-101 — backend discovery — 2026-11-05
Added token-free active root registration, explicit override and ambiguity/stale handling. Focused discovery, CLI and lifetime run: 26 passed with one existing Windows owner-marker teardown warning. Isolated backend separation and API run with temporary registry: 13 passed. Launch behavior preserved for existing roots.

## C-113 — agent instructions — 2026-11-05
Removed the mandatory delegation and model selection rule from AGENTS.md as requested. Added C-114 through C-116 for reusable hardware setup records.

## C-106 — raster fidelity ladder — 2026-11-05
Added exact parsed raster bundle comparison and immutable stepover variants under an explicit omission limit. Omission uses an inscribed sweep and excess uses a conservative outer envelope. Reuses the shared bundle verifier. .venv/Scripts/python.exe -m pytest -q tests/test_cam_ladder.py — 8 passed. Sample larger stepover reduced commands from 732 to 460 and nominal time by about 36%; this is a feed-based estimate.

## C-107 — ordered engraving and cutout — 2026-11-05
Added a centered tabbed STEP profile candidate, matching raster engraving, and a sequence manifest that binds separate pass reports and programs by hash, checks shared stock and datum, and puts the cutout last. Each pass keeps the existing guarded loader and an explicit fresh tool/Z setup step. The test loads both exact files through the application and replays their commands with separate Z setup on the virtual GRBL plant. .venv/Scripts/python.exe -m pytest -q tests/test_cam_sequence.py — 1 passed. This proves virtual command replay and file handoff, not physical cutting.

C-104 reconciliation: user confirmed overlapping recovery edits could be reconciled. Preserved recovery outside the scrollable Job panels, kept one global pause/resume/abort control group, and removed duplicate adapter/Qt methods. .venv/Scripts/python.exe -m pytest -q tests/test_qt_shell.py tests/test_c015_workspace.py tests/test_backend_qt_adapter.py — 81 passed.

## C-114 — portable hardware setup records — 2026-11-05
Added versioned stock, tool, fixture and optional process records with provenance, demo profiles, offline list/show and a pure validated CAM resolver. Existing machine and work-zero stores remain the live authority. .venv/Scripts/python.exe -m pytest -q tests/test_hardware_setups.py — 5 passed.

## C-115 — setup resolution and replay — 2026-11-05
CAM resolves one named record, rejects conflicting settings, and includes resolved fields plus provenance in the portable design and report. Background submission snapshots the same values. .venv/Scripts/python.exe -m pytest -q tests/test_cam_worker.py -k saved_setup_snapshot — 1 passed, including editing the registry after submission and rebuilding the exact bundle. Final C-114 agent suite was 7 passed.

## C-116 — reported setup at the desktop handoff — 2026-11-05
Machine shows the reported setup name. Job review shows material, fixture and datum evidence and flags a selected machine profile mismatch when the record names one. Current reference, work zero and preflight remain distinct backend facts. .venv/Scripts/python.exe -m pytest -q tests/test_cam_worker.py tests/test_qt_shell.py tests/test_job_provenance.py -k "saved_setup_snapshot or qt_shell_loads or gcode_picker or provenance" — 12 passed.

## C-108 — isolated parity — 2026-11-05
Verified repeat exact-byte loads and direct report loading from the offscreen Pine picker slot and CLI. Fixed an acceptance finding where a successful load returned before the new backend snapshot was visible. .venv/Scripts/python.exe -m pytest -q tests/test_machine_first_acceptance.py tests/test_backend_api.py tests/test_cam_sequence.py — 14 passed. Earlier parity run with backend separation E2E — 5 passed. Combined with pause/abort, changed setup and recovery suites from C-104. Measured file/settings handoff steps, not physical fixture timing. See docs/MACHINE_FIRST_JOURNEYS.md.

## C-109 — desktop CAM compatibility — 2026-11-05
Primary desktop navigation is Machine and Job. Existing text/plaque/STEP authoring remains reachable from CAM tools and is excluded from the normal progression after work-zero setup. C-096/C-105/C-107 provide offline plaque, raster, pocket and tabbed cutout examples. Broad offscreen run had 125 passes and one keyboard assertion still expecting Configure first. The updated keyboard test passed (1 passed, 61 deselected). Compatibility map is in docs/MACHINE_FIRST_JOURNEYS.md.

## C-088 — fine-residual fidelity/runtime ladder — 2026-11-05
Planning sign-off: independently checked report SHA-256 values against all five exact NC files and all five SVG previews. Confirmed the 0.04 mm reference rung adds zero omitted artwork relative to itself and measured omissions rise monotonically with coarser tolerances. The exact C-084 broad paths, conservative sweep fences, same setup, and nominal-only runtime caveat are documented. Accepted and marked C-088 done. Artifacts remain review-only; this is not physical readiness or cutting authorization.
Owner: luna-execution. The pre-existing `artifacts/ornaments/hawkeye/two-bit/c088-detail-ladder/` was empty (no files); consolidated the completed artifact there rather than leaving a duplicate sibling directory. The reproducible generator keeps exact C-084 broad paths at Z−0.6/−1.2/−1.625 mm (input SHA `60d6405c0fc7556f90807fd00932a95ef7c4ff64113464efcb6f18581bee0718`) unchanged and uses exact C-069 Z−0.04 mm residual source paths for the 0.04 mm full-fidelity rung (C-069 SHA `f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b`); the 0.08/0.12/0.20/0.32 mm rungs progressively simplify only those fine paths.

| Tolerance mm | Commands | Nominal min | Cut segments | ≥90° junctions | Retracts | Omitted art mm² | Additional omission vs 0.04 mm mm² |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.04 | 105,231 | 79.28 | 89,366 | 88.6% | 3,948 | 23.74 | 0.00 |
| 0.08 | 78,514 | 77.08 | 62,649 | 77.8% | 3,948 | 56.15 | 32.44 |
| 0.12 | 68,380 | 75.79 | 52,515 | 75.5% | 3,948 | 69.60 | 45.89 |
| 0.20 | 63,848 | 74.42 | 47,983 | 74.1% | 3,948 | 82.69 | 58.99 |
| 0.32 | 60,631 | 73.00 | 44,766 | 72.8% | 3,948 | 103.70 | 79.99 |

Verification: `.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c088-detail-ladder\prepare-c088-fine-ladder.py` completed all five exact output parses, nonnegative-XY and safe-Z rapid checks, terminal M5/M2 checks, equality of C-084 paths at every broad depth, candidate fine-path identity, stock bounds, and conservative full-width cutter containment in approved artwork/keepout. The report binds exact NC and SVG SHA-256 values; a separate hash check matched all five NC files. `.venv\Scripts\python.exe -m py_compile artifacts\ornaments\hawkeye\two-bit\c088-detail-ladder\prepare-c088-fine-ladder.py` and `git diff --check` passed. Runtime projections are nominal feed-based only (no completed-run calibration); 45 minutes remains aspirational. No machine/backend/GUI/hardware interaction and no job load/start. C-088 is implemented pending planning sign-off, not marked done.


## C-018 - reproducible ornament project - 2026-11-05

Added `artifacts/ornaments/hawkeye/two-bit/c018-reproducible-project/` with a versioned project manifest, rebuild instructions, exact approved-artwork source/setup hashes, vectorized source geometry, and output hashes for two separate review-only programs. The manifest distinguishes setup-derived measured/reported values from provisional settings and explicitly identifies that the recorded setups specify 100 x 100 mm stock while a 100 mm disc plus outside-cutter clearance needs an unverified 110 x 110 mm candidate blank. The original approved PNG remains unchanged.

Verification: `.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c018-reproducible-project\prepare.py` completed offline. `.venv\Scripts\python.exe -m pytest -q tests\test_ornament_project_bundle.py` - 2 passed. `git diff --check` passed. C-018 is implemented pending planning sign-off; no GUI/backend/hardware interaction, load, or start.


## C-019 - physical artwork and hanger review - 2026-11-05

Kept the approved PNG as input; the retained 90 mm artwork field is centered on the analytic 100 mm disc in a 110 mm review-frame candidate. The report measures exact emitted 30-degree/0.1 mm V-bit sweeps at the provisional 0.25 mm depth, black component/counter feature proxies, hanger keepout, and disc/stock ligaments. Source black area is 2413.5900 mm2; 105.3887 mm2 (4.3665%) remains unengraved (18.3324 mm2 intentionally reserved by hanger keepout; 87.0563 mm2 cutter-inaccessible outside it). Minimum connected-component/counter max-inscribed diameter is 0.07177 mm; 2 of 47 components and 55 of 125 counters are narrower than the 0.23397 mm cutter footprint. Exact sweep stays inside engravable approved art and clear of the 5 mm-radius hanger reserve. Hanger-to-disc-edge ligament is 3 mm.

Verification: `.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c018-reproducible-project\prepare.py` passed exact sweep, XY, rapid, artwork placement, keepout, and geometry checks. `.venv\Scripts\python.exe -m pytest -q tests\test_ornament_project_bundle.py` - 2 passed. `git diff --check` passed. Named setup stock is only 100 x 100 mm, not the candidate 110 x 110 mm; no production readiness claimed. C-019 implemented pending planning sign-off.


## C-020 - aligned two-tool review bundle - 2026-11-05

Generated separate engraving and tabbed disc/hole NC programs in `artifacts/ornaments/hawkeye/two-bit/c018-reproducible-project/`. Both explicitly select G54 P1 and share the same lower-left 110 x 110 mm candidate stock frame. The V-bit file is the approved source art at 90 mm on the 100 mm analytic part; the endmill file contains exactly one 4 mm hanger hole before one compensated 100 mm outside profile, with four 3 x 0.7 mm tabs on the outer contour only. The profile uses recorded 3.25 mm thickness plus explicitly provisional 0.2 mm breakthrough (Z-3.45); 5 passes, simulation gouge 0. Exact emitted V-bit sweep stays within artwork, stock and hanger keepout; exact profile sweep bounds are X/Y 1.8245 to 108.1755 mm within the candidate stock. No M6 or spindle start is present.

Exact output SHA-256: engraving `644b04cac6f869f3a28e18b8921ae7d676c7df59689fe255c888db1fab9ec23e`; profile `9652c1569e2b0f8f4321ffd504e94d5b38262f5ecdfd345bf032d208c292a612`; engraving preview `7dcdee4f9ce7fb787cedc09a207226ba88b83e13760a7595b162fe01079df870`. The manifest and report bind the source, both setup records, vector geometry and exact outputs. Rebuilding produced identical program/preview hashes.

Verification: `.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c018-reproducible-project\prepare.py` passed. `.venv\Scripts\python.exe -m pytest -q tests\test_ornament_cam.py tests\test_step_engraver.py tests\test_step_operations.py tests\test_step_simulation.py tests\test_ornament_project_bundle.py` - 127 passed. `.venv\Scripts\python.exe -m py_compile artifacts\ornaments\hawkeye\two-bit\c018-reproducible-project\prepare.py` and `git diff --check` passed.

Production release remains blocked: each named setup records 100 x 100 mm stock but the candidate uses an unverified 110 x 110 mm blank; actual fixture/clamp/safe-Z clearance, endmill flute/holder clearance, feeds/RPM/material response, breakthrough/tab retention and plywood flatness remain unknown. The source vector is a thresholded raster trace, with 4.3665% of black area unengraved and documented feature/counter limits. Candidates remain review-only. No application/backend/GUI/hardware interaction, load, or start. C-020 implemented pending planning sign-off; Run F stopped at its authorized checkpoint.


C-020 review-asset correction: XML validation caught a duplicate `cy` attribute in the engraving preview; fixed the SVG generator and rebuilt. Final `approved-artwork-geometry.svg`, `engraving-preview.svg`, and `profile-preview.svg` all parse as valid SVG. The corrected engraving preview SHA-256 is `8a7ded1ff3d8da50758f8406aa3a2a8ab0c2917d1d35c76e11f7394f3ec3ac65`; profile preview SHA-256 is `5f111b6081918b534f7441d892e7281210e2e223451cd5b1fe5a0a0c61dd7912`. NC hashes are unchanged. Final verification rerun: the five targeted CAM/profile/bundle suites passed (127 tests); SVG XML parsing, py_compile, and `git diff --check` passed.

## C-110 — repository layout — 2026-11-06
Grouped offline workflow modules under ttc3018_control/cam and retained the original module entry points. Added the project input/output/retention guide and ignore rules for new artifacts and local machine state. Removed tracked local machine data from the Git index without deleting it from disk. Added GUI resources to wheel and standalone packaging. Verified .venv/Scripts/python.exe -m pytest -q tests/test_agent_cam.py tests/test_cam_worker.py tests/test_cam_ladder.py tests/test_cam_sequence.py (21 passed), then built a wheel in a temporary source copy and ran an installed-wheel smoke check of every script entry point, offscreen GUI construction, and a saved-setup CAM build. Existing Hawkeye paths are unchanged.

## C-111 — external data-root migration — 2026-11-06
Temporary-fixture tests verify the copy, source preservation, active-owner refusal, migration reservation, destination hashes and startup root override. .venv/Scripts/python.exe -m pytest -q tests/test_data_migration.py tests/test_backend_discovery.py — 23 passed. Real cutover is an operator action at a separately authorized maintenance window.

## C-112 — start paths and final verification — 2026-11-06
Updated README start paths for Machine/Job, offline agent CAM, and contributor checks. Linked setup records and projects, updated Copilot instructions, corrected API transport documentation, and labeled superseded architecture. Clean temporary checkout verification of migration, discovery, offscreen desktop, and parity had 94 passes. Two checks that needed scripts/docs omitted from the first copy passed after adding those checkout files. Built a wheel and checked every script target, offscreen GUI startup and saved-setup CAM from the extracted wheel. Setup and standalone build PowerShell scripts parsed without errors. Standalone EXE compilation and physical machine cutover were outside this software verification. git diff --check passed. All 19 tasks C-098–C-116 signed off.
