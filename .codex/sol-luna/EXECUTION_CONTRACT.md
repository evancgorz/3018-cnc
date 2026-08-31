# Execution Contract

## Objective

Simplify the Qt Quick GUI by consolidating text and plaque creation into one engraving designer, moving existing-G-code loading into the first guided-setup page, removing Guided Setup from the top-level tabs and opening it from Machine, adding a deterministic loaded-job estimate plus pause-aware remaining time beside job progress, and collapsing direct coordinate entry by default.

## Current State

- `src/ttc3018_control/qt/qml/Main.qml` has four top-level workspaces: Prepare, Preview & Run, Machine, and Guided Setup.
- Prepare exposes separate `Load G-code`, `Text engraving`, and `Plaque builder` actions and separate `textDialog` and `plaqueDialog` implementations.
- The nine-step operational guided workflow is the fourth `StackLayout` page. Step 0 is Safety; step 5 is Create or load.
- Machine has a left navigation column ending with Console, and its right panel always shows the `Move to virtual coordinates` fields.
- Preview & Run shows acknowledgement-based percentage only. The existing STEP summary carries a STEP-specific estimate, but `GCodeProgram`, `JobService`, `ApplicationState`, and `ControllerViewModel` do not expose a generic estimate or remaining time.
- `GCodeProgram.segments` contains geometry and rapid/cutting classification but not modal feed. The parser already expands I/J arcs into line segments and supports G4/P.
- `JobService` owns start, pause, resume, failure, completion, spindle-stop, and return sequencing. Command acknowledgements can run ahead of physical motion, so acknowledgement percentage must not drive remaining time.
- Existing machine safety, job streaming, failure interlocks, delayed-M5 behavior, references, work zero, generators, and parser validation are passing and must remain intact.

## Final State

### Unified engraving designer

- Prepare contains one primary action named `Engraving designer` instead of separate Text engraving and Plaque builder actions.
- One centered modal dialog, `engravingDialog`, has a layout selector with exactly `Plain text` and `Plaque`.
- Shared controls are primary text/title, primary font, primary height, depth, safe Z, cut feed, plunge feed, and spindle RPM.
- Plain-text mode additionally shows letter spacing, line spacing, and Left/Center/Right alignment and calls the existing `preview_text`/`create_text` APIs.
- Plaque mode additionally shows subtitle enable/text/font/height, plaque width/height, inner margin, and border and calls the existing `preview_plaque`/`create_plaque` APIs.
- Mode-specific controls are hidden, not merely disabled. Switching mode immediately refreshes the existing live preview. Generate and load selects the matching existing generator, closes the dialog, and navigates to Preview & Run.
- Remove the old `textDialog` and `plaqueDialog` QML blocks. Do not merge or redesign the Python text/plaque generator implementations.

### Guided setup and loading

- The header tab model is exactly `Prepare`, `Preview & Run`, and `Machine`; workspace indices 0, 1, and 2 remain unchanged.
- The existing guided-setup page becomes a centered modal `guidedSetupDialog` opened by a `Guided setup` secondary button directly below Console in the Machine left navigation.
- Preserve all nine guided steps, state gates, Start over, Back, Next, physical-preflight confirmation, and guarded job start.
- On the last step, the `Done` button closes the dialog. Buttons that navigate to Prepare, Preview & Run, or Machine close the dialog before changing `window.workspace`.
- Step 0 (the first guided page) includes a `Load existing job…` button that opens the existing G-code file dialog. Rename that file dialog's visible title to `Load existing job`; continue using the existing validated G-code loading pipeline.
- Remove the standalone Load G-code action from Prepare. On guided step 5, retain navigation to Prepare and Preview & Run and update its copy to mention creating an engraving or STEP job; loading is already available on step 0.
- Update guided descriptions/reasons and README workflow text so no documentation instructs users to select a Guided Setup tab or a removed Text/Plaque action.

### Time estimate and remaining time

- Extend `src/ttc3018_control/gcode.py` so generic loaded/generated programs receive a deterministic `estimated_seconds` value.
- Preserve modal cutting feed while parsing. Each generated `Segment` records its effective cutting feed (or `None` for rapid). Use 3000 mm/min as the documented rapid assumption and 300 mm/min only as a documented fallback when cutting motion has no prior/modal F value. Sum three-dimensional segment distance divided by effective feed. Include G4 `P` dwell seconds. Arc duration uses the existing expanded arc segments. Reject non-finite or non-positive feed inputs through existing parser error behavior rather than producing invalid estimates.
- Add `estimated_seconds: float = 0.0` to `GCodeProgram` and `ProgramSnapshot`, with the new field last/defaulted to avoid breaking positional test construction.
- `ApplicationController.state` copies the program estimate into `ProgramSnapshot`.
- `JobService` owns pause-aware elapsed timing using an injectable monotonic clock (default `time.monotonic`). Start resets elapsed time; pause accumulates and freezes it; resume continues it; failure/abort/reset stop it; confirmed physical Idle at motion completion stops it before post-job M5/return sequencing.
- Expose `estimated_seconds`, `elapsed_seconds`, and `remaining_seconds`. Remaining is `None` when no estimate exists, otherwise never negative. If estimate expires while physical motion remains active, the UI displays `Finishing…`, not `0:00 remaining`.
- Do not calculate remaining time from `JobStreamer.progress`; acknowledgements are not physical completion.
- `ControllerViewModel` exposes formatted `job_estimate` and `job_time_remaining` strings and updates them through the existing 50 ms timer/state notification path. Format durations as `~M:SS` below one hour and `~H:MM:SS` at or above one hour. Loaded/not-running state shows the initial estimate; active state shows remaining; paused state appends ` (paused)`; complete state shows `Complete`.
- Preview & Run shows initial estimated duration adjacent to the preflight/job status before start. During a job, show remaining time on the same row as the progress percentage and immediately beside/above the progress bar.

