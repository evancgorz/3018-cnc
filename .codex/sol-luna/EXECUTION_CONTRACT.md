# Execution Contract

## Objective

Evolve TTC 3018 Control from a fixed 3018 profile into a safe, extensible hobby-CNC platform. Implement rollout steps 1–9: versioned machine definitions, multiple machines, hardware setup, controller adapters, commissioning evidence, single-switch homing/limits, movable Z probing, fixed tool setting and movable XYZ probing, and fixed fixtures with reusable work-coordinate restoration. Preserve the current switchless 3018 as a supported all-options-off configuration. Rollout step 10—dual-motor squaring and auxiliary equipment—is documentation backlog only.

## Current State

- `machine_state.py` has flat `MachineProfile(name, travel_x/y/z, safe_z)`, `ProfileStore`, and a `VirtualEnvelope` whose manual reference is the minimum corner.
- `ApplicationController` loads one `config/machine-profile.json`; no machine catalog or stable machine ID exists.
- `work_zero_settings.py` persists one global XYZ work zero.
- `commissioning.py` has dormant boolean `CommissioningProfile`, `CommissioningStore`, and `InputTestTracker`, not wired into the application or UI.
- `grbl.py` parses status, `Pn`, positions, offsets, probe/setting feedback, and guards commissioning settings. Ordinary job G-code intentionally rejects G38.
- The modular-monolith boundary is QML → ViewModel → application controller/services → domain/adapters. Keep it in-process.
- Current profile UI only edits name/travel/safe Z. Manual reference and work-zero flows support the switchless 3018.
- Job streaming, jogging, connection recovery, spindle-stop interlocks, return-to-work-zero, generators, STEP 2.5D, and validation are protected.
- GRBL 1.1 supports `$H`, G38 probing and `[PRB]`, persistent G54–G59 via G10, and non-persistent G43.1 tool-length offsets. Stock GRBL 1.1 does not expose generic independent dual-motor squaring.

## Final State

### Machine catalog and schema

- A nested JSON schema has `schema_version=1`, immutable `machine_id`, name, controller kind, geometry, axes, per-axis limits/homing, probes, spindle, stepper declaration, and metadata.
- All optional hardware defaults off. The migrated TTC 3018 has no switches/homing/probes and retains manual reference/work-zero operation.
- `config/machines.json` stores profiles and `selected_machine_id`. First run atomically migrates the legacy profile using a deterministic ID; do not delete the legacy file.
- Create, edit, duplicate, select, and delete are supported. Keep at least one profile. Mutations are blocked while connected or motion is owned.
- Work zero, commissioning, fixtures, and tool records are keyed by `machine_id`. Legacy flat work-zero JSON migrates on explicit save, not merely read.

### Controller adapters

- Advanced application logic depends on a controller-adapter protocol and immutable capability set.
- `Grbl11Adapter` supports existing motion/status plus `$H`, G38.2, G10 L20 WCS setting, G43.1/G49 TLO, protected settings, and structured confirmations.
- `GenericGrblAdapter` preserves connect/status/jog/job/manual-reference behavior but marks automated homing/probing/tool/fixture operations unsupported.
- Availability always requires declared hardware + current commissioned evidence + adapter support. Unsupported declarations can be saved for future adapters but cannot emit commands.
- G38 remains forbidden in ordinary jobs; a dedicated service owns probing.

### Setup wizard

- Machine > **Machine setup** opens pages for: (1) identity/controller; (2) XYZ travel, safe Z, direction; (3) per-axis switches/homing with none or one ordinary input per axis, min/max end, polarity, hard-limit use; (4) movable Z plate, fixed tool setter, movable XYZ probe, fixed XYZ fixture—all independently optional; (5) spindle and stepper/control declarations; (6) safety/support summary; (7) save/select and optional **Commission now**.
- Validation rejects unsafe/non-finite geometry, contradictory declarations, and invalid feeds/search distances.
- Saving computes dependency fingerprints. Name-only edits retain evidence/reference/work zero. Geometry/controller/direction changes clear session trust and stale motion evidence. Homing changes stale homing/fixed-location dependencies. Probe geometry changes stale that probe and dependants.

### Commissioning and homing

