# Execution Contract

## Objective

Convert Pine into a two-process application dedicated to the owner's Two Trees
TTC 3018. A persistent headless backend owns `ApplicationController`, polling,
the one hardware/simulation transport, state and safety gates. A disposable Qt
frontend connects through versioned local IPC and may restart without resetting
or disconnecting the backend. A Qt-free CLI connects to that same guarded API
for debugging. Remove generic multi-machine/hardware choices; retain only real
calibration and operational settings.

This is software implementation only. It does not physically commission limit
switches or an E-stop and authorizes no physical CNC access.

## Current State

- `ApplicationController` is Qt-independent and owns connection, motion,
  homing, probing, jobs, simulation and persistence.
- `ControllerViewModel` currently creates it, drains transport/simulation events,
  sends status polls from a Qt timer, and closes it when Qt exits. Thus GUI and
  controller lifetimes are coupled.
- `ApplicationState` exists but does not cover the entire QML surface; many
  ViewModel properties directly inspect application services.
- The generic catalog and `MachineSetupDialog.qml` expose profile selection,
  controller, per-axis switch/pin/end/polarity/hard-limit, and hypothetical
  accessories.
- User-owned dirty work includes completed NC X/Y/Z semantics with a prior 612
  test pass. Preserve all existing work and untracked configuration.

## Final State

### Runtime topology

```text
pine-backend (persistent, no Qt)
  BackendRuntime -> one ApplicationController -> one controller transport
  authenticated versioned server on 127.0.0.1:<ephemeral>
           ^                              ^
           |                              |
pine-cnc GUI (restartable)            pine-cli (headless)
```

- Add `pine-backend` and `pine-cli` project scripts; retain `pine-cnc` as GUI.
- Store atomically written backend discovery data under the supplied app root:
  schema/protocol version, PID, loopback address, random token and session ID.
  Only the owning backend removes it. Detect stale metadata through PID plus
  authenticated health, not PID alone.
- Bind only `127.0.0.1` on an ephemeral port. Authenticate every bounded request.
  Use versioned JSON over a small standard-library HTTP API or an equally
  testable loopback protocol.
- Extract a Qt-free `BackendRuntime` with deterministic `poll_once()` and a
  bounded loop. It owns the logic now in `ControllerViewModel._poll`: Wi-Fi and
  simulation polling, transport-event dispatch, GRBL status polling/timeouts,
  state snapshots and sequenced events.
- Required IPC operations: health/version, immutable full snapshot, sequenced
  event polling, typed action invocation, confirmation response and explicit
  safe backend shutdown.
- Use a validated action registry over public application operations. Cover
  top-level connection, reference/home, bounded jog/cancel/hold/resume, work
  zero, probe, spindle, job load/review/preflight/start/pause/resume/abort,
  simulation and disconnect actions needed by GUI/CLI. Never expose normal raw
  `send_line` or `send_realtime` through IPC.
- Backend survives GUI client close. Production GUI attaches to a compatible
  backend; when none exists it may spawn one exact owned backend and wait
  boundedly. GUI shutdown closes Qt/client resources only. Explicit backend
  shutdown is rejected during active work unless the existing safe abort/close
  route is explicitly invoked.
- A vanished backend puts GUI into a clear backend-unavailable state. Do not
  invent physical machine state. Reattachment requires a fresh full snapshot
  before enabling actions.
- Keep `build_engine(application=...)` as a test compatibility seam where
  practical, but production `main()` must use a backend client. An in-process
  client adapter may support deterministic tests.
- CLI minimum: `status`, `events`, `connect-usb`, `connect-wifi`, `disconnect`,
  `hold`, `resume`, `cancel-jog`, bounded `jog`, `home`, job status and
  `shutdown`; JSON mode, meaningful exit codes and clear motion warnings.

### Dedicated TTC 3018 model and UI

