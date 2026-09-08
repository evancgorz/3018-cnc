# Execution Contract

## Objective

Build a production-quality software-in-the-loop digital twin of the Two Trees
TTC 3018 and its MKS DLC32 GRBL-compatible controller. Pine must connect to the
twin through the same raw, line-oriented GRBL TCP path used by the real board;
the twin must not reach into `MachineSession`, `JobService`, motion services, or
Qt state to simulate success.

The twin must implement deterministic controller behavior, all three kinematic
axes over the stated default 3018 travel of **X 290 mm, Y 170 mm, Z 40 mm**, the
spindle/tool, a parametric 3018 machine assembly, work stock and fixtures, and a
bounded 2.5D material-removal model. It must load and verify at least
`examples/showcase-pocket-island.step`, while allowing other supported planar
STEP fixtures to be selected for collision-only or 2.5D removal simulation.

Run a second, independent **operator/safety supervisor subprocess** whenever an
interactive twin session or automated scenario is active. In interactive mode
it observes and interlocks on hazards. In scenario mode it also acts as the
operator by requesting the same public application actions that UI controls use.
It must independently detect machine, workpiece, stock, fixture, tool/holder,
rapid-clearance, travel, and gouge collisions and produce replayable evidence.
It may not mutate plant or application state directly.

Make this twin the normal target for robust feature development and regression
testing when no physical CNC is available. Also prepare a separately authorized,
supervised A/B commissioning harness that can later run a bounded safe script
against the twin and real controller, normalize both traces, and report parity
differences. This execution does not authorize physical-machine access.

## Current State

- Pine is a Qt Quick modular monolith. `ApplicationController` owns
  `ConnectionService`; the latter owns exactly one USB or raw TCP transport.
  QML does not own transport or GRBL commands.
- `Transport` in `application/ports.py` exposes `connected`, `events`,
  `disconnect`, `send_line`, and `send_realtime`. USB and TCP emit the same
  `SerialEvent` queue shape.
- `ControllerViewModel._poll()` consumes transport events, polls status, and
  passes every received line through the normal application response dispatcher.
- `ConnectionMode` and the normal connection dialog expose only USB and Wi-Fi.
- Pine emits GRBL realtime status/hold/resume/reset/jog-cancel; `$J`, `$H`,
  settings, probes/retracts, `G10 L20`, offsets, DLC32 ESP setup, spindle, and
  metric job commands accepted by `gcode.py` (`G0`-`G4`, `G17`, `G21`, `G40`,
  `G49`, `G54`, `G80`, `G90`, `G91`, `G94`, `M0`-`M5`, `M30`, XYZ/IJK/F/S).
- `JobStreamer` uses character-counted flow control and DLC32 `Bf` reports.
  An acknowledgement means acceptance, not completion of physical movement.
- `step_simulation.py` does bounded pre-generation 2D/height-field checks. It is
  not a controller twin, dynamic plant, collision world, or executed-removal
  simulator.
- STEP import already uses OCP and Shapely. `showcase-pocket-island.step` is a
  deterministic 40 x 30 x 5 mm fixture with a blind pocket and retained island.
- `docs/SIMULATION_IMPLEMENTATION.md` is a future-work statement that must be
  replaced by documentation of the implemented architecture and limitations.
- The legacy/default profile is X 290, Y 170, Z 40, safe Z 30. Saved profiles
  may differ and must always be passed explicitly, never silently substituted.
- The worktree contains extensive user-owned changes and untracked config/docs.
  Preserve all unrelated work and never write user `config/` during tests.
- Hardware-free baseline on 2026-09-04: **337 passed in 59.76s** from
  `.venv\Scripts\python.exe -m pytest -q`.

## Final State

### Process and connection topology

```text
Pine main process
  ViewModel -> ApplicationController -> ConnectionService
       -> existing TcpGrblConnection -> 127.0.0.1:<ephemeral>
                                      |
                         digital-twin backend subprocess
                         GRBL engine -> plant -> collision/removal
                                      |
                         versioned telemetry/trace IPC
                                      |
                         operator/safety supervisor subprocess
                         independent oracle + scenario actor
```

- `ConnectionService.connect_simulation()` starts a `SimulationRuntime`, waits
  for a bounded token/version handshake, then connects an ordinary existing
  `TcpGrblConnection` to the reported loopback endpoint.
- The backend binds only `127.0.0.1:0`, accepts exactly one Pine client, never
  opens a COM port, performs discovery, contacts the LAN, or binds all interfaces.
- The ordinary TCP reader, newline framing, event queue, response dispatcher,
  acknowledgement ownership, job streamer, status polling, and safety services
  remain in path. No direct simulation transport may bypass them.
- Runtime owns exact backend and supervisor child processes plus their IPC and
  loopback resources. Partial startup, disconnect, crash, timeout, and app close
  clean them in bounded time without broad process-name termination.
- Worker entry points are Windows-spawn/frozen-build safe and never create Qt
  objects or recursively launch Pine.
- Supervisor receives immutable telemetry/geometry/proposed and executed
  segments and emits hazard verdicts, scenario intents, and evidence. The main
  process maps intents to the same public controller/view-model operations as UI
  controls. Supervisor has no reference to mutable controller/plant/Qt objects.

### GRBL/DLC32 controller fidelity

- Implement a Qt-independent `VirtualGrblController` with its own inbound parser
  and modal/planner/RX/settings/pin/probe/spindle/WCS/alarm/reset state. It must
  not reuse Pine's outbound command builders as its parser.
- Support every command Pine can emit: realtime `?`, `!`, `~`, `0x18`, `0x85`;
  `$J=`, `$H`, `$X`, `$$`, `$I`, `$G`, `$#`, settings including `$6`; G0/G1/G2/
  G3/G4, G10 L20, G17/G21/G40/G43.1/G49/G54/G80/G90/G91/G94, G38.2,
  M0/M1/M2/M3/M4/M5/M30, F/S/XYZ/IJK, and current DLC32 ESP commands.
- Emit realistic startup, asynchronous status, one `ok`/`error:n` per normal
  line, `ALARM:n`, `[PRB:...]`, settings/query reports, and deterministic errors
  for malformed, nonfinite, unsupported, out-of-range, or illegal-state input.
  Realtime bytes never receive acknowledgements.
- Keep command acceptance and motion completion separate. Default to a
  DLC32-compatible 512-byte RX capacity and 15 planner blocks; `Bf` must reflect
  actual free capacity and FIFO ordering.
- Status derives `MPos`, `WPos`, `WCO`, `FS`, `Pn`, and `Bf` from one atomic
  snapshot. WPos = MPos - WCO, including applicable TLO semantics, within
  0.001 mm. Polling works in Run/Jog/Hold/Home/Alarm.
- Implement Idle, Run, Jog, Hold, Home, Alarm, startup/reset, hold/resume, jog
  cancel, soft reset/unlock, optional homing switches, and probe success/failure.
- Probe input is calculated from conductive tool/plate geometry and configured
  polarity, not canned. G38.2 stops at first contact with properly ordered report
  and acknowledgement behavior required by existing probing services.
- Deterministic fault hooks cover delayed/missing/duplicate/error ack, reset,
  alarm/disconnect, frozen state, stale/malformed/missing-WCO status, changed WCO,
  limit/probe activation, spindle delay, fragmented TCP, and partial final lines.

### Deterministic 3-axis plant

- Use an integer-tick virtual clock with manual advancement for tests and
  wall-clock scheduling for interactive use. Realtime/2x/5x/10x/uncapped change
  only time advancement, never geometry, event order, or final state.
- One `VirtualMachinePlant` owns continuous XYZ machine position/velocity/feed,
  planner progress, spindle target/actual RPM, switches, probes, and motion class.
- Default travel is closed and explicit: X [0,290], Y [0,170], Z [0,40] mm in
  Pine's positive-from-reference convention. Inconsistent/nonfinite profiles fail.
- Model per-axis feed/acceleration with deterministic coordinated triangular/
  trapezoidal motion; G17 arcs interpolate XY and helical Z. Endpoints are within
  0.001 mm independent of animation cadence.
- Hold decelerates, resume completes the block, jog cancel decelerates and clears
  only jog motion, and reset clears planner/transient state and stops spindle.
- Enforce travel continuously over swept segments, not only endpoints. Model
  spindle acceleration/deceleration and actual RPM. Material removal requires a
  valid spinning cutter and cutting motion.
- Do not claim cutting force, motor torque, heat, chatter, runout, missed steps,
  tool deflection, or real machine accuracy.

### Machine geometry, STEP stock, and collision behavior

- Add a versioned `MachineGeometryProfile` for conservative parametric 3018
  base/frame rails, bed/Y saddle, uprights, X gantry/carriage, Z carriage,
  spindle, collet/holder, cylindrical tool, reference frame, and allowed joints.
  The same XYZ snapshot drives render and collision transforms.
- Travel dimensions are authoritative. Unavailable manufacturer frame/body
  measurements are explicitly labeled configurable visual/collision proxies,
  never factory facts.
- Represent stock, spoilboard/bed keep-out, and configurable fixtures/clamps as
  independent solids. Use swept broad phase plus OCP distance/intersection or
  conservative analytic narrow phase; endpoint-only/sample-only checks are not
  sufficient for fast moves.
- Required hazards: travel limit, machine self/frame collision, spindle/holder
  versus stock/fixture, tool versus fixture/bed, rapid tool versus stock,
  spindle-off entry, excessive depth, retained-part gouge, and commanded versus
  executed divergence. Expected joint contacts and legitimate spinning-tool
  removal are explicit allowed contacts, not broad ignores.
- Use a bounded, stock-local 3D occupancy/height representation with declared
  resolution/tolerance/cell budget. Sweep actual cutter geometry along executed
  motion and separately report removed, undercut, overcut/gouged, unreachable,
  and remaining volume.
