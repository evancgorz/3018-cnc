# Application Architecture Refactor — Agent Handoff

## Implementation status

Implemented on branch `codex/qt-quick-ui` through the application composition,
connection, motion, job, generation, immutable-state, Qt Quick file-dialog,
typed-confirmation, deferred-commissioning removal, response-routing, and
held-jog regression work. Remaining work is optional hardening of the contract
matrix and event-sink coverage.

## Shipped checklist

- [x] Qt-independent application state, events, ports, and machine session.
- [x] Single-owner USB/Wi-Fi connection service with stale-attempt handling.
- [x] Guarded incremental, positional, live, reference, and work-zero motion.
- [x] Acknowledgement-driven job lifecycle with spindle-stop/Idle completion.
- [x] Text, plaque, and STEP generation through the shared validation pipeline.
- [x] Explicit Qt Quick composition root and injected `ApplicationController`.
- [x] QML file dialogs and centered typed confirmation handoff; no Qt Widgets
      dialogs remain in the production Qt shell.
- [x] Deferred commissioning removed from the active Qt workflow.
- [x] Held-jog state remains enabled across GRBL `Idle` → `Jog` transitions,
      with whole-millimeter release correction preserved.
- [x] README and architecture decision record updated.
- [x] 120 automated tests and the offscreen Qt shell check pass.
- [x] Incremental commits are pushed to `origin/codex/qt-quick-ui`.

Follow-up hardening can expand the application-controller contract matrix and
event-sink integration, but it is not required to use the migrated production
Qt shell.

## Mission

Refactor TTC 3018 Control into a clean modular-monolith architecture while
preserving its existing Qt Quick desktop experience and every machine-safety
behavior. The application should remain one desktop process for normal use,
but its presentation, application orchestration, domain rules, and hardware
adapters must have explicit boundaries.

This is an internal architecture refactor, not a UI redesign and not a move to
an HTTP service. The resulting application layer must be independent enough
that another adapter, such as a CLI or local API, could be added later without
moving safety logic or rewriting machine workflows.

## Required architectural decision

Use a **modular monolith** as the production architecture:

```text
Qt Quick/QML presentation
          |
Thin Qt view-model adapter
          |
Python application controller and use cases
          |
Domain safety, parsing, generation, and job rules
          |
USB, TCP, filesystem, and native-library adapters
```

- Keep the GUI and application controller in one operating-system process.
- Keep STEP/OpenCASCADE importing in its existing isolated child process.
- Do not introduce FastAPI, Flask, HTTP, WebSockets, OpenAPI, gRPC, a daemon,
  or another network-facing control surface in this refactor.
- Do not make QML aware of serial, TCP, GRBL command strings, G-code parser
  objects, storage paths, or worker threads.
- Treat a future API as an optional adapter around the same application
  controller, never as the location of safety or motion rules.

## Agent operating constraints

- Read and obey `AGENTS.md` before making changes.
- If TTC 3018 Control is running, do not terminate, restart, activate, focus,
  resize, or interact with it.
- Do not relaunch the application after source changes. Use unit tests and the
  supported offscreen shell check; tell the user a manual relaunch is required.
- Preserve unrelated working-tree changes.
- Use `apply_patch` for source and documentation edits.
- Commit and push after each completed phase. Use small commits whose messages
  identify the extracted boundary or behavior.
- Never weaken a safety check to simplify the refactor.

## Current architecture to verify before editing

The current production entry point is `run.py`. `qt/main.py` creates a
`QGuiApplication`, loads `qt/qml/Main.qml`, creates `ControllerViewModel`, and
registers it as the QML context property `appViewModel`.

`ControllerViewModel` is presently both the Qt adapter and much of the
application coordinator. It directly owns or coordinates:

- `MachineSession`
- USB `GrblConnection` and Wi-Fi `TcpGrblConnection`
- `JobStreamer`
- polling and incoming serial/TCP events
- machine reference and work-zero workflows
- incremental, positional, and live jogging
- profile and connection-setting persistence
- G-code loading, validation, preview, and job lifecycle
- Wi-Fi discovery and controller provisioning
- text, plaque, and STEP generation
- STEP model selection and preview state
- user notices and several confirmation dialogs