- Add one canonical versioned installed-hardware declaration in source: Two
  Trees TTC 3018; GRBL-compatible MKS DLC32; nominal travel 290/170/40 mm; safe
  Z 30 mm; one X/Y/Z limit input installed/planned; movable Z plate installed;
  12,000 RPM spindle; E-stop `installed_uncommissioned` until exact board/reset,
  power-removal and feedback topology is recorded.
- X/Y/Z connector labels are fixed, not arbitrary GPIO text. Preserve uniform
  NC/global `$5` semantics. Homing ends remain uncommissioned unless existing
  reliable facts identify them. Installed declarations must not automatically
  authorize physical homing/hard limits.
- Replace generic Machine Setup with a dedicated read-only Machine/Hardware
  status and commissioning surface. Remove profile/controller selectors, switch
  enable, pin, polarity, accessory and hypothetical fixture/tool-setter choices.
- Retain editable measured/calibration data: usable travel, safe Z, touch-plate
  thickness/feed/search/retract/tolerance, connection endpoint, and job/toolpath
  parameters. Safety changes invalidate dependent evidence as today.
- Migrate conservatively: never delete user catalog/config. Import compatible
  measured values; ignore contradictory capability declarations and show that
  recommissioning is needed.
- Update README/architecture docs for the fixed machine, backend/GUI/CLI
  lifecycle, local authentication, debugging usage and commissioning limits.

## Allowed Scope

- New `src/ttc3018_control/backend/` modules for runtime, protocol, dispatcher,
  server/client, discovery, snapshots and entry point; new CLI module/scripts.
- Focused changes to application controller/state/events and Qt main/ViewModel/
  QML needed for the split and dedicated UI.
- Machine configuration/dedicated-definition and conservative migration changes.
- Focused tests, docs and `.codex/sol-luna/EXECUTION_RESULT.md`.

## Protected Scope

- Every running TTC/Pine instance is user-owned. Do not terminate, restart,
  activate, focus, resize, capture or interact with it. Do not launch/relaunch
  the GUI. A manual relaunch will be required.
- Do not enumerate or access physical CNC hardware: no COM/USB/non-loopback
  connection, configuration, reset, home, jog, probe or stream. Tests inject
  forbidden factories and use temporary roots, fakes and loopback twins only.
- Do not modify user `config/*.json`, logs, screenshots, example jobs or the
  `%SystemDrive%/` tree. Never use the repository root for test persistence.
- Preserve dirty work. No destructive Git, cleanup, commits, pushes, dependency
  installation, firewall changes or broad listener.
- No raw-command console, unauthenticated API or weakened safety gates.
- Do not claim the reset header is safety-rated, power removal commissioned, or
  physical homing verified.

## Implementation Steps

1. Extract `BackendRuntime` from Qt polling/lifecycle behavior. Normalize
   controller/service data into immutable serializable snapshots and sequenced
   events. Test fake and loopback progression without Qt.
2. Add authenticated versioned loopback discovery/server/client with atomic
   ownership, stale detection, bounded payload/time, strict action validation
   and exact-owner cleanup. Test auth, malformed/oversized/version mismatch,
   stale discovery, multiple clients, and `127.0.0.1` binding.
3. Add the typed dispatcher and explicit confirmation flow. Contract tests must
   prove GUI/CLI adapters receive identical outcomes and never bypass transport.
4. Add backend and CLI entry points. Subprocess acceptance must use a temporary
   root, restart clients while one backend PID/session remains, and shut down
   only that exact backend.
5. Convert production Qt startup/ViewModel to the client/adapter. Move controller
   shutdown out of GUI close. Headless Qt tests destroy/rebuild an engine and
   prove the backend session survives, without opening a native window.
6. Implement canonical TTC hardware/migration and dedicated setup/status QML.
   Test fixed facts, retained calibration editors, absence of generic controls,
   and no automatic physical commissioning.
7. Update docs, run targeted tests, compileall, diff check and the full suite.