- Import `showcase-pocket-island.step` through existing isolated STEP/OCP code;
  place it in 40 x 30 x 5 stock at an explicit work transform. A valid real
  generated job must meet declared volumetric/surface tolerances and retain its
  island. Shifted, deep, rapid, wrong-tool, spindle-off, and fixture paths fail.
- Other supported STEP files may be selected. Unsupported removal geometry stays
  in clearly labeled collision-only mode; never claim a verified final part.
- STEP/stock/fixture/preview data is observation configuration only. It cannot
  acknowledge commands or alter controller/motion. Executed animation/removal
  comes only from accepted TCP GRBL driving the authoritative plant.

### Independent supervisor and scenario actor

- Supervisor is a distinct process with version/token handshake and heartbeat.
  Crash, mismatch, overflow, or silence fails simulation closed, requests normal
  hold/reset where possible, and reports unavailable supervision prominently.
- Its collision oracle independently recomputes hazards from snapshots and
  immutable geometry. It must not call backend collision-result functions or
  consume backend pass/fail flags. Tests corrupt each checker to prove the other.
- Backend stops before predicted contact where possible. Supervisor catches a
  backend miss within one fixed step, emits interlock, and causes virtual alarm
  without rewriting/rolling back history. Both record first unsafe swept pose.
- Scenario mode emits typed user intents: connect, reference, jog, set zero,
  load named artifact, preflight, start, pause/resume/abort, acknowledge, and
  disconnect. Main invokes public application/view-model entry points and returns
  outcomes. No scenario intent sends transport bytes or calls plant methods.
- Ship normal status/reference/work-zero/all-axis jog/live-jog/return/text/plaque/
  STEP/probe/pause/resume/abort/reset/disconnect scenarios plus every protocol,
  collision, supervisor-failure, final-part, and shutdown failure family.
- Each scenario has seed, preconditions, ordered intents, invariants, terminal
  state, and evidence requirements. Same build/profile/scenario/seed replays to
  identical semantic events, final state, verdicts, and normalized transcript.

### UI, persistence, and evidence

- Add `Virtual Machine (Digital Twin)` beside USB/Wi-Fi in the normal dialog.
  Hide physical fields; show speed, workpiece/scenario choice, loopback-only
  explanation, and `Start Digital Twin`.
- Never save simulation as physical preferred transport or auto-connect it.
  Simulation settings use `config/simulation.json`; tests use temporary roots.
  Simulation reference/WCO/profile/commissioning state cannot read, confirm,
  overwrite, or clear physical connection, machine, work-zero, or probe data.
- Persistently show `DIGITAL TWIN — NO PHYSICAL MACHINE` in main and separate
  simulator windows, with distinct styling and session marker in logs/exports.
- Add a separate native `SimulationWindow.qml` and thin
  `SimulationViewModel`. Render machine bodies, moving Y/X/Z members, tool,
  stock/STEP/fixtures, origins, preview, executed rapid/cut paths, removed stock,
  collision point/envelopes, axes, and numeric state from immutable snapshots.
- Provide fit/reset/isometric/top/front/side views; layer toggles; speed controls;
  trace export; scenario controls; and separate developer fault panel. Visual
  pause is explicitly rendering-only. Normal Pine controls perform machine hold.
- Closing during job/scenario requires confirmation; accepted close follows
  normal disconnect/trust invalidation. Animation never drives controller time.
- Trace every lifecycle, normalized TX/RX line, parser/queue/modal transition,
  motion/spindle/stock/collision event from both engines, user intent/outcome,
  fault, heartbeat/crash, and final snapshot with monotonic sequence/sim time.
- Export human Markdown plus JSON trace, final snapshot, collision evidence,
  stock metrics, and scenario assertions. Golden traces exclude PID/port/wall
  time/absolute paths/platform noise. Secrets remain redacted.

### Development and later A/B commissioning

- Add a headless verification CLI so feature work can run the twin as a standard
  test dependency without Qt or hardware and receive machine-readable pass/fail,
  trace, collision, and final-part evidence.
- Add reusable pytest fixtures/builders for a connected twin, deterministic time
  advancement, safe referenced state, work zero, loaded artifact, fault schedule,
  and supervisor scenario. Feature tests should use these instead of ad-hoc fake
  transports when controller/plant behavior matters.
- Add a parity-capture schema and comparator that can normalize twin and real
  controller sessions: command/response ordering, accepted status fields, state
  transitions, MPos/WPos/WCO coordinates, probe reports, feed/spindle, buffer
  fields, reset banners, and timing envelopes. Ignore only declared hardware/
  firmware variability and show every ignored field in the report.
- Prepare a bounded A/B commissioning script with staged gates: read-only banner/
  status/settings; spindle-off tiny XYZ jogs within an established safe envelope;
  work-offset round trip; optional spindle/probe only after separate explicit
  authorization and physical preflight. Each stage can stop independently.
- The real-machine capture adapter is inert unless a user explicitly selects a
  physical endpoint and approves that later session. Do not schedule, launch, or
  imply authorization for physical A/B testing in this execution.
- A/B output reports matched fields, tolerances, timing distributions, outliers,
  protocol differences, twin calibration suggestions, and items that cannot be
  inferred safely. It never auto-tunes the twin from one physical run.

## Allowed Scope

- New `src/ttc3018_control/simulation/` package for contracts/settings, clock,
  protocol/controller, plant, geometry, stock, collisions, backend/runtime,
  supervisor/scenarios, tracing/replay, verification CLI, and parity tooling.
- Focused changes to application ports/state/connection/controller for explicit
  simulation lifecycle/state/persistence isolation.
- A separate simulation settings module; physical `connection_settings.py` only
  to ensure simulation is not a preferred physical transport.
- `qt/main.py`, `qt/view_model.py`, a simulation adapter, `Main.qml`, and new
  simulation QML/components for connection and visualization.
- STEP artifact metadata changes strictly required for immutable workpiece
  observation configuration.
- Pinned development coverage dependency when used, focused tests/fixtures/golden
  traces, documentation, and execution result.

## Protected Scope

- Any TTC/Pine instance that existed before a validation run is user-owned: do
  not terminate, restart, activate, focus, resize, capture, or interact with it.
  Luna is explicitly authorized to launch, activate, exercise, resize, capture,
  and close only the isolated Pine instances it starts for this execution. Tag
  each owned instance with a unique temporary root/session marker, record its
  PID, and close that exact PID through normal application shutdown. Never use
  process-name-wide termination or assume an untagged window is test-owned.
- Never connect to, enumerate for connection, jog, home, probe, reset, configure,
  or stream to physical CNC hardware in implementation/validation. Never open a
  real COM port or non-loopback socket in tests or owned GUI instances. Disable
  startup auto-connect, inject sentinel physical factories, and select only the
  digital-twin connection. UI permission does not broaden hardware permission.
- Do not modify user `config/*.json`, logs, screenshots, examples, or unrelated
  dirty work. Tests use temporary roots and ephemeral loopback.
- Do not weaken physical USB/Wi-Fi behavior, GRBL gates, job grammar, ordering,
  reference/work-zero semantics, or freshness rules to make the twin pass.
- Do not contaminate physical trust/persistence, auto-connect simulation, or own
  physical and simulated transports together.
- Do not fake progress from preview/UI/scenario expectations or direct mutation.
  Only accepted GRBL drives plant; only plant snapshots drive execution visuals.
- Do not claim manufacturer-accurate proxy dimensions or physical machining
  safety/accuracy/force/thermal/general-3D verification.
- A/B tooling does not authorize a physical run. Real testing requires a later
  explicit user request, supervised preflight, and stage-specific approval.
- Do not commit, push, delete user work, or use destructive Git operations.

## Implementation Steps

1. Add `simulation/models.py` and `simulation/settings.py`: schema-versioned
   frozen records for profiles, geometry/tool/stock/fixtures/STEP placement,
   snapshots/events/hazards, faults, intents/outcomes, and handshakes; atomic
   settings store; finite/unit/path/transform/cell-budget validation. Success:
   malformed/future data fails and default travel is exactly 290/170/40.

2. Add `simulation/clock.py` and `simulation/plant.py`: integer manual/wall
   clock, coordinated acceleration motion, arcs, queues, spindle, hold/resume/
   cancel/reset, switches/probe and swept travel limits. Success: speed/frame
   invariant traces and <=0.001 mm endpoints without Qt.

3. Add `simulation/protocol.py` and `simulation/controller.py`: independent
   inbound parser, modal/settings/WCS/TLO/pin/buffer state, complete current Pine
   command inventory, reports/acks/errors and deterministic protocol faults.
   Success: black-box transcripts conform without outbound-builder imports.

4. Add `simulation/geometry.py`, `collision.py`, and `stock.py`: parametric 3018
   fixed/moving bodies and transforms, allowed joints, analytic/OCP continuous
   collision, bounded executed removal and target comparison. Success: every
   required hazard has first-contact evidence and normal full travel is clean.

5. Add `simulation/trace.py`: one sequencer, canonical JSON, bounded buffering,
   export bundle, golden normalization, replay, semantic comparison. Success:
   same seed produces byte-identical normalized results.

6. Add `simulation/backend.py`: spawn entry, loopback-only ephemeral single-client
   raw GRBL server, token handshake, controller advancement, telemetry and exact
   shutdown. Success: unmodified `TcpGrblConnection` drives it; no external bind.

7. Add `simulation/supervisor.py` and `scenarios.py`: independent oracle,
   heartbeat/interlock, typed operator intents/invariants and required scenarios.
   Success: corrupting either collision checker is caught by the other and the
   supervisor cannot import application/Qt/transport/backend-verdict code.

8. Add `simulation/runtime.py`: own/start/handshake/monitor/stop both children,
   broker telemetry/intents, expose immutable snapshots/controls, and clean exact
   resources on every lifecycle path. Add packaging-safe worker dispatch only if
   required. Success: repeated tests leave no child/thread/port/handle orphan.