- Machine > **Commissioning** opens a separate resumable workflow.
- Feature state is `off|declared|needs_commissioning|in_progress|commissioned|failed|stale|unsupported`; evidence includes fingerprint, timestamp, measurements, and note.
- Input tests require both asserted and released `Pn`; direction tests use bounded, confirmed motion.
- Allowed GRBL settings `$5,$20–$27,$130–$132` are reviewed, explicitly confirmed, written, read back, and verified.
- **Home machine** is never automatic. It requires commissioned inputs/directions/settings, adapter support, spindle off, explicit confirmation, and valid Idle/Alarm preflight.
- Successful `$H` requires acknowledgement plus fresh Idle/MPos. For a min-homed axis virtual minimum is post-home MPos; for max-homed it is `post-home MPos - travel`. Mixed ends work per axis.
- Failure/alarm/timeout/disconnect clears session position trust and sends no follow-on motion. Persistent fixture geometry survives, but cannot be used until re-homing.

### Transactional probing

- A Qt-independent `ProbingService` has explicit preflight, fast probe, retract/release, slow probe, offset application, safe retract, complete/fail/cancel states and exclusive command ownership.
- Preconditions: connected, fresh status, Idle, spindle confirmed off, current homed trust, declared+commissioned+supported probe, initially open input, known WCS, and every approach/search/retract target inside the envelope.
- Use bounded G38.2 fast touch → retract until released → slow touch → safe retract. Accept only fresh successful `[PRB:x,y,z:1]` belonging to the outstanding transaction.
- Route probe/homing responses before generic manual acknowledgements and job streaming. Timeout, disconnect, alarm, error, unexpected input, failed/stale probe, or impossible target fails closed.
- Movable Z plate applies plate thickness/search direction and sets work Z0 using adapter-generated G10 L20, then confirms fresh WCS/WCO.
- Movable XYZ probing asks for corner/orientation, sequentially probes selected faces, compensates tool/probe geometry, and sets selected X/Y/Z work coordinates. Intermediate XY moves occur at validated safe Z.

### Fixed tool setter

- Commissioning records machine-scoped safe approach XY/Z, direction, search/retract parameters, reference trigger machine Z, and at least three samples. Spread must meet configured tolerance.
- **Measure tool** requires current homed trust, performs the same two-stage probe, computes delta from commissioned trigger, applies G43.1 through adapter math, confirms `[TLO]`, and remains/returns at safe Z.
- TLO is session-only: clear with G49 on disconnect/reset/machine selection; never silently restore after power loss. UI shows active TLO.
- Sign math is pure adapter logic with table tests for positive/negative coordinates and both probe directions; QML performs no coordinate math.

### Fixed fixtures and reusable work restoration

- Named, machine-scoped fixture records contain G54–G59 slot, safe approach, probe/fixture geometry, expected bounds, fingerprints, and last confirmed origin.
- Commissioning probes and stores fixed fixture geometry. **Restore fixture** requires current homing and current evidence, then re-probes—it never blindly trusts old machine coordinates.
- Apply G10 L20, request/confirm fresh WCS/WCO within tolerance, persist only after confirmation, and leave at safe Z. Automated restore updates active work-origin state only after confirmation.

### Step 10 backlog only

- Create `docs/CNC_PLATFORM_BACKLOG.md` for independent dual-motor homing/squaring and auxiliary features: explicit stepper enable/disable, coolant/mist, air assist, dust/vacuum, RPM feedback, door/interlock/E-stop feedback, rotary axes, tool changers, driver diagnostics, sensorless homing, encoders.
- For each, record controller/IO prerequisites, hazards, extension point, and minimum future tests. Mark every item unimplemented. Add no runtime controls or commands.

## Allowed Scope

- `src/ttc3018_control/machine_state.py`, `commissioning.py`, `grbl.py`, `work_zero_settings.py`
- New domain/persistence modules for machine config/catalog, controller adapters, fixtures, and tool settings
- New application commissioning, homing, probing, and fixture services
- Required integration in `application/controller.py`, `machine_session.py`, `ports.py`, `state.py`, `events.py`, and connection routing
- `qt/view_model.py`, `qt/qml/Main.qml`, and new QML components beside it
- Relevant tests, `README.md`, `docs/ARCHITECTURE_DECISION_RECORD.md`, new backlog doc, and workflow result
- Change legacy profile config only if compatibility cannot be achieved in code.

## Protected Scope