## Validation Plan

Use temporary roots, fakes and loopback only:

1. Backend runtime/state/action unit tests.
2. IPC auth/discovery/client/server failure and sequencing tests.
3. CLI subprocess and GUI-client reconnect persistence tests.
4. Dedicated-machine/migration/QML static tests.
5. Existing affected application, homing, simulation and Qt tests.
6. `.venv\Scripts\python.exe -m compileall -q src tests`.
7. `git diff --check`.
8. `.venv\Scripts\python.exe -m pytest -q`.

Native GUI validation is prohibited in this execution.

## Failure / Escalation Rules

- Preserve public `ApplicationController` safety behavior. If a workflow needs a
  materially broader protocol redesign, report `PLAN_INVALID` with the exact
  missing state/action instead of bypassing it.
- Implementation defects are not blockers; repair and rerun affected gates.
- Replace hardware factories at composition time for subprocess tests. Never
  request or infer hardware permission.
- Preserve conflicting dirty changes and report the narrow conflict; never reset.
- PASS is forbidden if production Qt still owns the production controller, GUI
  close kills the backend, CLI bypasses safety, IPC binds beyond loopback,
  generic hardware configuration remains, or the full suite fails.

## Completion Criteria

- Separate persistent backend and restartable GUI use versioned authenticated
  loopback-only IPC; backend exclusively owns the controller transport.
- Headless proof shows GUI/client reconnect without backend PID/session or
  controller-state loss, plus explicit safe backend shutdown.
- CLI inspects and invokes guarded actions without Qt or direct transport bytes.
- UI is TTC-specific and removes generic machine/controller/pin/polarity and
  hypothetical capability configuration while retaining calibration values.
- X/Y/Z switches and Z plate are installed declarations; homing and E-stop stay
  visibly uncommissioned until real evidence exists.
- Targeted tests, compileall, diff check and full pytest pass.
- Result reports `PASS` with exact evidence/files and confirms no protected-scope
  action. Tell the user manual GUI relaunch is required for source changes.

## Planning Delta — C-014 Homing-first reference and close flow

The user reports that physical homing switches are now available and authorizes
the following bounded follow-on work before final planning sign-off:

1. Remove the operator-facing `Set/Establish Reference` control, guided action,
   explanatory text, and public bypass route. Successful homing is the normal
   source of machine-reference trust; unavailable/uncommissioned homing fails
   closed rather than falling back to a manual trust claim.
2. Replace the exit dialog's `Move to reference, then close` sequence with an
   explicit `Home, then close` action. Route it through the persistent backend,
   wait for successful homing and a fresh Idle observation, then close only the
   frontend. Keep close-without-motion available and never home automatically on
   an ordinary close event.
3. Preserve `ApplicationController.establish_reference` only for internal/fake
   simulation compatibility if still necessary. Remove it from GUI and ordinary
   agent/CLI surfaces when it would bypass the homing policy.
4. Cover success, rejection, alarm/failure, disconnect, safety block,
   spindle-on/active-job block, duplicate click, frontend-only close, and backend
   session survival. Update README and architecture/workflow documentation.
5. Complete fake and digital-twin tests first. Backend-only hardware testing is
   authorized if necessary, but only after backend evidence proves connected,
   Idle, spindle off, and all configured safety gates clear. The agent may restart
   only its own backend after source changes. Do not launch, relaunch, focus,
   capture, or interact with the GUI. Do not change user configuration or silently
   mark the switches commissioned.

`C-014` is the new review checkpoint. Report exact tests and any hardware evidence;
if hardware prerequisites are unknown, skip physical motion and complete the
software slice without treating that as an implementation blocker.

## Planning Delta — C-015 Unified Machine UX

Continue directly from C-014 into C-015 before requesting review:

1. Replace the blocky eight-step navigation with rounded, accessible `Machine`,
   `Prepare`, `Review`, and `Run` navigation. Consolidate connection recovery,
   contextual safety, home, jog, work zero, and supported probing on Machine.
   Place `Home machine` directly above the work-zero controls as their visible
   prerequisite; do not place it inside the jog panel.
2. Remove Connection, Safety, Reference, Work Zero, and Configure primary tabs.
   Move Configure and expert Console to compact bottom utility buttons. Safety
   failures/recovery remain conditionally visible in Machine/Run; healthy state is
   quiet. Do not hide a condition that blocks motion.
3. Remove the redundant healthy header pills and prominent disconnect action.
   Keep manual connection controls secondary. After backend attach, silently adopt
   an existing connection or automatically try the last successful physical method,
   then the other deterministic saved physical method, before showing the failure
   chooser. Bound attempts, avoid duplicates, never scan arbitrary network targets,
   and never auto-connect the digital twin.
4. Add a live position marker to the virtual machine envelope using fresh backend
   MPos. Test coordinate mapping, Y orientation, Z indication, stale/unknown,
   session change, resizing, and out-of-bounds display without falsely clamping it
   into the safe area.
5. Preserve backend authority and frontend restart behavior. Verify headlessly at
   1180×720 and 1500×920 with fake transports/digital twin; update docs and tests.
   C-015 authorizes no GUI interaction or new physical motion.

C-015 replaces C-014 as the combined planning-review checkpoint.

## Sol Review Delta — Required Completion After PLAN_INVALID

The backend foundation is accepted as preserved work, but the result is not an
architectural contradiction: it is an incomplete implementation. Continue with
these bounded decisions rather than stopping:

1. Add dedicated backend tests. Existing application tests and an ad-hoc smoke
   check are insufficient. Commit no files, but add checked-in tests covering
   runtime polling/dispatch, authenticated server/client, stale discovery,
   action rejection, one-session reconnect, loopback binding and exact shutdown.
2. Production `qt.main.main()` must never instantiate `ApplicationController`.
   Add a `BackendProcessManager`/factory that attaches to a healthy discovered
   server or spawns `python -m ttc3018_control.backend.main --root <root>`, waits
   boundedly, and returns a `BackendClient`. It must remember whether it spawned
   the process but must not stop it on GUI close.
3. Implement a client-backed Qt adapter. Do not duplicate safety logic. It may
   retain frontend-local file generation/preview state, but every controller or
   hardware action and all authoritative machine/job/safety state must come from
   backend snapshots/events/actions. A compatibility in-process adapter can keep
   legacy unit tests stable. Prefer an explicit adapter/protocol selected by
   `ControllerViewModel`; do not use unrestricted remote reflection.
4. It is acceptable to migrate the QML incrementally by preserving current
   ViewModel property/slot names while their implementations switch to client
   snapshots/actions. Add a binary production composition test that patches
   `ApplicationController` to raise, calls the production engine composition
   factory with a fake backend client, and proves Qt loads without constructing
   or closing a controller. Add a test that destroys/recreates the headless
   frontend adapter while backend session ID and state remain unchanged.
5. Fully replace `MachineSetupDialog.qml` now with the TTC-specific hardware and
   calibration surface defined above. Remove the profile selector and every
   switch/pin/end/polarity/hard-limit and hypothetical accessory editor. Keep
   calibration controls only when backed by explicit typed client actions; if a
   calibration mutation is not yet supported, show its current value read-only
   rather than retaining a generic configuration escape hatch.
6. Extend backend snapshots/actions only by explicit typed fields needed by the
   current GUI. Missing low-priority UI actions may be visibly unavailable with
   a clear reason, but connection, status, bounded jog/hold/resume/cancel,
   homing/reference, work zero, spindle and job lifecycle must remain functional.
7. Update `EXECUTION_RESULT.md` only after rerunning targeted backend/Qt/QML
   tests and the full suite. `PASS` still requires production Qt composition to
   be client-backed and the generic setup surface to be gone.
