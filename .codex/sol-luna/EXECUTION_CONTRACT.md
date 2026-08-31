# Execution Contract

## Objective

Deliver a complete UX and responsiveness pass for TTC 3018 Control. Make the application task-oriented, continuously responsive, explicit about what it is doing, calm and modern in motion, actionable when prerequisites or failures occur, and progressively disclosed for first-time versus advanced users. Consolidate all improvements discussed: readiness workflow, setup/commissioning UX, machine profile management, probing/tool/fixture task flows, Preview & Run confidence, recovery guidance, first-run/expert modes, non-blocking operations, busy/progress feedback, motion phases, targeted updates, debounced/cached previews, notification hierarchy, duplicate-action protection, focus/keyboard polish, and measurable performance.

## Current State

- The Qt Quick app has Prepare, Preview & Run, and Machine workspaces plus modal guided setup, machine setup, commissioning, engraving, and STEP dialogs.
- The compact status row shows machine/work coordinates, reference, work zero, spindle, and GRBL state, but it is descriptive rather than a clickable readiness workflow.
- Most ViewModel properties notify through one broad `state_changed` signal. The 50 ms timer and frequent status reports can trigger unnecessary reevaluation and canvas repaint.
- STEP import uses a daemon `threading.Thread` around the existing isolated OpenCASCADE worker and exposes only `step_importing` plus one status string. STEP path generation, G-code parsing/loading, text/plaque generation, and some preview work still execute synchronously from UI slots.
- Buttons inconsistently indicate work. STEP import changes text to “Importing…”, while connect, generate, load, motion, homing, probing, return, save, and profile operations often look unchanged until completion.
- `ApplicationState.active_operation` exists but is an unused string. Motion, jobs, homing, probing, tool setting, fixtures, Wi-Fi, and connection services each own state independently.
- Job progress and estimated remaining time exist. Motion services own safe-Z queues but do not expose user-facing phase names such as raising Z, moving XY, lowering Z, or waiting for Idle.
- Toasts are used for both routine acknowledgement and important failures. There is no persistent recovery panel or shared issue model.
- Confirmation tokens prevent stale confirmation dialogs, but background tasks lack a general operation generation/token model.
- Engraving live preview recalculates immediately on every field change. STEP preview generation is synchronous and can be repeatedly invoked while editing.
- The recent machine-platform work provides versioned profiles, capability declarations, commissioning evidence types, adapters, homing/probing/tool/fixture services, and setup/commissioning entry points, but their UX remains technical and incomplete.
- The repository rule forbids disturbing a running TTC 3018 instance. Offline Qt checks and deterministic tests are available.

## Final State

### Task-oriented readiness and navigation

- A persistent, compact readiness strip appears below the app header on all workspaces:
  `Connection → Machine reference/Home → Work zero → Job → Ready to run`.
- Each item has text plus icon, one of `complete|required|working|warning|unavailable`, and an explanation. Color is supplemental, not the only state indicator.
- Clicking an incomplete item performs the safest next navigation/action: open Connection, Machine controls, relevant homing/reference choice, work-zero guidance, Prepare/load, or Preview & Run. It never starts physical motion without the existing confirmation.
- The strip derives from a Qt-independent `ReadinessSnapshot`; QML contains no safety logic.
- Each workspace has exactly one visually dominant primary action based on current state: **Prepare machine**, **Create/load job**, **Review & run**, **Pause**, or **Recover safely**. Secondary/advanced actions are visually quieter.

### Shared operation model and immediate feedback

- Add typed `OperationSnapshot` and `OperationCoordinator` in the application layer. Fields: unique generation token, category, name, phase, state, optional 0–1 progress, started monotonic time, cancellable flag, blocking scopes, success/failure summary, and optional recovery action.
- Categories are `background`, `connection`, `machine_motion`, `job`, and `safety`. States are `idle|queued|running|waiting_controller|succeeded|failed|cancelled`.
- The coordinator arbitrates UI/application conflicts and stale results; it does not replace GRBL response ownership in MotionService, JobService, HomingService, or ProbingService.
- Every user action displays feedback in the same event-loop turn: button label/spinner, operation strip, inline status, or confirmation dialog.
- Late results are ignored unless their generation token is still current. Double-clicking/repeating an active operation cannot enqueue duplicates.
- Controls are disabled by blocking scope, not by a global app-wide busy flag. Console viewing, navigation, status inspection, feed hold, spindle stop, and safe abort remain available where appropriate.