### Collapsible coordinate entry

- In the Machine right panel, replace the always-open `Move to virtual coordinates` heading with a full-width disclosure button labeled `Move to coordinates` and a clear collapsed/expanded chevron.
- Store expansion in a QML boolean initialized to `false`; do not persist it between launches.
- The X/Y/Z grid and `Move safely` button are visible only when expanded. Existing validators, `move_to` call, feed inheritance, safe-Z planning, and envelope checks are unchanged.

## Allowed Scope

- `src/ttc3018_control/qt/qml/Main.qml`
- `src/ttc3018_control/qt/view_model.py`
- `src/ttc3018_control/gcode.py`
- `src/ttc3018_control/application/state.py`
- `src/ttc3018_control/application/controller.py`
- `src/ttc3018_control/application/job_service.py`
- Relevant tests under `tests/`, especially `test_gcode.py`, `test_application_contracts.py`, `test_qt_shell.py`, text/plaque tests if assertions require adaptation
- `README.md` for renamed/navigation workflow text
- `.codex/sol-luna/EXECUTION_RESULT.md`

## Protected Scope

- Do not alter text or plaque G-code geometry, fonts, border geometry, STEP algorithms, motion safety, jogging, reference/work-zero behavior, connection logic, Wi-Fi setup, job buffering limits, fail-closed behavior, delayed terminal M5 sequencing, or return-to-work-zero sequencing.
- Do not change public Python generator signatures (`preview_text`, `create_text`, `preview_plaque`, `create_plaque`) unless QML invocation requires no-signature wrapper slots; prefer calling existing APIs directly.
- Preserve workspace indices Prepare=0, Preview & Run=1, Machine=2.
- Preserve the user-owned untracked `config/work-zero.json`; never add, modify, delete, or commit it.
- Do not interact with, focus, capture, close, restart, or launch another TTC 3018 app while an instance is running. Source/test work must not disturb it.
- Do not add an executable packaging change or revive Tkinter.

## Implementation Steps

1. **Generic estimate model — `src/ttc3018_control/gcode.py`**
   - Extend `Segment` with a defaulted effective feed field and `GCodeProgram` with defaulted `estimated_seconds`.
   - Track modal F during `parse_gcode`, assign effective feed to linear and expanded arc segments, account for G4/P dwell, and compute the deterministic duration using the exact assumptions in Final State.
   - Add a focused helper only if it keeps parser logic testable; do not import STEP estimation internals.
   - Success: any validated G-code has a finite nonnegative estimate, known feed/distance cases are exact, and existing bounds/segment behavior is unchanged.

2. **Application snapshot — `src/ttc3018_control/application/state.py`, `controller.py`**
   - Add the defaulted estimate field to `ProgramSnapshot` and populate it from the loaded `GCodeProgram`.
   - Success: Qt-independent state consumers can read the loaded estimate without parsing UI summaries.

3. **Pause-aware run clock — `src/ttc3018_control/application/job_service.py`**
   - Add an injectable monotonic clock and timing fields/properties.
   - Update start/pause/resume/failure/abort/reset and the confirmed-Idle completion transition exactly as specified.
   - Do not alter acknowledgement streaming or delayed M5 ordering.
   - Success: remaining time counts down only during active physical job time, freezes while paused, and stops at motion Idle.

4. **Qt timing adapter — `src/ttc3018_control/qt/view_model.py`**
   - Add formatted estimate/remaining properties and formatting helper.
   - Ensure the existing polling timer emits state changes often enough for the remaining display to update at least once per second without adding another timer.
   - Preserve existing job confirmation and controls.
   - Success: QML receives stable initial, running, paused, finishing, and complete strings.

5. **Unified engraving QML — `Main.qml`**
   - Replace `textDialog` and `plaqueDialog` with the exact `engravingDialog` behavior from Final State.
   - Replace Prepare's three-item repeater with one Engraving designer button; leave STEP actions below it. Remove Prepare's G-code load action.
   - Update inspector placeholder copy from separate text/plaque wording to `engraving` wording.
   - Success: both existing generation paths remain reachable from one dialog and live preview reacts to every relevant field/mode change.

