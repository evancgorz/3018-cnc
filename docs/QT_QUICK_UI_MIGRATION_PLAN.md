# Qt Quick Production UI Migration — Agent Handoff

## Mission

Replace the Tkinter/ttkbootstrap presentation layer with a production-quality Windows desktop interface built with PySide6 and Qt Quick/QML. Preserve the existing, tested Python machine-control behavior and redesign the user experience around the visual hierarchy and workflow clarity of Bambu Studio, using blue accents instead of green.

This is an incremental presentation-layer migration, not a rewrite of the GRBL controller. The existing application must remain usable until the Qt implementation reaches verified feature parity.

## Non-negotiable product requirements

- Remain a native desktop application. Do not move the controller to Streamlit or the system browser.
- Use PySide6 and Qt Quick/QML for the new presentation layer.
- Preserve the current Python GRBL protocol, serial/TCP connection, Wi-Fi discovery/setup, G-code validation, machine-envelope safety, job streaming, text generation, plaque generation, profile storage, and commissioning logic.
- QML must never construct or send GRBL commands directly. All machine actions must pass through tested Python application services.
- Never weaken a motion, spindle, bounds, reference, work-zero, or job-start safety check to simplify UI integration.
- Preserve USB and raw Wi-Fi TCP operation.
- Preserve the existing Tkinter launcher as a fallback until the completion gate explicitly permits its removal.
- Routine feedback must be non-modal. Use inline validation, disabled-state explanations, status banners, and toasts. Retain confirmations for actions with physical consequences.
- Work zero and the virtual machine reference must remain visually and semantically distinct.
- Without trusted homing, persisted coordinates must never silently become trusted after startup, reset, disconnect, or loss of machine-position certainty.
- All movement-to-position operations must retain safe-Z sequencing and use the configured jog feed.
- The physical emergency stop or power removal remains outside software control and must be clearly communicated.

## Verified current capability baseline

The existing codebase includes:

- USB serial and raw Wi-Fi TCP connections
- Wi-Fi discovery and station-mode setup
- Live GRBL status, machine coordinates, work coordinates, virtual coordinates, feed, spindle, and input pins
- Guarded incremental jogging and numeric coordinate moves
- Machine profile storage with X/Y/Z travel and safe Z
- Session-trusted virtual machine reference and virtual travel envelope
- GRBL work-zero controls and confirmed work-offset tracking
- Return to virtual reference and return to work zero through safe Z
- Metric G-code parsing, validation, bounds analysis, and XY toolpath preview
- Acknowledgement-driven job streaming
- Start, pause, resume, abort, spindle start, and spindle stop controls
- Post-job spindle stop and guarded return to work zero
- Text engraving generator with multiple centerline fonts and live preview
- Plaque builder with title, optional subtitle, border styles, and live preview
- Guided manual setup workflow
- Switch/probe commissioning workflow
- Persistent connection settings, machine profile, and commissioning state
- Automated unit tests for protocol, safety geometry, connections, generators, parsing, and streaming

Before starting a migration phase, inspect the current implementation and tests. Do not rely solely on this summary when behavior is safety-relevant.

## Chosen technology stack

### Required

- `PySide6`: Qt 6 Python bindings
- `QtQuick` and QML: GPU-rendered presentation layer
- `QtQuick.Controls`: interactive controls
- `QtQuick.Layouts`: responsive desktop layouts
- `QtQuick.Shapes`: initial toolpath and overlay rendering
- Qt signals, slots, models, timers, and worker threads for Python/QML communication
- Existing `pyserial` transport implementation
- Existing `pytest` suite
- `pytest-qt` for Qt-facing tests
- `pyside6-deploy` or a verified Nuitka configuration for Windows packaging

### Design-system strategy

Start from Qt Quick Controls Basic with project-owned QML components and tokens. Do not depend on the operating system's native widget appearance. Material may be used as a behavioral reference or fallback during prototyping, but the shipped application should use a controlled, application-specific visual system.