### Non-blocking execution

- Add `qt/task_runner.py` using `QThreadPool/QRunnable` and Qt signals. It executes Python callables, returns typed success/failure with generation token, and never mutates QML/ViewModel state from a worker thread.
- Replace raw STEP import threading with this task runner while retaining the existing short-lived subprocess/native crash isolation.
- Run STEP import/analysis, STEP toolpath generation/simulation, large G-code parsing/loading, text/plaque generation, preview geometry conversion, file saving, host discovery, and connection attempts off the UI thread when they can exceed one frame.
- Transport polling and all GRBL response/state-machine mutation stay serialized on the controller/UI thread. Background connection work may prepare/open a transport, but ownership is transferred exactly once before polling.
- Cancellation is cooperative for pure Python work and terminates only the app-owned STEP import subprocess when needed. It never kills the running GUI or controller process.

### Motion and machine-operation feedback

- MotionService exposes phase data for safe moves: `raising_safe_z|moving_x|moving_y|lowering_z|waiting_idle|complete|failed`.
- Return-to-reference/work-zero, coordinate moves, homing, probing, tool measurement, fixture restore, and job completion visibly display their physical phase and target.
- “Complete” is shown only after required acknowledgement plus a fresh GRBL `Idle`/confirmation. While reports are delayed, show **Waiting for controller…** with elapsed time.
- Motion UI retains prominent **Feed hold**, **Spindle off**, and context-appropriate **Cancel/Abort**. Safety actions never disappear behind a spinner.
- Live coordinates continue updating during operations and the destination/active axis is highlighted without interpolating or concealing the exact reported value.

### Efficient state projection and smooth rendering

- Keep `state_changed` temporarily for compatibility, but add targeted ViewModel signals: `connection_changed`, `position_changed`, `readiness_changed`, `operation_changed`, `preview_changed`, `job_changed`, `issues_changed`, and `profiles_changed`.
- Status reports update authoritative state immediately. Visual coordinate notifications are coalesced to at most 30 FPS, while alarm, spindle, reference, work-zero, job, and safety changes emit immediately.
- Toolpath canvases repaint only on preview/viewport changes; machine-position updates do not rebuild static preview geometry.
- No QML property binding performs expensive Python work.

### Debounced, cached, atomic previews

- Add a reusable 150 ms debouncer for engraving and STEP setting edits using a fake-clock-testable generation counter.
- Keep the previous valid preview visible with an **Updating preview…** overlay. Never clear it merely because a newer computation is running.
- Apply preview results atomically only when the token and complete input fingerprint match the latest request.
- Cache immutable imported STEP geometry and reuse unchanged normalization/model strokes. Cache generated preview results by input fingerprint with a bounded in-memory LRU.
- Invalid current settings show an inline validation message while preserving the last valid preview, clearly labeled as stale.
- Preview cancellation/replacement cannot overwrite a newer result.

### Notification and recovery hierarchy

- Routine in-progress feedback is inline. Success uses a brief non-modal toast. Failures requiring user action create a persistent `IssueSnapshot` banner/card.
- Issue data includes severity, concise title, explanation, whether spindle may be running, whether reference/work-zero trust was lost, whether job reload is required, and explicit actions.
- The failure/recovery panel remains until resolved/dismissed where safe. Typical actions: **Spindle off**, **Reconnect**, **Home/re-establish reference**, **Reload job**, **Open console**, **Retry**.
- Connection errors stay in the connection dialog with retry/edit controls. Validation errors stay next to their fields. Avoid decision-free popups.
- Alarms, spindle-uncertain states, and lost position trust are never transient toast-only messages.

### Machine profiles, setup, commissioning, and task wizards

- Machine profile selector displays name, controller, travel, connection preference, capability badges, and commissioning status; internal IDs are hidden.
- Add working **Create**, **Duplicate**, **Edit**, **Delete**, and **Select** flows using existing catalog rules and disconnected/idle gates.
- Machine Setup becomes a progressive wizard: identity/controller; geometry; per-axis limits/homing; probes; spindle/control; review/save. All optional hardware defaults off and irrelevant pages/fields collapse.
- Commissioning displays one card per declared capability with `not installed|needs setup|ready to test|commissioned|stale|unsupported|failed`, exact reason, dependency change, and **Commission/Recommission** action.
- Probing is presented as user tasks rather than GRBL terminology: **Set material surface**, **Find stock corner**, **Measure current tool**, **Restore fixture**. Each wizard shows placement, expected motion, current phase, result, and safety confirmation.
- Advanced details—input pins, WCS slot, raw measurements, controller settings, and console—are behind an Advanced disclosure and never required for normal operation.