Before moving any behavior, inspect the current implementation and tests. This
summary is a routing aid, not an authoritative replacement for the code.

## Non-negotiable safety invariants

Every phase must preserve all of the following:

- Exactly one object owns the active machine transport and command stream.
- USB and Wi-Fi remain mutually exclusive connection transports.
- QML never creates, modifies, or sends a GRBL command.
- Motion is rejected unless the required GRBL state and position are fresh.
- The virtual machine reference and GRBL work zero remain separate concepts.
- A virtual reference is never silently trusted after a disconnect, reset, or
  loss of physical-position certainty.
- Persisted work-zero data does not become trusted without the session evidence
  required by the existing behavior.
- Virtual-envelope checks remain authoritative for all automatic movement.
- Position moves retain safe-Z ordering and configured jog feed.
- Return to reference and return to work zero retain their current final Z
  behavior and validation.
- Job completion stops the spindle, waits for acknowledgement and `Idle`, then
  performs only the currently permitted guarded return workflow.
- Job streaming remains acknowledgement-driven and bounded by GRBL capacity.
- Pause, resume, abort, reset, and close behavior retain current semantics.
- Live-jog release retains its captured whole-millimeter stopping target and
  correction behavior.
- Generated and loaded G-code always pass through the shared parser, validation,
  bounds, preview, preflight, and streaming pipeline.
- Physical confirmations remain required where the current application asks
  the user to authorize motion, spindle, homing, reset, or destructive setup.
- A UI exception must not bypass application-layer validation.

## Target responsibilities

### QML presentation

QML owns only visual state and interaction details:

- layout, focus, formatting, controls, dialogs, and toasts
- collecting typed user input
- invoking intention-level view-model slots
- rendering properties and models exposed by the view model

QML must not infer whether a motion is safe. Button enablement is advisory; the
application layer must validate every command again when invoked.

### Qt view-model adapter

`ControllerViewModel` should become a thin `QObject` adapter that:

- converts QML values and `QUrl` objects into ordinary Python values
- forwards intention-level calls to `ApplicationController`
- exposes display-ready properties and collection models
- converts application state/events into Qt property notifications and signals
- owns only Qt-specific timers, file-dialog integration, and presentation
  confirmation handoffs
- contains no GRBL command construction, envelope calculations, streaming state
  machine, transport selection logic, or persistence implementation

### Application controller

Add a Qt-independent `ApplicationController` as the single orchestration entry
point. It should:

- own the current application state and active operation lifecycle
- coordinate connection, motion, reference, work-zero, job, and generation use
  cases
- expose intention-level methods rather than raw GRBL access
- return structured outcomes instead of invoking UI dialogs
- publish immutable state snapshots and typed application events
- enforce single-control ownership and reject overlapping operations
- depend on protocols/interfaces for transports, clocks, and stores
- remain testable without a `QGuiApplication`

Representative methods may include:

```python
connect_usb(port: str) -> ActionOutcome
connect_wifi(host: str, port: int) -> ActionOutcome
disconnect() -> ActionOutcome
poll(now: float) -> tuple[ApplicationEvent, ...]
establish_reference() -> ActionOutcome
set_work_zero(axes: str) -> ActionOutcome
jog(axis: str, distance_mm: float, feed_mm_min: float) -> ActionOutcome
start_live_jog(axis: str, direction: float, feed_mm_min: float) -> ActionOutcome
stop_live_jog() -> ActionOutcome
move_to(target: Position, feed_mm_min: float) -> ActionOutcome
return_to_reference() -> ActionOutcome
return_to_work_zero() -> ActionOutcome
load_program(path: Path) -> ActionOutcome
start_job() -> ActionOutcome
pause_job() -> ActionOutcome
resume_job() -> ActionOutcome
abort_job() -> ActionOutcome
```

The exact signatures may differ when current behavior requires more context.
Do not force all operations into one generic command method.

### Domain modules

Keep or strengthen plain Python modules for deterministic rules:

- GRBL parsing and command formatting
- machine session and trust state
- virtual envelope and motion planning
- G-code parsing and bounds
- job-stream accounting
- text, plaque, and STEP toolpath generation
- connection and machine profile value objects

Domain modules must not import PySide6, QML types, dialogs, or concrete transport
classes.

### Infrastructure adapters

Concrete adapters own side effects:

- USB serial transport
- raw Wi-Fi TCP transport
- filesystem-backed profile and connection stores
- Wi-Fi discovery and provisioning
- isolated OpenCASCADE STEP worker

Use small `Protocol` definitions or abstract interfaces at the application
boundary. Do not rewrite stable adapters merely to rename them.

## Proposed module layout

Use this as the preferred destination, adapting names only when the existing
code makes a different split substantially clearer:

```text
src/ttc3018_control/
  application/
    controller.py          # Composition and intention-level public API
    state.py               # Immutable ApplicationState snapshots
    events.py              # Typed, UI-neutral events
    ports.py               # Transport/store/clock Protocol definitions
    machine_session.py     # Existing machine trust and safety service
    connection_service.py  # USB/TCP lifecycle and incoming event routing
    motion_service.py      # Jog, live jog, references, and position sequences
    job_service.py         # Program lifecycle, streaming, and post-job return
    generation_service.py  # Text/plaque/STEP orchestration into shared pipeline
  qt/
    main.py
    view_model.py          # Thin Qt adapter only
    qml/
  serial_connection.py     # Existing concrete adapter; relocation optional
  tcp_connection.py        # Existing concrete adapter; relocation optional
  ...existing domain modules...
```

Avoid creating empty wrappers. A service should be extracted only when it owns
a coherent state machine or use-case family.

## State and event model

Introduce an immutable `ApplicationState` dataclass containing authoritative,
UI-neutral values. Prefer actual numeric positions and enums over preformatted
strings. Include only fields required by current workflows, such as:

- connection mode and connection status
- GRBL state and freshness
- machine, work, and virtual positions
- reference trust and work-zero confirmation
- profile and safe-Z information
- active motion or live-jog status
- loaded program metadata and bounds
- job status and progress
- spindle/feed/pin state
- available ports and saved Wi-Fi endpoint
- current STEP model metadata

Add typed `ApplicationEvent` values for transient occurrences:

- notice or validation failure
- confirmation request
- connection failure
- log entry
- file-operation result
- request to close after a completed return move

Do not use event strings as a hidden command protocol. Events should have typed
fields or distinct dataclasses/enums. The Qt adapter decides how an event is
presented.

## Confirmation model

Physical-action confirmation must remain in the presentation layer without
putting safety decisions there.

Use a two-step pattern:

1. The application controller validates the proposed operation and emits or
   returns a typed confirmation request containing a stable operation token.
2. The Qt adapter displays the confirmation and calls `confirm(token)` or
   `reject(token)`.
3. The application controller revalidates current machine state before sending
   anything. A stale token must be rejected.

Do not pass executable callbacks, GRBL strings, or arbitrary Python objects into
QML as confirmation payloads.

## Phased implementation plan

### Phase 0 — Baseline and characterization

- [ ] Read `AGENTS.md`, current launch documentation, `ControllerViewModel`,
  `MachineSession`, both transports, `JobStreamer`, and all relevant tests.
- [ ] Record the current test count and run `python run.py --check` with the
  project virtual environment.
- [ ] Add characterization tests for behavior that is currently implemented in
  the view model but not covered below it.
- [ ] Prioritize connection lifecycle, event polling, live-jog release,
  reference invalidation, job completion, post-job return, and abort behavior.
- [ ] Confirm no production behavior changes in this phase.
- [ ] Commit and push: `Characterize application controller behavior`.

Gate: all existing tests and new characterization tests pass before extraction.

### Phase 1 — Contracts, state, and dependency seams

- [ ] Add `application/state.py` with immutable state dataclasses and enums.
- [ ] Add `application/events.py` with typed UI-neutral events.
- [ ] Add `application/ports.py` with minimal protocols for transport, stores,
  and clock/time access where deterministic tests need them.
- [ ] Adapt existing concrete classes structurally; avoid unnecessary base-class
  inheritance.