9. Extend `ConnectionMode`, `ConnectionService`, and `ApplicationController`
   with explicit simulation factories/connect lifecycle. Active transport remains
   existing `TcpGrblConnection`. Success: sentinel USB/Wi-Fi factories have zero
   calls and all workflows consume normal events.

10. Isolate persistence with the smallest controller refactor: simulation
    reference/WCO/profile/workpiece/fault/commissioning state is volatile or in
    simulation store; cache/restore physical views without disk writes. Success:
    physical config hashes remain identical after success, failure, and crash.

11. Extend STEP/generation metadata and view model only enough to pass immutable
    source/stock/tool/origin/fixture/target observation data to active runtime.
    Default to pocket/island; label unsupported as collision-only. Success:
    changing observation data cannot change identical-G-code protocol/motion.

12. Add `qt/simulation_view_model.py`, `SimulationWindow.qml`, components, and
    focused Main/view-model integration for connection, banners, geometry/path/
    stock/hazard display, speeds, layers, scenarios, faults, export, guarded
    close. Success: UI projection cannot advance or mutate simulation.

13. Add `simulation/verify.py` (`python -m ...simulation.verify --all --output
    <dir>`) and pytest fixtures. It runs uncapped headless scenarios and writes
    summary, traces, final snapshots, stock/collision results and Markdown.
    Commit only compact golden files under `tests/fixtures/digital_twin/`.

14. Add `simulation/parity.py` with versioned capture normalization/comparison,
    an inert real-capture entry point requiring explicit physical selection, and
    staged A/B plan/report generation. Unit-test entirely with recorded synthetic
    fixtures; do not connect hardware. Success: declared tolerances/ignored fields
    are visible and mismatches are actionable.

15. Replace `docs/SIMULATION_IMPLEMENTATION.md` with implemented architecture,
    operation, fidelity/limits, collision/STEP/scenario/evidence guidance and the
    future supervised A/B checklist. Update README/ADR only for real changes.

16. Work in verified vertical slices: contracts/settings; clock/plant; protocol;
    geometry/collisions; subprocess/runtime; application integration; STEP stock;
    supervisor/scenarios; UI; parity/evidence. After each slice run its focused
    deterministic tests and repair implementation-caused failures before moving
    on. Do not declare `PASS` because a demo path works, because most tests pass,
    or because execution has been lengthy. Success requires every completion
    criterion, regression, coverage, process-cleanup, and evidence gate below.

## Validation Plan

1. Record scope/status and physical config hashes; after work run `git diff
   --check` and targeted diff review. Pass: no config/log/example/unrelated write,
   physical endpoint/COM access, raw QML GRBL, or out-of-scope change.

2. Run `python -m compileall -q src tests` and import-boundary tests. Pass:
   application stays Qt-independent; workers avoid Qt/application side effects;
   supervisor avoids transport/backend verdicts; inbound parser avoids outbound
   builders; no circular/spawn recursion.

3. Test settings defaults/boundaries/NaN/Inf/schema/path/transform/cell budget,
   malformed JSON, atomic failure and round trips. Pass: fail closed in `tmp_path`.

4. Table-test every normal/realtime command, modal combination, case/spacing,
   TCP fragmentation, illegal/malformed/nonfinite input, query/probe/home/WCO/TLO/
   reset, RX/planner capacity, and response ordering. Pass: exact transcripts,
   one terminal response per normal line and none for realtime.

5. Seed plant endpoints/feeds/arcs/holds/resumes/cancels/time partitions at every
   speed/cadence. Pass: equal semantic traces/final states, finite in-travel pose,
   monotonic time, no teleportation, <=0.001 mm endpoints.

6. Test each machine body across extrema, allowed joints, swept high-speed
   collision, tolerance near-miss, and every hazard including safe endpoints with
   unsafe sweep. Pass: correct first contact and no false normal-travel collision.

7. Execute the real generated pocket/island program; mutate shift/depth/tool/
   spindle/rapid/island/fixture/stock. Pass: valid result meets declared target
   tolerance and each mutation fails for its independent intended cause; test one
   collision-only model.

8. Spawn backend and use unmodified `TcpGrblConnection` for banner/poll/stream/
   fragmentation/status/ack/reset/disconnect. Pass: only 127.0.0.1 ephemeral,
   one client, correct ordering and bounded cleanup.

9. With sentinel physical factories, drive complete `ApplicationController`
   connect/reference/WCO/all-jog/move/return/spindle/text/plaque/STEP/probe/pause/
   resume/abort/complete/disconnect workflows. Pass: public APIs/events only,
   expected trust/state, no direct mutation, zero physical-factory calls.

10. In Windows spawn context test supervisor handshake/token/version, heartbeat,
    backpressure, malformed IPC, crash/hang/owner death, checker corruption,
    action denial and interlock latency. Pass: independent detection, no mutation,
    safe failure, exact child PIDs exit, no orphan resource.

11. Inject every fault before/during/after motion where meaningful. Pass:
    existing application failure/recovery contracts, no false trust/completion,
    uncertainty displayed and trace trigger/outcome recorded.

12. Run every scenario twice and replay exports. Pass: normalized transcript,
    semantic events, verdicts and final snapshot byte-identical; all evidence
    populated; alternate seeds preserve invariants.

13. Seed physical config files with sentinels and run success/failure/crash/
    cancel. Pass: physical files/in-memory selection unchanged/restored;
    simulation never preferred or trusted physically.

14. First use `QT_QPA_PLATFORM=offscreen` and existing `build_engine` to verify
    connection mode/hidden fields/start/banner/separate-window model, snapshot
    projections, controls, guarded close, narrow layouts, crash cleanup, and no
    QML warnings or physical factories. Use deterministic snapshot injection.

15. Feed at least 10,000 seeded protocol lines/frame partitions and 100 bounded
    action/fault schedules. Pass: no crash/deadlock/nonfinite state; response,
    sequence, time, travel and replay invariants; seed reported on failure.

16. Run parity comparator tests with synthetic twin/physical captures covering
    matches, tolerated numeric/timing variance, missing/reordered lines, firmware
    field differences, unsafe script rejection and stage gating. Pass: no real
    transport constructed and every ignored field/tolerance is reported.

17. Add pinned coverage tooling if absent. Require >=90% line and >=85% branch
    coverage for the new simulation package, with only justified worker-guard
    exclusions. Then run full `.venv\Scripts\python.exe -m pytest -q`. Pass: all
    old/new tests, no skip/xfail hiding required behavior.

18. Run verification CLI into a fresh evidence directory and validate its own
    schemas/links. Pass: zero failed scenarios; stock/collision/child-cleanup/
    protocol hashes/test totals/durations/seeds present.

19. **Owned runtime GUI validation.** Starting state: record all existing Pine
    PIDs/windows without focusing them; create a fresh temporary application root
    with auto-connect disabled and sentinel USB/Wi-Fi factories; launch one new,
    visibly tagged Pine instance and record its exact PID. Do not select USB or
    Wi-Fi. Actions: open Connection; select `Virtual Machine (Digital Twin)`;
    verify physical endpoint fields disappear; choose 10x and the pocket/island
    workpiece; start the twin; verify the persistent no-physical-machine banner,
    separate simulator window, healthy supervisor, Idle state, and matching
    numeric/rendered XYZ. Establish virtual reference/work zero; jog positive and
    negative X/Y/Z; verify each moving body and status; load and run the default
    generated STEP scenario; pause/resume; exercise view/layer/speed controls;
    inject a fixture collision and verify first-contact visualization, alarm, and
    failed scenario; export evidence; disconnect; close through normal UI.
    Expected final state: the owned main/simulator/backend/supervisor PIDs exit,
    loopback port closes, no real transport factory was called, physical config
    sentinel hashes are unchanged, and pre-existing Pine PIDs/windows are
    unchanged. Pass evidence: screenshots of the connection choice, banner/full
    3018 view, all-axis poses, cutting/stock state, and collision state; exported
    JSON/Markdown trace; process/socket cleanup log; QML/application log without
    warnings/errors. One serious repair/retry is allowed for owned GUI automation;
    if environmental UI automation remains unreliable, report `BLOCKED` with the
    exact step, expected/observed state, screenshots/logs, and required action.

20. Document—but do not execute—the later A/B commissioning procedure with
    exact safe start state, explicit per-stage approvals/actions/expected fields,
    pass/fail/abort conditions, emergency-power requirement, evidence capture and
    minimum discrepancy report. Physical spindle/probe stages remain optional
    and separately authorized.

## REPLAN Delta — Coverage and Owned GUI Gates

The prior implementation and passing hardware-free tests remain valid. This
delta supersedes only the coverage procedure and implementation step 19.

### Coverage implementation

1. Update `pyproject.toml` with `[tool.coverage.run]` settings `branch = true`,
   `source = ["ttc3018_control.simulation"]`, `concurrency =
   ["multiprocessing"]`, and `parallel = true`. Do not omit `backend.py`,
   `supervisor.py`, or `verify.py` from measurement. This configuration is
   required because Windows `spawn` children create fresh interpreters and do
   not inherit command-line-only coverage options.
2. Add `tests/test_simulation_controller_branches.py` for the currently missing
   GRBL inventory and failure branches: byte/type/RX overflow, every realtime
   byte, `$$/$I/$G/$#/$X/$H/$J` and settings success/error, ESP, modal G/M
   commands, zero-radius and clockwise/counterclockwise arcs, probe miss,
   partial offsets, pin/Bf reporting, limit alarm, and every ACK fault.
3. Add `tests/test_simulation_plant_and_safety_branches.py` for clock/profile/
   workpiece validation, spindle ramp/down and invalid targets, zero-length and
   polyline motion, hold/resume/jog-cancel/reset/limit callbacks, every collision
   classification, divergence/no-divergence, stock budget/target/gouge/uncovered
   branches, and geometry validation/intersection branches.