### Preview & Run confidence

- Preview & Run begins with a stable summary card: file/model, estimated time, stock/material size, required tool, maximum depth, operation count/order, spindle command/RPM, work-zero convention, envelope result, and final destination.
- Prerequisites are actionable cards. Clicking a failed item navigates to its remedy.
- The run button transitions through **Checking preflight…**, **Starting spindle…**, **Waiting for controller…**, and **Running**. It cannot be double-started.
- Job progress displays operation phase, elapsed/remaining time, acknowledged command progress, and a clear distinction between streaming complete and physical motion complete.

### First-run, normal, and advanced experience

- Add versioned `config/ui-preferences.json` for first-run completion, expert-mode preference, last workspace, and non-safety disclosure states. Do not persist physical safety acknowledgements.
- First run guides machine selection/creation, connection, all-options-off versus declared hardware, and manual reference basics. It never performs automatic motion.
- Normal launches go directly to the Machine workspace/readiness strip. Expert mode reveals diagnostics, console, raw WCS/TLO/pin values, and advanced STEP controls.
- Focus returns to the invoking control after dialogs close. Keyboard navigation and focus order work throughout. Add shortcuts only for non-ambiguous actions; require confirmation for machine movement/job start. Space/Enter must not accidentally retrigger held jog controls.
- Respect Qt reduced-motion/system animation preference when available. Use 100–150 ms hover/pressed/opacity transitions and short page crossfades; alarms and safety transitions are immediate.

## Allowed Scope

- New application modules for operation/readiness/issue coordination and UI preferences
- `src/ttc3018_control/application/state.py`, `events.py`, `controller.py`, all existing application services where phase exposure is required
- `src/ttc3018_control/qt/view_model.py`, new `qt/task_runner.py`, and all QML under `qt/qml/`
- Machine catalog/config/commissioning persistence only where required for full profile/setup UX
- G-code/generation/STEP modules only for cancellation hooks, immutable inputs, progress callbacks, or safe caching; generated geometry and validation semantics are protected
- Relevant tests, README, ADR, and workflow result

## Protected Scope

- Preserve GRBL command semantics, response ownership, motion envelopes, job buffering, delayed M5/spindle-stop safety, pause/resume/abort, return sequencing, reference/work-zero trust, Wi-Fi behavior, and fail-closed rules.
- Do not mark machine motion complete from animation, command transmission, or acknowledgement alone.
- Do not perform machine motion, homing, probing, spindle start, tool measurement, or fixture restoration automatically.
- Do not permit G38 in ordinary job G-code or expose arbitrary command execution.
- Do not change text/plaque/STEP toolpath geometry or loosen parser/simulation/envelope validation.
- Keep the modular monolith; no HTTP server, daemon, cloud dependency, executable packaging, or Tkinter.
- Do not modify, stage, delete, or commit `config/work-zero.json`, generated `config/machines.json`, logs, or user data.
- Do not launch, focus, capture, restart, terminate, or interact with a running TTC 3018 instance. Source/offscreen validation only unless the user gives explicit current permission.

## Implementation Steps

1. **Baseline and instrumentation — tests plus `qt/task_runner.py` test hooks.**
   - Record baseline suite/shell time. Add an event-loop heartbeat probe and deterministic fake clock/executor used by later tests.
   - Define performance fixtures: large synthetic G-code, representative engraving changes, and existing STEP examples.

2. **Operation/readiness/issue domain — new `application/ux_state.py`; `state.py`, `events.py`.**
   - Add enums and immutable snapshots exactly as Final State specifies.
   - Implement `OperationCoordinator` with generation tokens, scoped conflicts, transitions, cancellation, stale-result rejection, elapsed time, and bounded completed-operation retention.
   - Add pure readiness derivation and issue/recovery models. Extend `ApplicationState` with defaulted fields last for compatibility.

3. **Application-service phase integration — controller, connection, motion, job, homing, probing, tool, fixture, Wi-Fi services.**
   - Map each service’s existing authoritative states to operation snapshots without changing command ownership.
   - Expose exact safe-motion and job phases. Require fresh Idle/PRB/TLO/WCO completion as currently specified.
   - Add conflict scopes and duplicate-action rejection. Preserve safety actions during all operations.