- Do not change job streaming/buffering, pause/resume, delayed terminal M5 and spindle-stop safety, return-to-work-zero, jog semantics, connections/Wi-Fi, generators, STEP, preview, or ordinary G-code validation.
- Do not allow G38 in loaded/generated job files.
- Do not add HTTP/OpenAPI, daemon, cloud service, executable packaging, firmware changes, or Tkinter. Keep the modular monolith.
- Do not claim dual-motor/dual-limit/auxiliary support without a real adapter.
- Never write settings, home, probe, or move automatically on connect. Physical commissioning actions require explanation and explicit user action.
- Preserve manual reference/work zero when all optional hardware is off. Preserve compatibility for existing `MachineProfile`/`ProfileStore` imports.
- Never modify, stage, delete, or commit user-owned untracked `config/work-zero.json`; persistence tests use temp paths.
- Never disturb or launch TTC 3018. If an instance runs, do not terminate/restart/focus/capture/interact. Tell the user manual relaunch is required.

## Implementation Steps

1. **Definition domain — new `machine_config.py`, compatibility in `machine_state.py`.** Add frozen enums/dataclasses, exact JSON conversion, validation, subtree fingerprints, and legacy TTC 3018 factory. Adapt geometry to existing envelope APIs. Success: exact round trip, safe validation, stable relevant fingerprints, unchanged legacy envelope behavior.

2. **Catalog/migration — new `machine_catalog.py`, controller bootstrap.** Add versioned atomic store, deterministic migration, CRUD/select rules, active-machine state, and disconnected/no-owner mutation gates. Selection rebuilds machine-bound services and clears session trust/TLO. Success: idempotent migration and restart-safe independent profiles.

3. **Machine-scoped stores — evolve `work_zero_settings.py`; add fixture/tool stores.** Read legacy and versioned formats; associate legacy work zero with supplied active ID and rewrite only on explicit save. Add strict, atomic machine-keyed stores. Success: two-machine isolation and safe malformed-record behavior.

4. **Adapters — new `controller_adapters.py`; extend `grbl.py`.** Add capability protocol/factory, exact Grbl11 builders/parsers, GenericGrbl unsupported behavior, PRB/TLO/G54–G59/setting structures, and pure offset math. Success: unsupported operations emit nothing and exact GRBL transcripts test deterministically.

5. **Commissioning — evolve `commissioning.py`; new `application/commissioning_service.py`.** Migrate old booleans, add typed evidence/state, pure dependency invalidation, Pn tracking, bounded direction checks, settings review/write/readback, operation ownership, and response priority. Success: evidence cannot commission early; selective invalidation matrix passes.

6. **Setup/commissioning UI — ViewModel and new `MachineSetupDialog.qml`/`CommissioningDialog.qml`.** Expose profile CRUD/drafts/capability reasons/workflow state; add compact selector/actions on Machine. Keep domain math in Python. Use exact wizard pages/defaults; save reports stale evidence. Success: current no-hardware profile is straightforward and unsupported actions cannot invoke services.

7. **Homing — new `application/homing_service.py`; session/envelope changes.** Implement preflight, ownership, `$H`, ack+fresh Idle completion, min/max/mixed transforms, and fail-closed lifecycle. Wire explicit UI. Never auto-use `$X`. Success: exact reference math and no trust/follow-on motion after failure.

8. **Movable probing — new `application/probing_service.py`.** Build explicit command-correlated state machine and pure Z/XYZ plan builders. Add placement/geometry/corner UI and final motion confirmation. Set WCS only after successful slow touch and verify. Success: failure injection at every state cannot send premature G10.

9. **Fixed tool and fixture production workflows.** Extend probing for three-sample setter commissioning, production TLO measurement/confirmation/lifecycle clearing, named fixture CRUD, fixed-fixture commissioning, re-probe restoration, WCS verification, and safe-Z finish. Add status/actions in UI. Success: sign/tolerance/machine isolation/current-homing tests pass.

10. **Backlog documentation only.** Create the step-10 backlog with prerequisites, hazards, extension points, and future tests. Audit that no associated runtime controls/commands were added.

11. **Docs/evidence/commits.** Update README and ADR for setup, commissioning, adapters, machine-scoped state, and transactional ownership. Write execution result. Commit coherent passing milestones frequently and push `main`; never stage work-zero JSON.

## Validation Plan

1. **Baseline/static:** before edits run `git status --short` and `.venv\Scripts\python.exe -m pytest -q`. After milestones run `git diff --check` and status. Pass: baseline characterized, no whitespace errors, user work-zero remains untouched/untracked.

2. **Schema/catalog/persistence:** add `test_machine_config.py`, `test_machine_catalog.py`, and work-zero tests. Run those plus `test_machine_state.py`. Cover round trip, all-off defaults, invalid/future schema, stable/idempotent migration, atomic-failure preservation, CRUD/select/last-profile rule, legacy work-zero migration, two-machine isolation, name-only fingerprint stability.