Use bundled SVG icons with a consistent stroke weight. Do not use emoji or platform-dependent glyphs as production icons.

### Do not introduce without demonstrated need

- Electron
- Tauri
- Streamlit
- A browser-based local server
- A JavaScript machine-control layer
- A second G-code parser or streamer
- `qasync` when Qt signals, timers, and worker threads already solve the integration
- OpenGL or custom scene-graph rendering before Qt Quick Shapes is profiled with representative large jobs

## Model routing for implementation agents

The user requested GPT-5.6 SOL light and GPT-5.6 Terra light. The supported reasoning-effort name is `low`, so use the following exact configurations:

- **GPT-5.6 SOL, low reasoning** (`gpt-5.6-sol`, `reasoning.effort: low`)
- **GPT-5.6 Terra, low reasoning** (`gpt-5.6-terra`, `reasoning.effort: low`)

### Assign GPT-5.6 SOL low to

- Cross-cutting architecture decisions
- Safety-boundary extraction and review
- State-machine design
- Python/QML ownership boundaries
- Threading and lifecycle review
- Toolpath-renderer architecture and performance decisions
- Final review of motion, spindle, reset, disconnect, and reference behavior
- Resolving failures that span multiple subsystems
- Phase completion audits and deletion of the legacy UI

### Assign GPT-5.6 Terra low to

- Bounded Python service extraction with existing tests
- QML components and design tokens
- Individual workspace implementation
- View-model properties, signals, and slots
- Forms, inspectors, dialogs, drawers, toasts, and banners
- Unit and integration tests with explicit acceptance criteria
- Documentation, packaging scripts, and mechanical dependency changes
- Isolated bug fixes whose safety contract is already defined

### Coordination rules

- One agent owns a file or tightly coupled file group at a time.
- Parallel work is allowed only when file ownership and interfaces are already defined.
- A SOL low agent defines or approves a cross-subsystem interface before multiple Terra low agents implement against it.
- Every agent must read this document, the relevant existing source files, and the relevant tests before editing.
- Every agent must preserve unrelated working-tree changes.
- Agents must use `apply_patch` for hand-authored edits.
- Agents must run focused tests after each bounded change and the complete suite before declaring a phase complete.
- No agent may operate the physical machine merely to validate UI wiring unless the user explicitly requests that physical test.
- Do not create development-effort estimates. Report scope, dependencies, progress, test evidence, and blockers instead.

## Target information architecture

Use a persistent application shell with five top-level modes:

1. **Prepare**
2. **Preview & Run**
3. **Machine**
4. **Guided Setup**
5. **Commissioning**

The shell must retain a compact global status area containing:

- Connection state and active transport
- GRBL state
- Machine-reference trust
- Work-zero confirmation
- Spindle state
- Current machine/work coordinates or a compact coordinate summary
- Connection/disconnection action
- Alarm or safety banner when required

The global shell must not become a second control panel. Contextual actions belong in the active workspace.

## Visual direction

### Palette

- Application background: `#181A1F`
- Primary workspace surface: `#22252B`
- Raised surface: `#2B2F36`
- Hover surface: `#343941`
- Primary accent: `#168BFF`
- Accent hover/selection: `#3B9EFF`
- Primary text: `#F2F4F7`
- Secondary text: `#A8AFBA`
- Subtle/divider text: `#737B87`
- Success/trusted: restrained cyan-blue or neutral success tone; do not compete with the primary action
- Warning: amber
- Alarm, abort, hazardous action: red

### Layout principles

- Use one dominant workspace or canvas, not a grid of equally weighted group boxes.
- Use a stable contextual inspector width.
- Prefer spacing, typography, subtle surface contrast, and separators over visible borders.
- Use rounded corners consistently and sparingly.
- Keep primary actions in predictable locations.
- Keep machine state visible without consuming excessive vertical space.
- Hide advanced or infrequent controls in drawers, tabs, or expandable sections.
- The console is a collapsible bottom drawer, not a permanent peer of the preview.
- Support high-DPI scaling and a practical minimum desktop resolution.
- Animation must communicate state transitions and remain short. Never delay or obscure a safety state.