4. **Qt task runner and async migration — new `qt/task_runner.py`; ViewModel slots.**
   - Implement QThreadPool worker/result/cancel API with generation tokens and GUI-thread-only completion.
   - Migrate raw STEP thread first, retaining subprocess isolation, then STEP generation/simulation, G-code load/parse, engraving generation, file save, discovery, and connection.
   - Capture immutable inputs before dispatch. Never pass mutable controller/session objects into workers.

5. **Targeted ViewModel projection — `view_model.py`.**
   - Add targeted signals and properties for operation, readiness, issues, profile cards, preview updating/stale state, and motion phase.
   - Coalesce position notification to 30 FPS while emitting safety changes immediately. Keep global signal only for compatibility and remove unnecessary calls.
   - Add action-routing slots for readiness cards and recovery actions; no safety decisions in QML.

6. **Reusable responsive QML components — new files under `qt/qml/components/`.**
   - Create `BusyButton`, `ReadinessStrip`, `OperationBanner`, `IssueBanner`, `StateBadge`, `ActionCard`, `InlineValidation`, and `LoadingOverlay`.
   - Components receive properties/actions only and match existing blue-accent dark design. Include hover/pressed/focus states, fixed geometry while labels change, reduced-motion support, and accessible text.

7. **Header/workspace task flow — `Main.qml`.**
   - Install readiness strip and operation banner across all pages.
   - Compute one primary action per workspace from ViewModel properties. Route incomplete readiness items and retain all advanced controls under secondary disclosures.
   - Ensure banners/status do not shift content when appearing.

8. **Debounced preview pipeline — ViewModel, generation service, preview QML.**
   - Add 150 ms text/plaque/STEP debouncing, latest-generation-only acceptance, bounded LRU, immutable fingerprints, previous-valid preview retention, and atomic swaps.
   - Move expensive conversion/generation off-thread. Overlay updating/stale/validation states without canvas flicker.
   - Separate preview repaint signals from position/state signals.

9. **Profile/setup/commissioning redesign — machine QML dialogs and ViewModel/catalog APIs.**
   - Build user-facing profile cards and complete CRUD flows. Hide IDs.
   - Replace placeholder setup screens with the progressive wizard and capability-aware summary.
   - Add commissioning cards/reasons/actions based on evidence and adapter support. Preserve all-options-off 3018 path.

10. **Machine task wizards — new QML dialogs; probing/tool/fixture ViewModel adapters.**
    - Implement Set material surface, Find stock corner, Measure current tool, and Restore fixture workflows around existing services.
    - Show diagrams/instructions using simple code-native QML shapes/icons, expected bounded motion, live phase, cancel/abort, and result confirmation.
    - Do not add controller commands or calculations to QML.

11. **Preview & Run and recovery redesign — `Main.qml`, ViewModel.**
    - Add confidence summary, actionable prerequisites, start-state progression, operation-aware progress, and physical-versus-streaming completion text.
    - Add persistent recovery panel with exact trust/spindle/reload consequences and approved actions.

12. **First-run/expert preferences and polish — new `ui_preferences.py`, QML.**
    - Add atomic versioned preferences, first-run wizard, expert toggle, last-workspace/disclosure persistence, focus restoration, keyboard/focus order, cursor states, subtle transitions, and reduced-motion handling.
    - Never persist safety acknowledgements or active-operation state.

13. **Documentation, cleanup, and milestone commits.**
    - Update README and ADR. Remove obsolete duplicate UI paths only after replacement tests pass.
    - Commit and push coherent milestones to `main`; never stage user config.

## Validation Plan

1. **Static/baseline**
   - `git status --short`; `.venv\Scripts\python.exe -m pytest -q`; `.venv\Scripts\python.exe run.py --check`; `git diff --check`.
   - Pass: baseline recorded; no user config touched; existing suite and shell pass before edits.

2. **Operation coordinator tests**
   - Add `tests/test_ux_state.py`.
   - Cover every state transition, fake-clock elapsed time, progress validation, scoped conflicts, cancel rules, duplicate request, stale token, background+machine coexistence, safety action availability, and bounded history.

3. **Readiness/issue tests**
   - Table-test disconnected, connecting, manual-reference, homing-capable, missing work zero, no job, invalid envelope, ready, running, paused, failed, spindle-uncertain, and lost-trust combinations.
   - Pass: exact status/action/reason; no QML-derived safety result.