4. Add `tests/test_simulation_evidence_branches.py` for parity validation and
   numeric/timing/semantic/count differences, capture read/write failures, trace
   normalized and unnormalized exports plus malformed/noncontiguous replay,
   custom unknown/malformed scenarios, and `simulation.verify.main` for `--all`,
   named selection, and no-match failure.
5. Add `tests/test_simulation_spawn_workers.py`. Exercise real
   `SimulationRuntime` Windows-spawn children through loopback only: backend
   boot/status/fragmented command/client reconnect/interlock/orderly stop;
   supervisor heartbeat, intent, hazard, stock metrics, and orderly stop. Add
   parent-side fake-context tests for backend/supervisor handshake timeout and
   mismatch, superseded/failed startup cleanup, queue overflow, interlock
   de-duplication, dead-supervisor fail-closed behavior, invalid scenario input,
   graceful stop and exact-owned-child terminate fallback. Never launch Qt or a
   physical transport in these tests.

Run the gate from a fresh external data prefix:

```powershell
$env:COVERAGE_FILE = Join-Path $env:TEMP 'pine-twin-coverage'
.venv\Scripts\python.exe -m coverage erase
.venv\Scripts\python.exe -m coverage run -m pytest -q
Get-ChildItem "$env:COVERAGE_FILE.*"
.venv\Scripts\python.exe -m coverage combine --keep
.venv\Scripts\python.exe -m coverage report -m
.venv\Scripts\python.exe -m coverage json -o (Join-Path $env:TEMP 'pine-twin-coverage.json')
.venv\Scripts\python.exe -c "import json,os,pathlib; p=pathlib.Path(os.environ['TEMP'])/'pine-twin-coverage.json'; d=json.loads(p.read_text()); t=d['totals']; line=100*t['covered_lines']/t['num_statements']; branch=100*t['covered_branches']/t['num_branches']; files=d['files']; assert line >= 90, line; assert branch >= 85, branch; assert any(k.endswith('simulation\\backend.py') and v['summary']['covered_lines'] > 40 for k,v in files.items()); assert any(k.endswith('simulation\\supervisor.py') and v['summary']['covered_lines'] > 30 for k,v in files.items()); print(f'line={line:.2f}% branch={branch:.2f}%')"
```

Pass only when the full suite passes, at least three parallel data files exist
(parent plus actual spawned workers), combined line coverage is at least 90.00%,
combined branch coverage is at least 85.00%, and executed worker-function lines
are present for both backend and supervisor. The reproduced pre-replan baseline
is 372 passing tests, 1163/1582 lines (73.51% line-only; coverage.py's combined
display is 68%), and 271/524 branches (51.72%); `backend.py` and
`supervisor.py` are each 10% because their spawned execution was not collected.

### Owned GUI validation boundary

6. Add `scripts/run_simulation_gui_validation.py` and make the smallest support
   change to `src/ttc3018_control/qt/main.py`: allow `build_engine` to receive an
   already constructed `ApplicationController`. The launcher must create a
   unique temporary application root and session marker, disable auto-connect,
   inject USB/Wi-Fi factories that raise and record any call, set a window title
   containing the marker, write a manifest containing only its exact main PID,
   temp root, marker, log path, physical-config sentinel hashes, and later owned
   child PIDs/loopback endpoint, and use normal `aboutToQuit` cleanup. Unit-test
   the injection/manifest/sentinel behavior in `tests/test_qt_shell.py`; do not
   launch the visible app during implementation validation.
7. Luna must finish all source/test edits and headless gates, then stop and
   report `BLOCKED` with the single required user action: manually run
   `.venv\Scripts\python.exe scripts\run_simulation_gui_validation.py`. This is
   the required manual relaunch under `AGENTS.md`; Luna must not run it.
8. The launched instance is user-owned. Before any agent GUI validation, the
   user must identify the session marker and explicitly authorize observation,
   activation/focus, resize, screenshots, digital-twin-only UI interaction, and
   normal UI closure of that exact tagged main/simulator instance. Permission
   does not extend to any pre-existing Pine instance, physical transport, broad
   process enumeration, force termination, or restart.
9. After that authorization, perform the original step-19 checklist only on the
   exact tagged instance. Read owned PIDs/endpoint from its manifest, not by
   scanning or matching process names. Pass evidence is: connection choice and
   hidden physical fields; persistent banner and simulator window; healthy
   supervisor; matching XYZ after positive/negative jogs; STEP run and
   pause/resume; collision/alarm; exported trace; zero sentinel-factory calls;
   unchanged sentinel hashes; normal-close log; owned child PIDs exited; owned
   loopback port closed. Do not inspect, focus, capture, or compare pre-existing
   Pine windows/processes.
10. No source or test edit is allowed after the tagged instance launches. If GUI
    validation exposes a defect, close only the exact instance through normal UI
    when that was explicitly authorized, apply the fix, rerun headless gates,
    and stop for a new user manual relaunch and a new scoped permission. The GUI
    gate cannot legitimately pass in the same turn that modifies source/tests.

## REPLAN Delta — Final Runtime Commissioning and Contract Closure

This delta is authoritative over the earlier **Owned GUI validation boundary**
steps 7–10 and over any statement that native Computer Use is unavailable. The
trusted desktop service is available through the Node REPL using `@oai/sky`.
The user has explicitly authorized launching, focusing, resizing, interacting
with, normally closing, and relaunching Pine instances as needed for this
digital-twin validation. This authorization does **not** permit COM/USB access,
physical Wi-Fi/controller factories, non-loopback controller endpoints, or
physical A/B commissioning; the real machine remains outside this execution.

Treat the following as one large implementation-and-validation chunk. Do not
stop after individual sub-gates while an ordinary implementation repair can
still complete the contract.

1. Preserve and verify the launcher profile repair in
   `scripts/run_simulation_gui_validation.py`: `_write_sentinel_config` must
   write valid isolated `machines.json` and `machine-profile.json` data whose
   selected profile is X 290/Y 170/Z 40 mm with safe Z 30 mm. Keep physical
   factories inert and recording, all config under the unique temporary root,
   and pre/post sentinel hashes. In `tests/test_qt_shell.py`, use an isolated
   `ApplicationController` and assert launcher-loaded travel `(290, 170, 40)`.

2. Before visible launch, run launcher/Qt targeted tests, focused simulation
   tests, `compileall`, and `git diff --check`; then run the complete suite with
   the pinned multiprocessing coverage procedure. Pass only with all tests
   green, simulation line coverage >=90%, branch coverage >=85%, and measured
   execution in real backend and supervisor worker processes.

3. Run the verification CLI into a fresh timestamped external evidence
   directory. Require 5/5 scenarios and validate the report, summary, trace,
   and final-state schemas/links. Record paths and hashes in the result.

4. Launch a fresh uniquely tagged validator using
   `.venv\Scripts\python.exe scripts\run_simulation_gui_validation.py`.
   Automate Windows through the trusted Node REPL and `@oai/sky`; select the
   exact title containing the printed marker. Read owned PIDs, loopback endpoint,
   temp root, log, and hashes from its manifest. Never select USB/Wi-Fi and
   reject any controller endpoint other than `127.0.0.1`.

5. Through normal public GUI actions: select `Virtual Machine (Digital Twin)`
   and verify physical fields hide; select 10x and `Pocket + retained island`;
   connect; verify the persistent no-physical-machine banner, separate simulator,
   healthy supervisor, GRBL Idle, 290x170x40 travel, and matching XYZ. Establish
   reference/work zero. Jog positive and negative X/Y/Z inside travel and verify
   numeric/rendered movement. Load/run the default generated STEP scenario;
   pause/resume; exercise view/layer/speed controls; verify removal state.
   Trigger a deterministic safe fixture/workpiece collision through a public
   UI/scenario action—never direct plant mutation—and verify first-contact
   visualization, interlock/alarm, and failed verdict. Export trace/evidence via
   the GUI. Capture evidence at each meaningful state.

6. If a required public control is absent or the GUI exposes a code defect,
   implement the smallest architecture-consistent repair and regression test,
   normally close the exact instance, rerun affected headless/full gates, and
   repeat with a fresh marker. Such a defect is not an environmental blocker.

7. Disconnect and normally close the exact tagged main/simulator instance.
   Verify recorded main/backend/supervisor PIDs exit, loopback closes, physical
   factory calls stay zero, and sentinel hashes remain unchanged. Existing Pine
   instances may be used, closed, or relaunched under current authorization,
   but the tagged instance is preferred. Never terminate broadly by process
   name and never access hardware.

8. Audit every completion criterion. Write `PASS` only when headless, coverage,
   CLI, live GUI, collision/interlock, export, physical-isolation, and cleanup
   gates pass. Include commands, counts, coverage, evidence paths, session
   marker, owned PIDs/endpoint, UI captures, logs, hashes, deviations, and an
   explicit statement that no physical session occurred. Escalate only for a
   genuine architecture contradiction or a proven non-code environmental block.

## Failure / Escalation Rules
### Sol review delta — live WCO and STEP-run repair

The 2026-09-04 Sol review disproved the worker's `@oai/sky` blocker. The correct
dedicated `mcp__node_repl__js` runtime imported `@oai/sky`, enumerated the exact
tagged window, and completed connection, 10x selection, reference establishment,
positive/negative X/Y/Z jogs, simulator/main XYZ agreement, and guided import /
generation of `showcase-pocket-island.step`. Do not use the unified browser/CUA
REPL for this gate.