- [ ] Add fake transports and in-memory stores under tests.
- [ ] Prove domain and application modules do not import PySide6.
- [ ] Commit and push: `Add application state and port contracts`.

Gate: contracts are covered by tests and no runtime wiring has changed.

### Phase 2 — Extract connection lifecycle

- [ ] Extract USB/TCP selection, connect, disconnect, status polling, connection
  errors, Wi-Fi discovery results, and transport event routing.
- [ ] Guarantee only one active transport and one command writer.
- [ ] Preserve stored Wi-Fi settings and USB-assisted Wi-Fi configuration.
- [ ] Preserve reference/work-zero invalidation rules on disconnect and reset.
- [ ] Make connection behavior testable with fake transports and no Qt loop.
- [ ] Keep current QML properties and actions functioning through adapter
  delegation.
- [ ] Commit and push: `Extract connection application service`.

Gate: connection, TCP, Wi-Fi discovery/setup, and Qt shell tests pass.

### Phase 3 — Extract motion and reference workflows

- [ ] Move incremental jog, positional jog, live jog, jog cancel, stop-target
  capture, nearest-whole-millimeter correction, and ordered position queues into
  a Qt-independent motion service.
- [ ] Move establish-reference, set-work-zero, return-to-reference, and
  return-to-work-zero orchestration into the application layer.
- [ ] Keep `MachineSession` and virtual-envelope functions authoritative for
  trust and bounds decisions.
- [ ] Use the current configured jog feed for every generated jog sequence.
- [ ] Add deterministic tests for acknowledgement ordering and stale status.
- [ ] Commit and push: `Extract guarded motion workflows`.

Gate: all motion tests pass, including edge-of-envelope and live-jog release.

### Phase 4 — Extract program and job lifecycle

- [ ] Move program loading, parsing, metadata, preview-source preparation,
  preflight, start, pause, resume, abort, and completion coordination into a job
  application service.
- [ ] Keep `JobStreamer` focused on acknowledgement-driven transmission.
- [ ] Preserve spindle acknowledgement, `Idle` wait, and guarded post-job return
  to work zero.
- [ ] Preserve skipped-return explanations when references, work offset, or
  envelope evidence are unavailable.
- [ ] Ensure close-during-job and close-after-return policies remain explicit.
- [ ] Add tests for transport loss, GRBL error, abort, reset, and application
  close at every job phase.
- [ ] Commit and push: `Extract job lifecycle service`.

Gate: no command can reach a transport without passing job/motion validation.

### Phase 5 — Extract generation orchestration

- [ ] Move text, plaque, and STEP generator orchestration out of the Qt adapter.
- [ ] Keep form-value conversion and file-dialog URLs in the Qt adapter.
- [ ] Return structured validation errors and preview data from the application
  layer.
- [ ] Preserve isolated STEP importing and selected-face behavior.
- [ ] Ensure generated G-code still enters the exact shared parser, bounds,
  preview, and job-loading pipeline.
- [ ] Commit and push: `Extract engraving generation workflows`.

Gate: text, plaque, STEP, parser, preview, and bounds tests pass unchanged or
with stronger coverage.

### Phase 6 — Thin the Qt view model

- [ ] Make `ControllerViewModel` depend on an injected `ApplicationController`.
- [ ] Replace direct transport, session, streamer, store, and generator imports
  with controller calls and state/event projection.
- [ ] Keep the public QML-facing property and slot surface stable unless a
  deliberate simplification is covered by QML and Qt tests.
- [ ] Keep QML free of machine-state inference and raw command construction.
- [x] Replace remaining `QtWidgets` dialogs used under `QGuiApplication` with
  Qt Quick dialogs and typed confirmation/event handoffs.
- [ ] Add an import-boundary test that fails if the Qt adapter directly imports
  concrete transports or job-stream implementation classes.
- [ ] Commit and push: `Reduce Qt view model to presentation adapter`.

Gate: the Qt adapter contains formatting and delegation, not machine workflow
state machines.

### Phase 7 — Composition, cleanup, and documentation

- [ ] Add one composition root that constructs stores, transport factories,
  services, `ApplicationController`, and `ControllerViewModel`.