4. **Task-runner/threading tests**
   - Verify worker runs off GUI thread, result/error returns on GUI thread, token propagation, cancellation, stale suppression, exception formatting, and shutdown without leaked threads/processes.
   - Event-loop heartbeat must continue during delayed fake STEP import, generation, G-code parse, connection, and file save.

5. **Preview tests**
   - Fake clock/executor tests: burst edits cause one computation after 150 ms; old result cannot overwrite new; previous preview remains; invalid edit labels preview stale; cache hit skips generation; LRU bound; preview signal does not fire on position-only status.

6. **Motion/job phase tests**
   - Expand motion/job/homing/probing/application tests for exact phases, acknowledgement versus fresh Idle, waiting-controller elapsed state, failure/recovery issue contents, duplicate clicks, and safety-control availability.
   - Existing delayed M5, spindle-stop, abort retention, jog, return, and streaming tests must pass unchanged.

7. **Profile/setup/commissioning tests**
   - Test profile card projection, hidden IDs, CRUD gates, wizard defaults/validation, irrelevant-field hiding, evidence status/reason, stale dependency explanation, and all-options-off workflow.

8. **Probe/task wizard adapter tests**
   - Test exact user task → service plan mappings, confirmations, cancellation, phase copy, geometry validation, successful result, and all existing fail-closed probe/tool/fixture cases.

9. **Qt/QML structural and offscreen tests**
   - Expand `test_qt_shell.py`; load all components/dialogs offscreen.
   - Assert readiness strip, one primary action/workspace, BusyButton states, operation/issue banners, no layout overlap at 1180×720 and 1500×920, focus order, first-run/expert visibility, and no QML warnings.

10. **Performance acceptance**
    - Add deterministic/instrumented tests, not brittle absolute microbenchmarks:
      - UI heartbeat gap stays below 100 ms during fake slow operations.
      - 100 status reports cause at most 30 position notifications per second and no preview rebuild.
      - 20 rapid preview edits cause one final generation.
      - Large G-code and representative STEP processing run off the GUI thread.
      - Repeated preview replacement leaves no unbounded worker/cache growth.

11. **Full regression**
    - `.venv\Scripts\python.exe -m pytest -q`; `.venv\Scripts\python.exe run.py --check`; `git diff --check`.
    - Pass: all tests and shell pass, no generated/user config staged.

12. **Runtime GUI validation**
    - Only when no TTC 3018 instance is running. The agent must not launch if one exists.
    - Start disconnected at 1500×920, then 1180×720. Navigate all workspaces/dialogs; trigger fake/offline import/generation/load paths; verify immediate button feedback, responsive dragging/navigation, stable previews, banner layout, keyboard focus, and expert toggle. Do not connect to or move physical hardware.
    - Pass: no freeze, overlap, unreadable state, focus trap, QML warning, or stale result. If an instance is running, record this optional visual step deferred; offscreen/performance tests remain required.

## Failure / Escalation Rules

- `PLAN_INVALID` if async connection cannot transfer transport ownership safely without redesigning ConnectionService, if QThreadPool cannot preserve existing STEP subprocess isolation, or if service phases cannot be exposed without changing protected GRBL response ownership.
- `PLAN_INVALID` if targeted signals require abandoning current public ViewModel compatibility rather than staged migration.
- Fix routine QML, worker, debounce, token, cache, focus, and test failures during execution.
- `BLOCKED` for missing Qt/dependencies/permissions. A running TTC app blocks only optional runtime visual validation.
- Never “improve responsiveness” by acknowledging machine completion early, allowing conflicting commands, reducing validation, or moving controller mutation to worker threads.
- Do not mark PASS with placeholder setup/commissioning pages, synchronous expensive slots, or busy labels that are not tied to real operation state.

## Completion Criteria

- Every Final State section is implemented with no placeholder controls.
- Every potentially slow user action gives feedback immediately and does not block the GUI thread.
- Machine operation completion remains controller-confirmed and all safety controls remain available.
- Readiness, operation, issue, profile, commissioning, probing, Preview & Run, first-run, and expert UX are functional and tested.
- Targeted signals materially reduce unnecessary preview/canvas updates; debounce/cache/stale-result protections pass.
- Full tests, shell check, performance acceptance, and static checks pass.
- Workflow result records exact evidence and deviations; coherent commits are pushed to `main`; user config remains untouched.