The live path exposed a reproducible implementation defect. At machine
`X276.15 Y0.00 Z6.00`, pressing `Zero XYZ` changed the readiness flag to
`Confirmed`, but both main and simulator continued reporting work coordinates
equal to machine coordinates rather than `X0 Y0 Z0`. The generated job therefore
continued to fail preflight as `Z job range would be -5.200…3.000 mm ... allowed
0.000…40.000`, although applying WCO at machine Z6 should place its machine-Z
range at 0.8…9.0 mm. Fix the virtual controller's `G10 L20`/WCO/status behavior
and, if necessary, the application freshness/confirmation path; do not weaken
the envelope check. Add focused regression tests that drive the command through
ordinary `TcpGrblConnection`/application status polling and prove fresh WCO,
WPos=MPos-WCO, confirmed work zero only after the updated report, and a generated
STEP job fitting when zeroed at safe machine Z. Also test partial-axis zeroing.

The tagged run was normally disconnected and closed. Main PID 15136 and owned
children 19736/11092 exited and port 60181 closed. Physical connection,
machine-profile, machines, work-zero, and z-touch sentinel hashes were unchanged.
`step-prepare.json` changed after the guided STEP workflow; it is simulation/job
preparation state, not physical transport state. Make the manifest/result label
physical safety sentinels separately from expected mutable isolated job settings,
and prove no physical factory calls.

After repair, run targeted tests, the full coverage gate, and CLI. Launch a fresh
tagged validator and repeat the live procedure from connection through safe-Z
zero, generated STEP start, pause/resume, collision/interlock, evidence export,
disconnect, and exact cleanup. Write `PASS` only when every remaining GUI gate is
observed. Ordinary implementation defects remain Luna work, not `BLOCKED`.


- Return `PLAN_INVALID` before direct simulator state injection, weakened real
  safety contracts, shared mutable/oracle-verdict state, or physical access.
- Return `PLAN_INVALID` if deterministic OCP placement/collision or a meaningful
  generated default STEP job is impossible; include evidence and smallest safe
  alternative rather than silently dropping required verification.
- Return `PLAN_INVALID` if frozen-build constraints make two owned subprocesses
  infeasible without architectural decision; preserve valid headless work.
- Treat outbound/inbound semantic discrepancies as evidence; diagnose which side
  violates behavior rather than copying code to force agreement.
- Fix ordinary implementation failures. Escalate repeated nondeterminism,
  deadlock, unexplained oracle disagreement, or required representation changes.
- If environment/antivirus blocks child startup, return `BLOCKED` with exact
  handshake/error and minimum user action; do not substitute threads.
- If offscreen Qt cannot prove a visual detail, use the authorized tagged owned
  runtime procedure above. Never interact with a pre-existing/user-owned instance.
- Never guess actual frame/cutter/stock/clamp measurements. Proxy defaults are
  labeled; later physical A/B cannot start without explicit user authorization.

## Completion Criteria

- Pine offers a clearly marked digital twin and connects through unmodified raw
  `TcpGrblConnection` to loopback backend; physical transports are provably idle.
- A separate healthy supervisor acts through public intents, independently
  catches all collision/error classes, interlocks failures, and cannot mutate
  application/plant state.
- GRBL status/ack/buffer/modal/WCO/probe/spindle/reset/hold/resume/fault behavior
  satisfies Pine's full emitted command inventory and freshness/ownership rules.
- Deterministic X 290/Y 170/Z 40 plant behavior, arcs, acceleration, limits and
  spindle meet endpoint and speed/frame-independence criteria.
- Separate window animates actual authoritative machine/workpiece state and
  cannot drive it; proxy geometry provenance is honest.
- Valid pocket/island STEP machining meets target tolerance and intentional
  rapid/fixture/holder/tool/depth/island failures have first-contact evidence.
- Physical settings/trust remain byte-identical and simulation is never preferred.
- Scenario traces replay, CLI produces inspectable zero-failure evidence, new
  package coverage meets 90% line/85% branch, and full suite including original
  337 tests passes hardware-free.
- Twin fixtures/CLI make it the normal robust development test target without a
  CNC. Parity tooling and a staged safe A/B commissioning plan are complete and
  fully tested synthetically, but no physical session has occurred.
- Documentation states fidelity/limitations and no physical-safety claim. Owned
  validation instances and their child processes were closed cleanly, and every
  pre-existing/user-owned Pine instance remained untouched.
## Sol review delta — WCO lifecycle cleanup (2026-09-07)

Sol review rejected the latest PARTIAL result on one bounded implementation gap:

- `ApplicationController.disconnect()` clears `_work_zero_request_pending_ack` but leaves `_work_zero_expected_offset` and `_work_zero_expected_axes` stale.
- `ApplicationController.reset()` does not clear any of those pending WCO acknowledgement fields.
- `__init__` initializes `_work_zero_expected_offset` and `_work_zero_expected_axes` twice.

Luna must remove the duplicate initialization, clear all three pending acknowledgement fields on disconnect and reset (as already done on close/abort), and add focused regressions proving stale WCO reports cannot confirm a work zero after either lifecycle boundary. Run only the smallest relevant WCO/controller tests. Do not rerun the full suite, coverage aggregation, CLI corpus, or GUI; their prior evidence remains valid except for the corrected files. Update `EXECUTION_RESULT.md` honestly with the focused commands and outcome, retaining the unresolved STEP GUI disclosure. Do not access hardware or alter unrelated files.
## Sol review delta — planner backpressure and post-stream motion control (2026-09-07)

Fresh isolated GUI evidence after the WCO repair exposed a protocol-fidelity defect:

- Tagged session `pine-twin-gui-8ec01ec439a9`, 10x, `showcase-pocket-island.step`, machine Z 6.00/work Z 0.00.
- STEP import, automatic proposal, generation, envelope preflight, and Start all succeeded.
- Within seconds the application displayed `Complete · 100%` while the authoritative plant still reported GRBL Run and approximately nine minutes remained. This means the twin acknowledged/queued essentially the whole program instead of enforcing its declared planner capacity.
- Clicking Pause changed the authoritative controller from Run to Hold, but the application reported `Pause failed — Job is not running`. Clicking Resume changed Hold back to Run, but reported `Resume failed — Job is not paused`.
- Abort correctly reset the twin to Idle. The exact tagged instance was disconnected and closed; launcher session exited. No hardware was accessed.

Luna must correct this as one coherent fidelity chunk:

1. Enforce bounded GRBL-like planner admission in the virtual controller/runtime. Motion lines received while planner capacity is exhausted must be retained in order and acknowledged only when admitted after capacity frees; do not emit a synthetic buffer-full error and do not permit an unbounded plant queue. Realtime status/hold/resume/reset must remain responsive while normal lines wait. Reset must clear deferred input safely.
2. Reconcile job controls during the final controller-drain phase: while the application is waiting for GRBL Idle after the last streamed acknowledgement, Pause and Resume must remain truthful and functional based on the observed controller state, not fail solely because `JobStreamer.state == complete`. Timing and UI state must not claim the physical/twin motion is complete before Idle. Preserve correct behavior for real GRBL transports; do not add simulation-only application shortcuts.
3. Add deterministic unit/integration regressions proving queue depth never exceeds planner capacity, acknowledgements are deferred and ordered, reset clears deferred work, realtime hold/status/resume work under backpressure, long simulated streaming does not reach completed state while substantial plant motion remains, and pause/resume are accepted and reflected during final drain.
4. Run targeted simulation-controller/runtime/job-service tests first, then the affected simulation integration group. Do not run the repository-wide suite, CLI corpus, or GUI in this correction pass. Update `EXECUTION_RESULT.md` with exact evidence and retain the need for one fresh final GUI confirmation.

Protected scope remains unchanged: no physical transport, USB/COM, non-loopback endpoint, hardware settings, unrelated refactor, or user-owned Pine instance. Do not launch the GUI during implementation.

## Sol program delta — complete the digital-twin backlog (2026-09-07)

The user has authorized execution of every item in the proposed backend-first
digital-twin backlog, with a verified commit and push after each item. Work must
proceed sequentially in these coherent packages: (P0) close the present
collision/export acceptance contract; (P1) public-interface backend scenario
harness; (P1) independent virtual operator/safety actor; (P1) collision and
coordinate-frame hardening; (P1) GRBL protocol-fidelity expansion; (P2)
deterministic evidence/replay; (P2) STEP stock-removal fidelity; (P2) fault
injection/recovery; (P2) long-duration randomized/property testing; (P3) QML
and frontend verification; (P3) a synthetic physical A/B commissioning plan
and fixtures, with actual hardware execution deferred until separately and
explicitly authorized.

For every package Luna must: inspect current evidence before editing; implement
through existing public application/controller boundaries; add deterministic
headless tests; run focused tests before broader affected gates; update the
backlog/result documentation honestly; review the staged diff for generated,
personal, or unrelated files; commit only the package's intended files; and
push the resulting commit to the current tracked branch. Do not stage runtime
configuration, local evidence directories, `%SystemDrive%`, credentials, or
unrelated user work. A package is complete only after the pushed commit is
confirmed on `origin` and its tests/evidence pass.

GUI work is restricted to concise milestone acceptance checks. Bulk protocol,
simulation, collision, replay, fuzz/property, and application-state validation
must be headless. Never select or instantiate physical USB/COM/Wi-Fi transports
or non-loopback endpoints. Do not run a physical A/B session. Existing Pine
windows remain protected except for exact uniquely tagged validator instances
whose ownership is established by title and manifest; normal cleanup is
preferred, and exact-PID termination is allowed only for a verified owned hung
validator after normal close fails under the user's existing authorization.

Immediate P0 success requires fresh post-fix public-UI proof of the translated
workpiece collision, first-contact/interlock/alarm/failed verdict, GUI evidence
export, physical-factory/sentinel safety, and exact owned-process cleanup. It
also requires a reviewed commit containing the accumulated digital-twin work
without generated/personal artifacts, a successful affected/full validation
appropriate to that large baseline, and a confirmed push. If Computer Use is
stopped again, preserve backend progress and report PARTIAL rather than
claiming the GUI gate.

## Sol review delta — simulator restoration affordance (2026-09-07)