3. **Adapters/parsing:** run `test_grbl.py` plus new `test_controller_adapters.py`. Assert capability matrix, exact `$H`/G38.2/G10 L20/G43.1/G49, unsupported emits nothing, PRB success/failure, TLO/WCS reports, finite guards, TLO sign tables, setting allowlist.

4. **Commissioning:** expand `test_commissioning.py`, add `test_commissioning_service.py`. Cover old migration, every state transition, asserted/released and bounce, readback mismatch, ownership, timeout/disconnect/alarm, persistence, and invalidation matrix for name/travel/direction/controller/homing/every probe/unrelated edits.

5. **Homing:** add `test_homing_service.py`, expand session/envelope tests. Cover preflight denials, Idle/alarm-lock, no automatic `$X`, ack without fresh Idle, min/max/mixed transforms, noise, timeout/error/alarm/disconnect, no follow-on motion, manual-reference regression.

6. **Probing:** add `test_probing_service.py` using fake transport/clock/scripted reports. For Z and every XYZ corner cover preflight, initially closed probe, bounds, exact fast/retract/release/slow order, stale/failed PRB, timeout/error/alarm/disconnect/cancel at each state, no early G10, thickness/radius/direction math, WCS confirmation, safe retract.

7. **Tool/fixtures:** add `test_tool_setting.py` and `test_fixtures.py`. Cover sample minimum/tolerance/outliers, sign tables, TLO mismatch, G49 lifecycle, no restore, G54–G59 CRUD, machine isolation, stale/unhomed denial, mandatory re-probe, origin math, WCO tolerance, safe-Z, and no persistence update on failure.

8. **Application regression:** expand application/session/connection tests. Verify response-routing priority, mutual exclusion with jobs/jogs/manual commands, profile-switch gates, lifecycle trust/TLO clearing, delayed M5, return-to-work-zero, Wi-Fi, and persistent work zero.

9. **Qt:** expand `test_qt_shell.py` with offscreen loading/ViewModel tests for dialogs, all-off drafts, validation, selector, capability reasons, disabled unsupported calls, confirmations, tool/fixture status, and existing layout/reference controls.

10. **Full validation:** run `.venv\Scripts\python.exe -m pytest -q`, `.venv\Scripts\python.exe run.py --check`, and `git diff --check`. Pass: all tests, `TTC 3018 Qt shell check passed`, clean diff check.

11. **Backlog boundary:** `rg -n "dual.motor|squar|coolant|mist|air assist|vacuum|stepper enable|tool changer|rotary|encoder" src tests docs`; inspect every match. Pass: no new production implementation for step 10.

12. **GUI/manual:** agents do not launch/interact with TTC 3018. Provide a user relaunch checklist: current 3018 selected/all options off; setup pages readable; create second mock profile; unsupported explanations shown; commissioning cards correct; switch back disconnected; manual reference/jog/job still available. Automated PASS relies on offscreen QML/shell tests, not physical commissioning.

## Failure / Escalation Rules

- `PLAN_INVALID` if transport ownership/fresh correlation requires redesigning protected streaming, GRBL semantics contradict adapter assumptions, machine scoping requires destructive migration, or fixed-tool sign cannot be proven with pure math/tests. Do not guess or expose unsafe production actions.
- `PLAN_INVALID` if separate setup/commissioning components cannot fit the current ViewModel boundary without architectural redesign.
- Luna fixes ordinary implementation/test/QML/routing issues. `BLOCKED` is for missing dependencies, permissions, or unusable test environment; a running app blocks only optional visual interaction.
- Never weaken safety tests, bypass gates, auto-`$X`, or replace session homing/re-probing with blind persisted coordinates.
- Implement and validate in order with milestone commits. Do not silently omit steps 1–9.

## Completion Criteria

- Every rollout 1–9 requirement is implemented; rollout 10 exists only in backlog docs.
- Legacy TTC 3018 migrates to all-options-off and retains its manual workflow.
- Multiple machines, scoped persistence, capability gates, selective commissioning, homing, movable probes, fixed tool setting, and fixture restoration have deterministic coverage.
- Automation requires declared hardware, current evidence, adapter support, session trust, safety preflight, and explicit initiation.
- Targeted tests, full suite, shell check, diff check, and backlog audit pass.
- Execution result records PASS/evidence or correct escalation; coherent commits are pushed to `main`; `config/work-zero.json` remains untouched.