### Interaction principles

- Explain disabled controls inline or through a tooltip/status reason.
- Ignore unavailable jog commands without modal dialogs, consistent with current behavior.
- Use modal confirmation only for hazardous or irreversible actions such as spindle start, job start, abort/reset, commissioning writes, homing, or downward movement requiring explicit approval.
- Validation belongs beside the affected input and in a concise summary area.
- Maintain visible distinction between disconnected, connected-but-not-idle, idle-but-unreferenced, referenced-but-no-work-zero, and ready-to-run states.

## Workspace specifications

### 1. Prepare

Purpose: create or load a job and edit its parameters.

Layout:

- Left source rail: Load G-code, Text, Plaque, Recent Jobs
- Center: large toolpath/design canvas
- Right: contextual inspector for the selected source
- Bottom-right primary action: Generate & Preview or Review Loaded Job

Canvas overlays:

- Machine travel envelope
- Virtual machine origin
- Work origin
- Current tool position when connected
- Rapid and cutting paths
- Job bounds and dimensions
- Unsafe or out-of-envelope regions
- Zoom, pan, fit, reset, and top-view controls

Text and plaque creation must be integrated inspector modes rather than separate top-level windows. Changes update the preview in real time. Generated G-code must continue through the existing parser, bounds checks, and job-loading path.

### 2. Preview & Run

Purpose: review a validated job, complete preflight, and operate an engraving run.

Layout:

- Center: dominant toolpath canvas
- Right: job summary and preflight inspector
- Bottom: progress/action bar
- Collapsible bottom drawer: detailed console log

Required information:

- File or generated-job name
- Program dimensions and XYZ bounds
- Work-zero placement
- Envelope-fit result
- Safe Z, cut depth, feed information when available
- Whether the job starts the spindle
- Current spindle state
- Machine/reference/work-zero readiness
- Explicit physical preflight acknowledgements

Required actions:

- Start job
- Pause
- Resume
- Abort
- Start/stop spindle when separately controlled
- Return to work zero through safe Z when manually requested

The execution UI must show progress, active state, and completion/failure outcomes without requiring the console.

### 3. Machine

Purpose: connect, inspect, reference, zero, and position the CNC.

Layout:

- Left secondary navigation: Status, Connection, Profile, Coordinates, Console
- Center: simplified top-down machine-envelope visualization
- Right: cohesive jog and positioning panel

Jog panel:

- X/Y directional pad
- Z up/down control
- Step-distance selector
- Jog-feed selector
- Numeric virtual-coordinate target
- Move-to action
- Retract to safe Z
- Return to virtual reference
- Return to work zero through safe Z
- Establish virtual machine reference
- Set individual or XYZ work zero
- Feed hold, resume, and jog cancel where contextually appropriate

The machine view must display current position, virtual reference, work zero, loaded-job bounds, and limit/envelope relationships. Every move retains the existing validation and safe sequencing.

### 4. Guided Setup

Purpose: lead a user through the complete switchless setup and engraving workflow.

Use an integrated workspace with a vertical progress rail:

1. Safety and operating assumptions
2. Connect
3. Verify/save machine profile
4. Establish virtual machine reference
5. Set work zero
6. Create or load a job
7. Review toolpath and envelope fit
8. Complete physical preflight
9. Run and monitor the job

The center explains the current step and why it matters. The contextual panel exposes only the controls required for that step. Advancement remains gated by current verified state.

### 5. Commissioning

Purpose: commission optional switches, homing, limits, and probe hardware.

Preserve the existing ordered and gated flow:

- Input press/release tests
- Positive-direction confirmation
- Read and review GRBL settings
- Apply input polarity
- Configure first-homing settings
- Run separately confirmed first homing cycle
- Confirm successful homing
- Enable protections separately
- Record probe geometry and electrical readiness