The final tagged GUI run proved the corrected public alarm path and exact
cleanup, but the simulator had been minimized during setup and could not be
restored through trusted UI automation. Since the simulator is a first-class
digital-twin surface, add a small public `Show simulator`/`Show digital twin`
action in the main simulation-connected UI that raises and activates the owned
simulator window. Keep it simulation-only and forbid use while disconnected.
Add a Qt/QML binding regression for visibility/availability and preserve the
existing close guard. Then run one fresh tagged GUI pass: restore the simulator
through this action, verify first-contact ring/crosshair and labeled hazard
details, invoke `Export evidence…`, verify JSON+Markdown output and success
feedback, disconnect, and exact cleanup. Do not claim PASS without those
observations. No hardware, physical transport, non-loopback endpoint, or
unrelated Pine instance is permitted.

## Sol review delta — headless-first collision stabilization (2026-09-07)

Repeated P0 GUI attempts are suspended until the complete public-interface
collision lifecycle is deterministic headlessly. Evidence shows a fresh
collision-only runtime can emit `ALARM:1` shortly after connection at the
initial zero pose, while another run reaches the job and then becomes
non-responsive. Source review shows hazards may be emitted on every telemetry
snapshot and runtime interlock deduplication keys include `time_ns`, so one
persistent contact can become an unbounded stream of nominally unique hazards.
The bounded 256-event UI poll is retained but is not sufficient by itself.

Luna must execute the P1 public-interface backend scenario harness before any
more GUI work. The harness must drive the production application/controller and
loopback twin boundaries through connect, initial idle, reference, safe-Z,
work-zero, generated collision-only STEP load/start, first contact, interlock,
failed job, export, disconnect, and owned-process cleanup. It must prove no
startup/setup false alarm, exactly one stable first-contact incident per
continuous hazard episode, bounded queues/event history, responsive application
state, correct machine/work/WCO transforms, and deterministic replay. Diagnose
and fix collision arming/transition semantics and supervisor/runtime hazard
latching at the architectural layer rather than adding GUI delays or weakening
collision coverage. Add focused unit tests for stationary/continuous contact
and an end-to-end regression for the full lifecycle. Run affected simulation
and application suites. Commit and push this harness/stabilization as its own
backlog item only after Sol review; then resume P0 with one fresh GUI acceptance
pass and a separate commit/push for the completed acceptance item.

## Sol program delta — independent virtual operator package (2026-09-07)

Continue backend-first while the narrow P0 GUI visualization/export gate awaits
one uninterrupted acceptance pass. Luna must implement the next coherent P1
package: an independent virtual operator/safety actor that consumes immutable
machine snapshots and user-intent events, independently recomputes travel,
fixture, stock, holder, spindle, frame, and stalled-motion hazards, and emits
typed hold/abort/interlock intents with reasons. It must not call production
collision-result functions or share mutable oracle verdict state. Integrate it
through the existing supervisor/runtime public boundary, preserve fail-closed
behavior, and add deterministic tests for disagreement detection, intent
ordering, stale snapshots, supervisor failure, and recovery authorization.

Run focused supervisor/runtime/application tests, all simulation tests, and a
deterministic multi-seed scenario corpus. Review staged scope, exclude generated
evidence/config and `%SystemDrive%`, then commit and push this package as its
own checkpoint only after Sol review. No GUI, hardware, physical transport,
non-loopback endpoint, or physical A/B commissioning is needed for this item.

Sol review requires one integration correction before this package can be
committed: the supervisor API accepts an explicit `backend_hazards` verdict,
but the spawned backend currently does not publish one, so disagreement
detection is only unit-tested. Add a backend-owned independent hazard
assessment to telemetry, with consistent machine/WCO transforms and no calls
to the operator or shared mutable verdict state. Exercise explicit empty and
non-empty disagreement through the production boundary and prove the resulting
divergence/interlock does not deadlock. Re-run the operator, spawn, public,
application, and simulation gates before Sol review and commit/push.

## Sol program delta — collision and coordinate-frame hardening (2026-09-07)

The next backend-first package is the scheduled P1 collision/frame hardening
item. Luna must audit and correct the shared machine/work/WCO transform and
the independent backend/operator swept-collision semantics without weakening
coverage or adding GUI timing work. Use explicit immutable frame helpers so
stock, fixtures, bed, tool, holder, and machine-frame proxies all agree on
the positive-up GRBL convention and non-zero X/Y/Z work offsets. Cover fast
linear and G17/helical arc sweeps, boundary contact versus penetration,
rapid-stock entry, spindle-off entry, holder/fixture/bed contacts, excessive
depth, retained-material gouge, and valid spinning-tool removal. Preserve
authoritative travel limits and ensure a hazard cannot be hidden by a frame
translation or by endpoint-only sampling.

Add deterministic unit and production-boundary regressions for zero and
non-zero WCO, shifted workpieces, every axis boundary, swept tunneling, arc
interpolation, stationary/continuous contact latching, and backend/operator
semantic parity. Run focused collision/geometry/stock/operator tests followed
by the affected simulation, public-scenario, application, and spawn-worker
groups. Record exact evidence, review staged scope, and commit/push this
package as its own checkpoint. Do not launch GUI, access hardware, select
USB/COM/Wi-Fi, or stage generated/config/evidence artifacts.

## Sol replan delta — homing sensors, E-stop handling, and automated XYZ datum (2026-09-07)

The user has materially expanded the backlog with three safety-critical
capabilities. This section supersedes any earlier statement that homing
switches or XYZ fixtures are hidden or unimplemented. Work remains backend-
first and simulation-only until a separate commissioning authorization.

### Package H1 — explicit homing/limit capability and digital-twin sensors

Audit the existing machine-definition, commissioning, GRBL adapter, controller,
and setup UI paths. Extend the versioned machine schema (with migration and
fingerprint invalidation) so X, Y, and Z independently declare a homing/limit
switch, input pin, active-low polarity, home end (default `min`, with explicit
`max` support), and hard-limit behavior. Preserve the 3018 travel defaults
(290/170/40 mm) and the ability to leave every optional capability disabled.
Expose the declarations and commissioning state publicly; do not silently
assume a switch exists because a pin is reported.

Extend the virtual plant/controller so each axis has deterministic switch
activation at the configured machine-frame end, applies polarity consistently,
reports GRBL `Pn:X/Y/Z` inputs, models `$22` homing enable, `$23` homing-direction
mask, `$5` limit polarity, and `$21` hard-limit enable where supported, and
keeps homing acknowledgement separate from motion completion. A configured
minimum-end switch must home toward zero; a maximum-end switch must home toward
the configured travel. A hard-limit transition during ordinary motion must
stop motion, emit a stable alarm, and invalidate reference; a homing cycle must
only trust a fresh Idle report after the expected switches and direction are
observed. Wrong polarity, missing axis, simultaneous unexpected inputs,
switch chatter, travel overshoot, and reset during homing fail closed.

Add a deterministic commissioning workflow for testing X/Y/Z inputs one at a
time (inactive -> active -> released), direction/end review, and a homing
cycle. Store machine-scoped evidence and stale it when switch geometry,
polarity, pin, controller, or travel changes. Add focused unit, controller,
runtime, public-scenario, and property tests for every axis, both ends,
active-high/active-low, hard-limit versus homing semantics, and no physical
factory calls.

### Package H2 — hardware-safe emergency-stop contract

Add a versioned E-stop capability definition and commissioning record. Model
the real safety boundary explicitly: a safety-rated power cutoff remains the
primary protection; a GRBL reset pin may stop the controller but may provide no
feedback, so an optional feedback input is required if the application must
display a confirmed physical E-stop state. Support disabled, reset-only,
feedback-only, and reset-plus-feedback declarations with active-low polarity,
debounce, latching, and an explicit manual-reset/re-reference requirement.

Through the production controller boundary, an E-stop event must immediately
stop scheduling, request spindle-off/hold when possible, clear or abort the
active job, latch an interlock, invalidate reference and work-zero trust, and
block all motion, probing, homing, and restart commands until the input is
released, the controller is known Idle, and the user performs an explicit
reset/re-reference acknowledgement. Treat GRBL reset banners, alarm responses,
feedback pin transitions, timeout, and contradictory signals as fail-closed.
Never claim software E-stop equivalence to a safety-rated circuit and never
emit a physical reset or GPIO action from the twin by default.

Extend the digital twin with deterministic E-stop injection and telemetry,
including spindle-off, queue/process cleanup, stable alarm/interlock evidence,
manual recovery, and replay. Add regression tests for idle, jog, probing,
homing, active job, pause/resume, alarm, disconnect, reset, feedback polarity,
debounce/chatter, missing feedback, and recovery ordering. Add a concise wiring
and commissioning document that calls out reset-pin caveats and requires
physical power removal to remain reachable.

### Package H3 — automated XYZ calibration-plate work-zero workflow

Keep the existing manual `Zero X`, `Zero Y`, `Zero Z`, and `Zero XYZ` actions.
Add a separate, explicitly selected `Auto XYZ calibration plate` workflow;
never replace or silently reinterpret the manual buttons. Define a versioned
calibration-plate geometry containing the square plate datum, corner-circle
center/radius or diameter, plate thickness, tool-radius compensation,
clearance/safe-Z, search margins, fast/slow feeds, repeatability tolerance,
maximum XY/Z travel, and the conductive probe input/polarity. Require a
machine-scoped input/geometry commissioning record before enabling it.

The safe state machine is: trusted homed/reference state (automatic `$H` when
commissioned, otherwise an explicit manual reference) -> spindle off and Idle
-> user places the tool tip inside the known corner circle and confirms the
starting pose -> retract to safe Z -> perform bounded, low-speed orthogonal
edge searches (or a declared camera-assisted equivalent when that capability is
actually available) to collect at least four contact points -> solve the circle
center with tool-radius compensation and a deterministic residual/repeatability
check -> verify the solved center and all moves remain inside the 3018 envelope
and outside the forbidden holder/plate regions -> move to a validated point
outside the circle -> perform the existing two-stage Z touch sequence -> set
only the intended G54 X/Y/Z work offset after fresh reports confirm it ->
retract to safe Z and optionally return to reference/work zero. The initial
pose is an interior seed, not evidence of the center; without an available
contact or vision signal the workflow must refuse to guess.