6. **Guided setup QML relocation — `Main.qml`, guided copy in `view_model.py`**
   - Remove the fourth header tab and fourth StackLayout page.
   - Move that page's complete content into `guidedSetupDialog`, add the Machine sidebar button under Console, and implement close-before-navigation/Done behavior.
   - Add Load existing job to step 0 and retitle the existing file dialog. Update step 5 copy/action labels.
   - Success: guided setup has one entry point from Machine, retains all nine state gates, and no top-level Guided Setup tab remains.

7. **Collapsible move-to QML — `Main.qml`**
   - Add the default-false expansion property and disclosure button; wrap only the target fields and Move safely button in conditional content.
   - Success: the subsection starts closed, toggles reliably, and sends the unchanged move request when open.

8. **Preview timing UI — `Main.qml`**
   - Add initial estimate and active remaining strings near the existing progress bar while preserving progress percentage and controls.
   - Success: estimate is visible before start and remaining/paused/finishing state is visible during execution.

9. **Documentation and tests**
   - Update README navigation/action names.
   - Add/adjust deterministic tests listed below. Do not weaken existing safety assertions to make changes pass.

## Validation Plan

1. **Static diff checks**
   - Command: `git diff --check`
   - Expected/pass: exit 0; no whitespace errors; `config/work-zero.json` remains untracked and untouched.

2. **G-code estimate tests**
   - Command: `.venv\Scripts\python.exe -m pytest tests/test_gcode.py -q`
   - Required cases: 60 mm at 60 mm/min equals 60 seconds; modal F persists; rapid uses 3000 mm/min; absent cutting F uses 300 mm/min; G4/P contributes seconds; arc estimate is finite/positive; previous bounds and safety tests remain unchanged.
   - Pass: all tests pass with exact/`pytest.approx` assertions.

3. **Application timing tests**
   - Command: `.venv\Scripts\python.exe -m pytest tests/test_application_contracts.py -q`
   - Use a fake monotonic clock. Verify start reset, active countdown, pause freeze, resume continuation, failure/abort/reset stop, motion-complete Idle stop, nonnegative remaining, and snapshot propagation.
   - Verify delayed M5 behavior and fail-closed tests still pass unchanged.

4. **Qt/QML targeted tests**
   - Command: `.venv\Scripts\python.exe -m pytest tests/test_qt_shell.py tests/test_text_engraver.py tests/test_plaque_engraver.py -q`
   - Required assertions: exactly three header tabs; no old Text engraving/Plaque builder/Load G-code Prepare actions; Engraving designer and both layout options present; guided dialog/button and Load existing job present; no top-level Guided Setup tab; coordinate disclosure defaults false; timing properties format initial/running/paused/finishing/complete states; reference control ordering remains valid.
   - Pass: all tests pass under existing offscreen Qt configuration.

5. **Full regression**
   - Command: `.venv\Scripts\python.exe -m pytest -q`
   - Expected/pass: all tests pass; no regression in motion, parser, STEP, generation, connection, streaming, or persistence suites.

6. **Qt shell validation**
   - Command: `.venv\Scripts\python.exe run.py --check`
   - Expected/pass: exit 0 and `TTC 3018 Qt shell check passed`.

7. **Runtime GUI procedure (only when no TTC 3018 instance is running; never disturb a user-owned instance)**
   - Starting state: no `run.py` TTC process, no machine connection required, `QT_QPA_PLATFORM` normal desktop.
   - Launch: user manually runs the normal launcher; Luna must not launch if another instance exists.
   - Actions/expected state: confirm three tabs; Machine > Guided setup opens centered dialog; first page has Load existing job; step navigation remains usable; Prepare > Engraving designer switches modes without overlap and live preview updates; Machine move-to disclosure starts closed and toggles; load an example G-code and confirm estimate before start. Do not connect or command physical hardware for visual QA.
   - Pass: no overlap/clipping at the existing supported window size, all controls are readable, modal navigation closes correctly, and no QML warnings/errors appear.
   - If an app instance is running, record visual validation as deferred by the protected running-instance rule; deterministic offscreen and shell validations remain sufficient for PASS.

## Failure / Escalation Rules

- `PLAN_INVALID` if the parser cannot retain modal feed without changing protected parser semantics, the existing QML cannot host the guided content in a dialog, or timing requires redesigning JobService completion/streaming architecture.
- `PLAN_INVALID` if combining dialogs requires changing generator geometry/signatures rather than selecting the existing APIs.
- Fix ordinary QML IDs/layout errors, test expectation changes caused by renamed controls, and implementation-caused timing bugs within EXECUTE.
- `BLOCKED` only for missing dependencies, permissions, or required environment failure. A running TTC app blocks only optional live visual validation, not source implementation or offscreen validation.
- Do not interact with a running machine/app to validate these changes.

## Completion Criteria

- Every Final State item is implemented within Allowed Scope and Protected Scope is unchanged.
- Targeted tests, full suite, Qt shell check, and diff check pass.
- `.codex/sol-luna/EXECUTION_RESULT.md` records `PASS`, exact commands/results, deviations, and runtime GUI validation status.
- Commit only task files and workflow artifacts; never commit `config/work-zero.json`.
- Commit and push to `main` after validation, following the repository's established workflow.