Opening the workspace must never send commands. All settings writes and motion remain explicit, reviewed actions.

## Target software architecture

```text
src/ttc3018_control/
├── domain/
│   ├── grbl.py
│   ├── gcode.py
│   ├── machine_state.py
│   ├── job.py
│   ├── text_engraver.py
│   ├── plaque_engraver.py
│   └── commissioning.py
├── infrastructure/
│   ├── serial_connection.py
│   ├── tcp_connection.py
│   ├── wifi_discovery.py
│   ├── wifi_setup.py
│   └── stores.py
├── application/
│   ├── machine_session.py
│   ├── connection_manager.py
│   ├── motion_controller.py
│   ├── job_controller.py
│   ├── generator_controller.py
│   ├── commissioning_controller.py
│   └── notifications.py
├── qt/
│   ├── main.py
│   ├── bridge/
│   ├── models/
│   ├── resources/
│   └── qml/
│       ├── Main.qml
│       ├── design/
│       ├── components/
│       └── workspaces/
└── legacy_tk/
    └── ...
```

This is a target structure, not permission for a disruptive bulk move. Refactor incrementally, keep imports reviewable, and avoid mixing architecture relocation with behavior changes.

### Application-service boundary

Create Python services that expose intention-level operations, for example:

- `connect(settings)` / `disconnect()`
- `jog(axis, distance, feed)`
- `move_to_virtual(target, feed)`
- `retract_safe_z(feed)`
- `establish_reference()`
- `set_work_zero(axes)`
- `return_to_reference(feed)`
- `return_to_work_zero(feed)`
- `load_program(path)`
- `load_generated_program(text, source)`
- `start_job(preflight)`
- `pause_job()` / `resume_job()` / `abort_job()`
- `start_spindle(rpm)` / `stop_spindle()`

Each operation returns or emits structured outcomes suitable for status banners and logs. Avoid UI-formatted strings as the only representation of state.

### Qt bridge rules

- Use `QObject` properties and notify signals for stable application state.
- Use `QAbstractListModel` or purpose-built models for logs, program lines, validation issues, recent jobs, and toolpath data.
- Cross a worker-thread boundary only through queued Qt signals/slots or another explicitly thread-safe mechanism.
- QML calls slots representing user intentions; it does not access serial/TCP objects.
- Throttle high-frequency position updates to a visually useful rate without reducing controller polling or safety-state freshness.
- No blocking serial, TCP, discovery, file, or packaging work on the Qt GUI thread.

## Implementation phases and gates

### Phase 0 — Baseline and guardrails

Tasks:

- Run the complete existing test suite and record the baseline.
- Identify current UI-dependent business logic in `app.py` and popup classes.
- Add characterization tests where safety behavior lacks direct coverage.
- Define immutable command/result types and shared state enums.
- Add a Qt migration feature flag or separate launcher.

Gate:

- Existing launcher works.
- Existing tests pass.
- Safety-critical behavior has explicit test ownership.
- No Qt UI sends machine commands.

### Phase 1 — Extract application services

Tasks:

- Extract machine/session state from Tk variables.
- Extract connection orchestration.
- Extract motion and reference/work-zero actions.
- Extract job loading, validation, streaming, and lifecycle orchestration.
- Extract notification outcomes from messagebox/status-string behavior.
- Keep Tkinter as a consumer of the new services where practical.

Gate:

- Services can be tested without constructing a Tk root.
- Tkinter still supports the current workflow.
- All existing tests and new service tests pass.

### Phase 2 — Qt shell and design system

Tasks:

- Add the PySide6 entry point and dependency.
- Implement design tokens, typography, icons, buttons, inputs, cards, tabs, tooltips, banners, toasts, dialogs, drawers, and focus states.
- Build the five-mode application shell.
- Build compact global status and connection presentation.
- Add static workspace compositions using representative data.
- Establish minimum-window and high-DPI behavior.