Every segment must be collision/swept-path checked by the twin and the
independent operator. Unexpected contact, no-contact timeout, out-of-envelope
search, radius/residual mismatch, active spindle, stale WCO, plate-removal
acknowledgement, E-stop, switch alarm, supervisor loss, or any uncertain state
must stop, retract only when proven safe, latch an alarm/interlock, and leave
work zero unconfirmed. Record a typed trace containing seed pose, contact
points, fitted center/residual, compensation, Z triggers, generated commands,
hazards, and final WCO; export JSON and Markdown evidence.

Add deterministic geometry/state-machine tests for ideal and noisy circles,
tool-radius offsets, interior seeds near each quadrant, insufficient search
space, wrong plate size, missing/stuck/inverted probe input, failed contact,
holder/fixture/bed collisions, switch/E-stop interruption, stale WCO, and
replay-stable successful and failed runs. Exercise the complete public
loopback twin boundary and verify no USB/COM/Wi-Fi or non-loopback endpoint is
selected.

### Package H4 — public UI, documentation, and evidence gates

Expose H1/H2/H3 through the existing public view-model/QML boundaries with
clear capability-gated controls, per-axis switch end/polarity, homing and
E-stop commissioning status, manual-versus-automatic work-zero choice,
progress/abort/recovery messaging, and a simulator overlay that shows switch
states, E-stop latch, circle geometry, contact points, fitted center, Z-touch
path, hazards, and final verdict. Keep all physical controls disabled until
their evidence is current. Update README and dedicated commissioning docs
with the exact physical prerequisites and no-hardware simulation procedure.

Validation order for each package is targeted static/compile checks, focused
unit tests, affected simulation/controller/application tests, deterministic
multi-seed/property and replay tests, then one concise public UI acceptance
pass. Review staged files and exclude generated evidence, runtime config,
`%SystemDrive%`, credentials, and unrelated user changes. Commit and push each
package separately to the tracked branch, confirm the remote commit, and
update `EXECUTION_RESULT.md` with exact commands, counts, digests, and any
remaining GUI or physical-commissioning gap. Do not access real hardware or
perform a physical A/B run.

## Sol replan delta — production calibration execution and safety control plane (2026-09-07)

The H1-H4 checkpoint provides the safety contracts and deterministic plan
helpers, but Sol review finds one material end-state gap: the automated XYZ
workflow is not yet executed through the production application/controller and
the twin's ordinary GRBL probe boundary. The next coherent package is H5.

### H5.1 — public safety control plane

Expose versioned homing/limit declarations, commissioning evidence, E-stop
status/release/acknowledgement, and simulation sensor injection through the
existing ApplicationController/ViewModel public methods. Preserve the physical
capability gate: no declaration or simulated telemetry may imply that a real
switch, reset pin, GPIO, or safety-rated cutoff exists. Add deterministic
headless Qt/application tests for disconnected/connected, active/released,
stale/invalidated evidence, and every recovery rejection path. Keep physical
transport factories untouched and disabled by default.

### H5.2 — ordinary-protocol calibration execution

Add a production application service/state machine that consumes the existing
`CalibrationPlateDefinition` and `AutoXYZCalibrationWorkflow` plan through the
same `send_manual`/response/status boundaries used by physical GRBL. It must
sequence: trusted reference and Idle/spindle-off gate; safe-Z retract; four
bounded orthogonal `G38.2` searches; ordered `[PRB:...]` contact responses;
circle fit/residual and tool-radius validation; safe outside-circle witness
move; existing two-stage Z probe; intended G54 update; fresh WCO confirmation;
safe retract and explicit plate-removal acknowledgement. Manual Zero actions
remain unchanged.

Every command must be acknowledged and motion/status-complete before the next
stage. Abort, alarm, E-stop, limit input, no-contact, timeout, malformed probe,
stale WCO, supervisor loss, or collision must stop the transaction, request
spindle-off/hold where possible, leave work zero unconfirmed, and expose a
typed failure reason and replayable trace. No direct simulator-state mutation
is allowed.

### H5.3 — twin geometry and production-boundary fixtures

Extend the virtual GRBL plant/controller with an optional conductive corner
circle/plate geometry. During ordinary `G38.2` X/Y motion, the twin must stop at
the first swept tool/plate contact, emit the same ordered `[PRB:x,y,z:1]`
response as a real controller, and report failure when the bounded search does
not contact. Preserve normal Z-surface probing, spindle, WCO, limits, and
collision/operator semantics. Geometry must be explicit, versioned, and inert
unless a simulation fixture is supplied.

Add deterministic loopback tests for ideal/noisy fits, all four search
directions, tool-radius and WCO transforms, successful end-to-end calibration,
wrong plate/insufficient search/no-contact, probe polarity, limit/E-stop/
collision interruption, ordered acknowledgements, stale WCO, plate removal,
replay digest, and exact process cleanup. At least one test must drive the
ApplicationController over the loopback runtime rather than calling the
workflow helper directly.

### H5.4 — validation and checkpoint

Run focused calibration/control-plane tests, then affected simulation,
application, spawn-worker, and Qt shell tests; run compileall and diff checks.
Review only intended source/tests/docs, exclude generated/config/evidence and
`%SystemDrive%`, commit and push H5 as a separate checkpoint, and append exact
evidence to `EXECUTION_RESULT.md`. Do not launch the GUI after source changes,
access hardware, select USB/COM/Wi-Fi, or use non-loopback endpoints.

## Sol program delta — synthetic A/B commissioning plan and fixtures (2026-09-07)

The final scheduled package is a P3 synthetic twin-versus-controller A/B
commissioning plan. Luna must keep physical access inert while adding a
versioned, machine-readable commissioning script/fixture set that can run the
same bounded read-only, tiny-jog, WCO, probe, spindle, and optional cutting
gates against two explicitly supplied capture providers. Normalize only
declared firmware/hardware noise, preserve ordering and semantic differences,
apply documented position/feed/spindle/timing tolerances, and report every
ignored field, missing/extra response, outlier, and first divergence. The
physical provider must require separate explicit authorization and an exact
endpoint; no default or discovery path may touch USB/COM/LAN hardware.

Add synthetic twin and fake-controller fixtures covering matched traces,
tolerated numeric/timing drift, semantic mismatch, malformed captures,
unexpected alarm, WCO mismatch, missing response, and abort criteria. Provide
replayable JSON/Markdown reports and a preflight checklist that makes physical
emergency-stop, spindle-off, workholding, and trusted-reference requirements
explicit without executing them. Run focused parity/fixture tests followed by
affected simulation/application gates, record exact evidence, review staged
scope, and commit/push this package separately. Do not launch GUI or access
hardware, USB/COM/Wi-Fi, non-loopback endpoints, or stage generated/config/
evidence artifacts.

## Sol program delta — long-duration randomized/property testing (2026-09-07)

The next backend-first P2 package is long-duration randomized/property
testing. Luna must build a deterministic seeded scenario corpus (using the
virtual clock and no external randomness) that exercises mixed XYZ moves,
arcs, jogs, holds/resumes, resets, spindle/probe transitions, WCO changes,
fault injections, collision contacts, queue backpressure, disconnects, and
recovery attempts over long traces. Prefer property-style invariant checks
that remain valid for every seed: positions stay finite, travel and planner
capacity are never silently exceeded, FIFO/ack ordering is preserved, status
coordinates remain internally consistent, hazards latch/clear deterministically,
stock volume is bounded and monotonic, process/queue cleanup completes, and
replay digests are stable.

Add a compact CI-friendly seed set plus stress-depth controls, shrinking or
first-failure reports with seed/step/action context, and replay artifacts for
any failing case. Run focused randomized/property tests repeatedly, then the
affected simulation/application/public/spawn gates; record exact seed corpus
and evidence, review staged scope, and commit/push this package as its own
checkpoint. Keep all execution headless and simulation-only; do not launch
GUI, access hardware, select USB/COM/Wi-Fi, or stage generated/config/evidence.

## Sol program delta — QML/frontend verification (2026-09-07)

The next package is the scheduled P3 frontend verification pass. Luna must
audit the Qt/QML bindings and headless shell tests against the now-complete
backend contracts: simulation-only connection visibility, simulator restore
availability, hazard ring/crosshair and labeled details, stock metrics,
operator/interlock notices, pause/resume/abort state truthfulness, evidence
export success/failure feedback, disconnect cleanup, and the simulator close
guard. Keep all behavior routed through public ViewModel/ApplicationController
methods; QML must not own transport, plant, collision, or filesystem state.

Add deterministic Qt binding regressions for connected/disconnected and
running/hold/alarm/failure states, operator intents, export affordances,
window visibility/activation, bounded event polling, and stale-state cleanup.
Use mocked/headless surfaces for bulk coverage. A GUI pass is optional only as
a concise milestone observation; do not claim the unresolved P0 visual/export
acceptance gate is closed without fresh tagged first-contact visualization,
evidence export, and exact cleanup. Run focused Qt/shell/application tests,
record evidence, review staged scope, and commit/push this package separately.
No hardware, physical transport, non-loopback endpoint, unrelated Pine window,
or generated/config/evidence staging is allowed.

## Sol program delta — STEP stock-removal fidelity (2026-09-07)

The next backend-first P2 package is executed stock/STEP fidelity. Luna must
audit the bounded `StockModel` and isolated STEP import path so the selected
workpiece has an explicit work-frame placement, declared resolution/cell
budget, and a deterministic target height field when the geometry is a
supported planar 2.5D fixture. Executed removal must use the accepted TCP
motion path, spinning cutter state, and swept cutter footprint—not the
planned path or a GUI preview. Report removed, remaining, uncovered, gouged,
undercut/overcut, and collision-only status with stable volumes and tolerances;
retain islands and reject unsupported arbitrary 3D removal claims.