- [ ] Keep `run.bat` and `run.py` as the only supported launch path.
- [ ] Remove superseded private view-model state only after behavior is migrated
  and tested.
- [ ] Remove dead commissioning/Tkinter presentation modules only if they are
  confirmed unused and outside any still-supported workflow; otherwise document
  them as deferred cleanup.
- [ ] Update README architecture and contributor guidance.
- [ ] Add a short architecture decision record explaining why the project uses
  a modular monolith and when a separate process/API would be justified.
- [ ] Run the complete verification matrix and inspect `git diff --check`.
- [ ] Commit and push: `Complete modular application architecture`.

Gate: clean worktree, pushed branch, documentation matches actual code.

## Test strategy

### Unit tests

- Application controller with fake clock, transports, and stores
- Connection ownership and reconnect behavior
- Status freshness and command rejection
- Reference/work-zero transitions
- Incremental, positional, and live jogging
- Safe-Z sequencing
- Program loading and generated-program validation
- Job acknowledgement, pause, resume, abort, failure, and completion
- Post-job spindle stop and return-to-work-zero behavior
- Confirmation token expiration and revalidation
- State snapshot and event contents

### Contract tests

Run the same transport contract against USB and TCP adapters where practical:

- open/close lifecycle
- outgoing line and realtime-byte semantics
- incoming event normalization
- timeout/error normalization
- no writes after close

### Qt adapter tests

- QML shell loads offscreen with no warnings that indicate broken bindings.
- Existing properties update from an injected application state.
- Slots forward normalized values to the application controller.
- Typed application events produce the correct toast/dialog/signal behavior.
- File dialogs pass local paths without constructing Qt Widgets.
- QML cannot directly access transport or GRBL command objects.

### Regression commands

Use the project virtual environment. On Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe run.py --check
git diff --check
git status --short --branch
```

Do not start the interactive application as an agent verification step.

## Commit and review discipline

- Keep each phase behavior-preserving and independently revertible.
- Commit characterization tests before moving the behavior they protect.
- Do not combine formatting sweeps with architecture changes.
- Do not relocate every module at once.
- Push each completed phase so work is recoverable.
- In every handoff, report tests run, commit hash, pushed branch, remaining
  unchecked items, and whether a manual relaunch is required.

## Explicit non-goals

- Browser, Streamlit, Electron, or webview migration
- HTTP/OpenAPI service
- Remote machine control
- Multiple simultaneous controlling clients
- General-purpose 3D CAM
- Changes to GRBL firmware
- New homing switches, probes, or physical safety hardware
- UI visual redesign
- Replacing OpenCASCADE or the existing generators
- Changing machine travel defaults or feed behavior

## Future API/process split trigger criteria

Revisit a separate backend only if at least one concrete product requirement
appears:

- headless machine operation without the desktop GUI
- a second independently maintained frontend
- remote monitoring or control
- external automation integrations
- demonstrated need for GUI/backend crash isolation beyond isolated native
  workers

Before implementing that split, define single-client control leases,
authentication, local/network exposure, heartbeat behavior, orphaned-job
policy, emergency-stop semantics, version compatibility, event streaming, and
service installation/upgrades. Prefer local IPC over HTTP when process
isolation is the only requirement.

## Completion criteria

The refactor is complete only when:

- [ ] Production remains one Qt Quick desktop application with one launcher.
- [ ] `ControllerViewModel` is a thin Qt adapter over `ApplicationController`.
- [ ] Application and domain modules import no PySide6 symbols.
- [ ] QML contains no GRBL commands or machine-safety decisions.
- [ ] Exactly one component owns the active transport and command ordering.
- [ ] All current USB, Wi-Fi, motion, reference, work-zero, job, generator,
  preview, persistence, and close workflows remain available.
- [ ] Every listed safety invariant has regression coverage.
- [ ] STEP import remains isolated from the main process.
- [ ] No HTTP server or extra background daemon is required.
- [ ] Full tests and the offscreen Qt shell check pass.
- [ ] Documentation describes the architecture that actually shipped.
- [ ] All phase commits are pushed and the working tree is clean.