Gate:

- Shell launches independently of Tkinter.
- All workspaces are navigable.
- Layout remains usable at the defined minimum size and common high-DPI settings.
- No machine commands are exposed yet except through deliberately wired services.

### Phase 3 — Live state and connection

Tasks:

- Implement Qt bridge/view models for connection and machine state.
- Wire serial/TCP events to Qt safely.
- Implement centered connection dialog, USB selection, Wi-Fi host/port, discovery progress, connect, and disconnect.
- Display GRBL state, positions, spindle, feed, pins, reference trust, and work-zero confirmation.
- Implement alarms, status banners, and routine toasts.

Gate:

- USB and Wi-Fi behavior matches the legacy UI.
- Connect/disconnect/error paths never freeze the UI.
- Disconnect and reset invalidate trust exactly as the existing safety model requires.
- Relevant automated tests pass.

### Phase 4 — Machine workspace controls

Tasks:

- Implement jog pad, Z controls, step, and feed.
- Implement numeric virtual-coordinate moves.
- Implement safe-Z, reference, work-zero, and return controls.
- Implement hold, resume, jog cancel, and reset presentation.
- Add disabled-state reasons and non-modal ignored-command feedback.
- Add keyboard jogging only after focus and repeat behavior are explicitly designed and tested.

Gate:

- Every motion action routes through existing or extracted safety checks.
- Out-of-envelope input cannot be submitted.
- Safe-Z movement order and configured jog feed are preserved.
- Controlled abort/reference behavior matches current requirements.
- Automated tests pass before any optional low-speed physical acceptance test.

### Phase 5 — Toolpath canvas

Tasks:

- Render rapid/cutting segments and arcs.
- Add zoom, pan, fit, reset, grid, rulers, bounds, dimensions, origins, and current tool position.
- Render machine envelope and unsafe/out-of-bounds conditions.
- Add selection/hover only where it improves understanding.
- Profile representative small and large G-code programs.
- Introduce a custom `QQuickItem`/scene-graph renderer only if measured performance requires it.

Gate:

- Preview geometry agrees with parser bounds.
- The canvas remains responsive with representative jobs.
- Rendering cannot alter the validated program or machine state.
- Visual regression or screenshot tests cover major states.

### Phase 6 — Prepare and Preview & Run

Tasks:

- Implement file loading and recent-job presentation.
- Implement validation summaries and envelope-fit display.
- Implement preflight checklist and readiness gating.
- Implement spindle controls and job start/pause/resume/abort.
- Implement progress and completion/failure states.
- Move the console into a collapsible drawer.
- Preserve guarded post-job return to work zero.

Gate:

- Imported jobs pass through the existing parser and validation path.
- A job cannot start without the same trusted state and confirmations as the legacy UI.
- Pause/resume/abort and post-job behavior match tested controller behavior.
- Full automated suite passes.

### Phase 7 — Text and plaque creators

Tasks:

- Integrate text engraving into the Prepare inspector.
- Integrate plaque creation into the Prepare inspector.
- Provide live canvas updates for all supported controls.
- Add visual font and border selectors.
- Display physical dimensions and collision/bounds problems inline.
- Preserve optional subtitle behavior and centered title behavior.
- Preserve optional spindle-start output.
- Continue loading generated G-code through the shared validation pipeline.

Gate:

- Existing generator tests pass unchanged or with justified interface-only updates.
- Preview and generated toolpath use the same geometry.
- Invalid or interfering geometry cannot be loaded as a runnable job.

### Phase 8 — Guided Setup and Commissioning

Tasks:

- Port the setup wizard into the integrated Guided Setup workspace.
- Port commissioning into its integrated workspace.
- Preserve all gates, explanations, confirmation boundaries, and saved progress.
- Add clear recovery guidance for failed prerequisites.

Gate:

- The complete switchless workflow can be completed without opening legacy windows.
- Merely opening commissioning sends no commands.
- Homing, settings writes, and protection enabling retain separate confirmations.
- Existing commissioning tests and new Qt integration tests pass.