Add deterministic tests using `examples/showcase-pocket-island.step` for
import/placement, target generation, pocket/island retention, valid cutting,
spindle-off/rapid/deep/wrong-tool rejection, partial-cell boundaries,
resolution/cell-budget limits, and replay-stable stock metrics. Exercise the
production loopback path for at least one accepted cutting segment and verify
backend/operator hazards remain frame-consistent. Run focused STEP/stock
tests followed by affected simulation/public/application/spawn gates, record
exact evidence, review staged scope, and commit/push this package as its own
checkpoint. Keep it headless and simulation-only; no GUI, hardware,
USB/COM/Wi-Fi, or generated/config/evidence artifacts.

## Sol program delta — fault injection and recovery (2026-09-07)

The next backend-first P2 package is deterministic fault injection/recovery.
Luna must make the existing `SimulationFault` hooks usable through the
headless/runtime boundary, with explicit scope, sequence/time matching, and
safe clearing. Cover delayed, missing, duplicate, and error acknowledgements;
malformed/stale status; frozen motion; supervisor/backend heartbeat loss;
telemetry overflow; disconnect/reconnect; reset/alarm; changed WCO; probe
failure; spindle-delay; and fragmented/partial TCP. Every injected fault must
produce truthful application/job state, bounded fail-closed interlock or
recovery behavior, and replayable trace evidence—never silent success.

Add deterministic tests for each fault class, combinations and ordering,
mid-job and final-drain failures, supervisor failure/restart authorization,
explicit recovery token/fresh-safe-sample requirements, queue/process cleanup,
and deterministic replay across seeds. Verify real transports are not
selected and recovery cannot issue motion until safety state is re-established.
Run focused fault/controller/job/runtime tests followed by affected
simulation/application/public/spawn gates, record exact evidence, review
staged scope, and commit/push this package as its own checkpoint. No GUI,
hardware, USB/COM/Wi-Fi, non-loopback, or generated/config/evidence staging.

## Sol program delta — GRBL/DLC32 protocol-fidelity expansion (2026-09-07)

The next backend-first P1 package is protocol fidelity. Luna must audit the
virtual controller and parser against the commands Pine actually emits and
the DLC32-compatible wire contract, then close deterministic gaps without
reusing Pine's outbound builders or bypassing the ordinary TCP reader. Cover
fragmented/partial lines, comments and malformed/nonfinite words, realtime
bytes interleaved with normal input, startup/reset/alarm/unlock transitions,
system queries/settings/WCS/TLO/probe reports, modal changes, linear/arc/
helical/jog motion, spindle ramping, planner/RX `Bf` accounting, and ordered
acknowledgement/error behavior. Preserve the distinction between command
acceptance and motion completion, FIFO planner admission under backpressure,
and deterministic fault hooks for delayed/missing/duplicate/error ack,
malformed status, reset, frozen state, and fragmented transport.

Add protocol-level and spawned loopback regressions that assert exact line
framing/order, realtime responsiveness, status consistency (`MPos`, `WPos`,
`WCO`, `FS`, `Pn`, `Bf`), probe success/failure ordering, modal/WCO/TLO
round-trips, planner capacity bounds, and fail-closed behavior for invalid or
unsupported input. Run focused parser/controller tests, then affected
simulation/application/spawn/public suites. Record exact evidence, review
staged scope, and commit/push this package as its own checkpoint. Keep all
validation headless and simulation-only; do not launch GUI, access hardware,
select USB/COM/Wi-Fi, or stage generated/config/evidence artifacts.

## Sol program delta — deterministic evidence and replay (2026-09-07)

The next backend-first P2 package is evidence/replay completeness. Luna must
audit `TraceRecorder`, scenario results, and the verification CLI so a run
captures the semantic command/response, modal, planner, status, motion,
spindle, stock, hazard, supervisor-heartbeat, fault, intent, and final-state
events needed to reproduce a failure. Keep canonicalization explicit and
stable: normalize only declared environment noise, preserve ordering and
payload meaning, validate schema/version/contiguous sequences on load, and
make digest computation independent of wall-clock, PID, or loopback-port
noise. Add a deterministic replay API/CLI that re-runs a stored scenario or
trace under the same profile/seed and reports the first semantic divergence,
not just a boolean.

Add tests for round-trip JSON/Markdown evidence, malformed/truncated/schema
rejection, canonical digest stability, first-difference reporting, replay of
all built-in scenarios and seeded fault cases, and evidence boundedness during
long runs. Preserve the existing no-hardware parity guard. Run focused
trace/verify/scenario tests followed by affected simulation/application/public
gates, record exact evidence, review staged scope, and commit/push this
package as its own checkpoint. Do not launch GUI, access hardware, select
USB/COM/Wi-Fi, or stage generated/config/evidence artifacts.

## Sol replan delta — public safety commissioning and Auto XYZ controls (2026-09-08)

The backend safety contracts are present, but the public surface still hides
the capability that the requested workflow needs: `MachineSetupDialog.qml`
describes homing/limit switches and XYZ fixtures as temporarily unimplemented,
`simulation_auto_xyz_available` is hard-coded false, and the Auto XYZ preview
button has an empty handler. This package closes that architectural boundary
without any GUI launch or physical transport access.

### H6.1 — explicit homing/limit configuration through public application APIs

Add a validated ApplicationController/ViewModel boundary for per-axis
homing/limit declarations: switch enabled, minimum/maximum home end, input pin,
active-low polarity, hard-limit behavior, debounce, and optional measured
maximum. Keep the existing 3018 travel defaults and `MachineDefinition`
fingerprints authoritative. When connected to a real controller, apply only
the ordinary GRBL `$5/$21/$22/$23` settings after Idle and preserve the
no-motion/physical-safety gates; when disconnected, persist the declaration for
later commissioning. The digital twin must receive the same declaration through
its existing runtime control boundary. No physical factory, discovery, COM,
USB, Wi-Fi, or non-loopback endpoint may be selected by tests.

### H6.2 — commissioned simulation plate and public Auto XYZ workflow

Expose an explicit simulation-only calibration-plate fixture using the existing
`CalibrationPlateDefinition`, `CalibrationCommissioningRecord`, and
`ProbeCornerCircle` contracts. A fresh twin may offer Auto XYZ only when the
fixture is present and its machine-scoped commissioning record is valid; a
physical connection must remain unavailable until a real commissioning record
exists. Provide a public dialog/control that accepts the user's interior seed
pose, shows the bounded search/safe-retract/Z-touch plan and typed state, starts
and aborts through the existing ApplicationController methods, and never emits
raw plant mutations or motion from QML. Preserve the separate manual Zero X/Y/Z
and Zero XYZ buttons.

### H6.3 — headless verification and checkpoint

Add deterministic tests for declaration persistence/validation, per-axis
polarity/end/pin mapping, GRBL setting application and Idle gating, simulation
projection/cleanup, Auto XYZ availability gating, seed validation, start/abort
and fail-closed interlocks, and QML bindings/action enablement. Include at least
one ApplicationController loopback calibration through the public ViewModel
boundary. Run focused config/application/Qt tests, affected simulation and
spawn-worker tests, compileall, and the full suite; record exact evidence in
`EXECUTION_RESULT.md`, review staged scope, and commit/push this package
separately. Do not launch/relaunch the GUI after source edits, access hardware,
or stage generated/config/evidence artifacts. A fresh manual GUI relaunch is
still required later for the native visual/export gate.

## Sol replan delta — public digital-twin E-stop and limit exercises (2026-09-08)

The safety engine and ViewModel already implement simulation E-stop release,
acknowledgement, and per-axis limit-input injection, but the public simulator
card currently exposes only status labels. Add the missing test controls so a
developer can exercise the same fail-closed paths without hardware.

### H7.1 — simulation-only safety exercise controls

Expose guarded controls through ApplicationController/ViewModel/QML for
asserting the twin E-stop (reset input and/or electrical feedback according to
the configured mode), releasing the input, acknowledging recovery only after a
fresh trusted reference, and toggling X/Y/Z limit inputs. Show the latched,
released, acknowledged, and active-pin states with clear simulation-only
labels. Controls must be hidden or disabled while disconnected or on a physical
transport, route only through existing public methods, and never emit physical
reset/GPIO/transport traffic.

### H7.2 — tests and checkpoint

Add deterministic ViewModel/QML and loopback tests proving E-stop assertion
aborts/invalidate motion and reference, limit toggles reach the twin sensor
bank, recovery remains blocked until release plus fresh reference/acknowledge,
disconnect clears stale UI state, and the physical transport remains untouched.
Run focused safety/H6/Qt/spawn tests, compileall, and the full suite; append
exact evidence to `EXECUTION_RESULT.md`, review scope, and commit/push H7.
Do not launch the GUI after source edits, access hardware, select USB/COM/Wi-Fi,
or stage generated/config/evidence artifacts. The native visual/export gate
remains a later manual relaunch requirement.

## Sol review delta — seed persisted homing declarations at twin startup (2026-09-08)

H7 correctly routes declaration edits through the active runtime, but the
default `ApplicationController` simulation factory still constructs a fresh
twin with its generic default sensor profile. Before the next session starts,
seed the default `SimulationRuntime` with the selected machine's validated
`homing_limit_profile`; retain the existing explicit runtime reconfiguration
path and custom simulation-factory compatibility. Add a regression that saves
non-default X/Y/Z declarations, reconnects the twin, and proves the spawned
controller reports the same ends/polarity/pins without any physical factory
call. Run the focused H7/loopback/spawn tests and full suite, append evidence,
commit, and push this correction. No GUI relaunch, hardware, physical
transport, or generated/config/evidence staging is allowed.