### Phase 9 — Production hardening and legacy removal

Tasks:

- Add production packaging and a clean-machine installation test.
- Add application metadata, version display, icons, and crash/error logging.
- Verify settings migration from the existing application.
- Test high-DPI, resizing, keyboard navigation, contrast, and screen-reader labels where practical.
- Exercise disconnect, Wi-Fi loss, alarm, reset, malformed G-code, failed streaming, abort, and shutdown paths.
- Update README and operating documentation.
- Make Qt the default launcher.
- Remove Tkinter/ttkbootstrap only after every gate below is satisfied.

Final gate:

- Feature-parity matrix is complete.
- Full automated suite passes.
- Packaged Windows build launches without a development environment.
- USB and Wi-Fi connection acceptance checks pass.
- Safety-state transitions have been reviewed by GPT-5.6 SOL low.
- User has accepted the production UI workflow.
- Legacy UI removal is a separate, reviewable commit.

## Testing strategy

### Preserve and expand unit tests

- GRBL parsing and command generation
- Machine-envelope calculations
- Work-zero target calculations
- Safe movement planning and feed selection
- G-code parser and bounds
- Job streamer acknowledgement behavior
- Text and plaque generation
- Connection settings and discovery
- Commissioning prerequisites

### Add application-service tests

- State transitions for connect, disconnect, reset, alarm, abort, and completion
- Reference/work-zero trust lifecycle
- Command rejection reasons
- Job readiness calculation
- Notification severity and user-action requirements
- Worker lifecycle and shutdown

### Add Qt tests

- View-model property/signal behavior
- Control enablement for all machine states
- Workspace navigation
- Inline validation
- Dialog confirmation boundaries
- Generator inspector behavior
- Job progress states
- QML loading and missing-resource detection
- Screenshot checks for representative layouts and alarms

### Physical acceptance boundaries

Automated agents must not independently run the CNC. When the user requests physical acceptance testing, use conservative speeds and test one behavior at a time with the spindle off before any cutting test. Record the observed machine state and result for every test.

## Feature-parity checklist

- [ ] USB connection
- [ ] Wi-Fi TCP connection
- [ ] Wi-Fi discovery
- [ ] Wi-Fi station setup
- [ ] Connection persistence
- [ ] Live GRBL state
- [ ] Machine/work/virtual coordinates
- [ ] Feed, spindle, and pin display
- [ ] Incremental jogging
- [ ] Numeric move-to
- [ ] Configured jog feed for position returns
- [ ] Virtual envelope enforcement
- [ ] Machine profile editing
- [ ] Virtual reference establishment/invalidation
- [ ] Work-zero controls and confirmation
- [ ] Safe-Z retract
- [ ] Return to virtual reference
- [ ] Return to work zero
- [ ] G-code load/validation
- [ ] Bounds and fit checks
- [ ] Toolpath preview
- [ ] Text generator
- [ ] Plaque generator
- [ ] Spindle start/stop
- [ ] Job start/pause/resume/abort
- [ ] Job progress
- [ ] Post-job return to work zero
- [ ] Guided Setup
- [ ] Commissioning
- [ ] Console/logging
- [ ] Settings/profile migration
- [ ] Windows packaging

## Agent completion report format

Every implementation agent must report:

1. Scope completed
2. Files changed
3. Safety behavior affected or explicitly unaffected
4. Tests run and exact results
5. Visual verification performed
6. Remaining phase work
7. Blockers or decisions requiring user input

Do not report development-time estimates. Do not claim physical-machine verification unless it was explicitly requested and actually observed.

## Definition of success

The migration is complete when the Qt application provides the entire current workflow with a cohesive Bambu-Studio-inspired dark desktop interface, restrained blue accents, a dominant toolpath workspace, contextual controls, clear safety state, and no dependency on Tkinter—while preserving or strengthening every tested machine-safety guarantee.
