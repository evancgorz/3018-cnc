# Execution Result

## Status

PARTIAL — implementation, automated gates, fresh tagged digital-twin launch,
and normal cleanup completed. The remaining STEP-run GUI scenarios could not
be completed because the native file chooser did not surface after the
observed `Import STEP file…` action; no untrusted or terminal shortcut was
used to bypass that gate.

## Implementation and automated evidence

- Corrected simulation G10 L20 semantics so `WCO = machine_position -
  requested_work`, preserving the authoritative machine/work relationship.
- Added live WCO acknowledgement tracking in the application controller,
  including fresh matching reports, reconnect restoration, partial-axis
  matching, and clearing on error/disconnect/reset.
- Updated GUI validation manifests so physical sentinels cover only immutable
  connection/machine/profile/work-zero/z-touch inputs; mutable isolated
  `step-prepare.json` and `simulation.json` remain outside the sentinel set.
- Targeted WCO/generated-STEP/restoration gates: **all passed** (48 targeted,
  3 live-WCO, 4 restoration/WCO tests).
- Affected full coverage gate: **416 passed in 161.26s**; combined coverage
  **96.30% line, 90.87% branch** across 17 parallel data files.
- Verification CLI: **5/5 scenarios**, schema/link validation PASS.
  Evidence root:
  `C:\Users\EVANGO~1\AppData\Local\Temp\pine-twin-evidence-wco-20260904-131813`
  - `summary.json` SHA-256:
    `923619841704bc7118051a1a2b321eaf0ba62d871d9a842e6ec334e6f1789a01`
  - `report.md` SHA-256:
    `fcf575edbdffc2ff56c5b5483e388230df641a4d1cd54dbdf627c695dbcc9cde`

## Fresh tagged GUI evidence

- Exact marker/title: `pine-twin-gui-86d8c4800220` /
  `Pine — pine-twin-gui-86d8c4800220`.
- Main window id: `11737262`; launcher wrapper PID: `21136`.
- Selected **Virtual Machine (Digital Twin)** at **10×** with job
  **Pocket + retained island**, then started the digital twin.
- Native simulator visibly reported **DIGITAL TWIN — NO PHYSICAL MACHINE**,
  **Supervisor: healthy**, **Authoritative plant**, `GRBL Idle`, and matching
  machine/work coordinates (`X2.00 Y0.00 Z0.00`).
- Established reference; performed the fine X+ jog and observed machine/work
  X advance to `2.00`; entered Prepare and opened **Guided STEP setup · 1 of
  4**.
- `Import STEP file…` was observed and clicked, but no native chooser became
  available. Therefore STEP start/pause/resume, collision-stop, and export
  outcomes are not claimed.

## Cleanup

- Disconnected the tagged digital twin through its native **Disconnect digital
  twin** control.
- Dismissed the resulting **Machine is not at reference** dialog with native
  **Close without moving**.
- Verified via the trusted window inventory that the exact tagged main window
  and simulator were gone; pre-existing Pine windows were not touched.
- Verified launcher wrapper PID `21136` no longer existed. No forced kill,
  hardware access, COM/USB access, non-loopback endpoint, or physical A/B
  commissioning occurred.

## Evidence references

- Contract: `.codex/sol-luna/EXECUTION_CONTRACT.md`
- GUI manifest:
  `C:\Users\EVANGO~1\AppData\Local\Temp\pine-twin-gui-86d8c4800220-5e3dovwx\gui-validation-manifest.json`
- Launch stdout:
  `C:\Users\EVANGO~1\AppData\Local\Temp\pine-twin-launch-wco-20260904-131837.stdout`

## Sol review delta — WCO lifecycle cleanup (2026-09-07)

- Removed the duplicate `__init__` initialization of
  `_work_zero_expected_offset` and `_work_zero_expected_axes`.
- `ApplicationController.disconnect()` and `reset()` now clear all three
  pending WCO acknowledgement fields: pending-ack, expected offset, and
  expected axes.
- Added a parameterized regression covering both lifecycle boundaries. It
  asserts all pending fields are cleared and that a stale matching WCO report
  cannot confirm work zero afterward.

Focused validation only (no full suite, coverage aggregation, CLI corpus, or
GUI rerun):

- `.venv\Scripts\python.exe -m pytest -q tests/test_application_contracts.py
  -k "stale_wco or confirmed_work_zero"` → **3 passed, 39 deselected in
  2.77s**.
- `.venv\Scripts\python.exe -m pytest -q tests/test_simulation_wco_live.py`
  → **3 passed in 16.73s**.

The unresolved STEP GUI disclosure above remains unchanged; no hardware,
physical transport, non-loopback endpoint, or GUI session was accessed for
this cleanup delta.

## Sol review delta — planner backpressure and post-stream motion control (2026-09-07)

- `VirtualGrblController` now retains planner-bound normal lines in an ordered
  deferred queue and admits them only as authoritative plant planner slots
  free. It never grows the plant queue beyond the configured planner capacity
  or emits a synthetic buffer-full response for ordinary backpressure.
- Realtime status, hold, resume, and soft reset remain handled immediately;
  soft reset clears partial-line, deferred-line, and delayed-ack state.
- `JobService` now exposes `draining` while all streamed lines are accepted but
  the controller has not reached Idle. Hold/resume remain accepted during that
  phase based on observed Run/Hold state. Application and Live projections use
  this state, so UI status does not claim Complete while motion remains.
- Added deterministic regressions for bounded planner depth, ordered deferred
  acknowledgement, realtime responsiveness, reset cleanup, long-stream final
  drain, and drain-phase pause/resume.

Focused validation only (no GUI, full suite, coverage aggregation, or CLI):

- `.venv\Scripts\python.exe -m pytest -q
  tests/test_simulation_controller_branches.py -k "planner_backpressure or
  reset_clears_deferred or streaming_waits"` → **3 passed, 10 deselected in
  0.13s**.
- `.venv\Scripts\python.exe -m pytest -q tests/test_application_contracts.py
  -k "job_service or job_completion or job_failure or unsafe_controller"` →
  **14 passed, 28 deselected in 0.39s**.
- `.venv\Scripts\python.exe -m pytest -q
  tests/test_simulation_controller_branches.py
  tests/test_simulation_core.py tests/test_simulation_spawn_workers.py` →
  **39 passed in 9.20s**.

The prior unresolved STEP GUI disclosure remains unchanged. One fresh final
GUI confirmation is still required by the contract; this correction pass did
not launch Pine or access hardware.

## Sol review delta — WCO collision frame and final GUI attempt (2026-09-07)

- Fixed the supervisor collision frame: imported workpiece stock bounds are
  translated by the live XYZ WCO before comparing against machine-coordinate
  telemetry. Stock-removal metrics use the same offset frame.
- Added a deterministic worker regression with machine Z30/work Z0 that
  descends into stock and requires the `spindle_off_entry` hazard.

Focused validation:

- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_spawn_workers.py
  -k "supervisor_worker"` → **2 passed, 6 deselected in 0.77s**.
- `.venv\\Scripts\\python.exe -m pytest
  tests/test_simulation_geometry_and_parity.py -k "geometry_world or
  stock_removal"` → **3 passed, 17 deselected in 0.28s**.

GUI evidence from owned tagged session `pine-twin-gui-2a784d23d263`:

- Public UI selected Virtual Machine (Digital Twin), 10×, Collision-only STEP;
  supervisor banner was healthy and the session used loopback endpoint
  `127.0.0.1:56170` only.
- Public Guided STEP imported `examples/showcase-mounting-plate.step`,
  generated and loaded `generated-step.gcode`; reference and work zero became
  ✓, with machine `Z30.00` and work `Z0.00`.
- Starting the public job exposed the defect: streaming continued without the
  expected translated collision alarm, and the exact tagged main PID became
  temporarily non-responsive. Normal close/abort requests failed. After
  re-verifying title, manifest ownership, and child PIDs, only the exact owned
  tree was force-terminated under explicit root authorization:
  main PID `21988`, child PIDs `19512` and `23904`. No unrelated Pine window was
  touched.

Fresh post-fix tagged session:

- Manifest:
  `C:\\Users\\EVANGO~1\\AppData\\Local\\Temp\\pine-twin-gui-cc7099328ce2-nzrfpg4n\\gui-validation-manifest.json`
- Marker `pine-twin-gui-cc7099328ce2`; physical sentinels remained unchanged,
  owned child PIDs stayed empty, and no loopback endpoint was opened before the
  user stopped Computer Use with the physical Escape key during 10× selection.
- Because the user stopped GUI control, collision/interlock visualization,
 GUI trace/evidence export, and final normal-close verification are **not
 claimed**. Overall status remains **PARTIAL**, not PASS.

## Sol program delta — bounded GUI collision retry (2026-09-07)

- Added a bounded `SimulationRuntime.poll()` drain (`MAX_EVENTS_PER_POLL =
  256`) so a fast digital-twin telemetry/hazard producer cannot monopolize the
  Qt event loop while an interlock is propagating. Added a regression proving a
  live queue remains responsive and is not drained without bound.
- Focused validation: `.venv\\Scripts\\python.exe -m pytest
  tests/test_simulation_spawn_workers.py -q` -> **9 passed in 1.70s**.

Fresh owned GUI marker `pine-twin-gui-d2c23c54f1e7` (manifest under
`C:\\Users\\EVANGO~1\\AppData\\Local\\Temp\\pine-twin-gui-d2c23c54f1e7-6d5h56lj`) was
configured through the public UI for VM/10x/Collision-only STEP, established
machine Z30/work Z0, imported `showcase-mounting-plate.step`, generated and
loaded the validated program, and started the public run. The run remained at
1% while streaming and became non-responsive before a visible hazard/alarm or
failed verdict; normal abort/close failed. Manifest/title/PID ownership was
re-verified and only that exact owned tree (main `16576`, children `3844,
15596`) was force-terminated. No unrelated Pine process was touched.

A second fresh owned marker `pine-twin-gui-bb86322f4749` was launched after
the bounded-drain repair. During rapid public setup, the controller entered
Alarm before the STEP import completed; the native chooser was dismissed and
the exact owned session was closed/verified absent (manifest main `22312`,
children `13988,12264`; no remaining matching process). This is setup-failure
evidence, not a collision verdict.

The required public first-contact visualization/interlock/failed-verdict
evidence export was therefore **not achieved**; no GUI trace/evidence export is
claimed. No hardware, USB/COM, non-loopback endpoint, or physical A/B
commissioning was used. Overall status remains **PARTIAL**, not PASS.

## Sol review delta — headless-first collision stabilization (2026-09-07)

Implemented the bounded P1 public-interface backend harness and collision
stabilization without launching Pine:

- Added `run_public_collision_lifecycle()` in
  `src/ttc3018_control/simulation/public_scenarios.py`. It drives the real
  `ApplicationController` → `ConnectionService` → loopback
  `TcpGrblConnection` → backend/supervisor path through initial Idle,
  reference, safe-Z, XYZ WCO, generated collision-only job, first contact,
  interlock/failure, evidence export, disconnect, and owned-process cleanup.
- Added Qt-independent controller adapters for bounded twin polling, canonical
  trace/evidence export, and application-boundary trace events.
- Supervisor collision episodes are now latched by semantic
  `(kind, body_a, body_b)` keys and re-armed only after a clear edge. Runtime
  latching uses the same stable key, bounds retained incidents to 256, and
  deduplicates queue-overflow/interlock reports. Supervisor output has its own
  bounded poll budget so heartbeats cannot be starved by telemetry.
- Backend telemetry is published at a bounded 20 Hz observation cadence,
  preventing redundant snapshots from filling the supervisor/owner queues.
  Startup/setup poses remain unarmed unless an active motion-state transition
  is present; stationary/continuous-contact and clear/rearm regressions cover
  the semantics.
- `JobService` now fails a job if Alarm/Door/Sleep arrives during the final
  controller-drain window after all lines have been acknowledged; normal GRBL
  pause/resume/drain behavior remains covered.

Fresh public lifecycle evidence (no physical factory calls, loopback only):

- Result: **PASS** — startup incidents `0`; first-contact incidents `1`
  (`spindle_off_entry`); job verdict `failed`; confirmed WCO `(0, 0, 30)`;
  evidence JSON and Markdown exported; exact backend/supervisor cleanup
  verified.
- Evidence: `.codex/sol-luna/headless_acceptance_run/test_public_controller_collisi0/evidence/collision.json`
  and matching `collision.md`.

Focused/affected validation:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_public_scenarios.py tests/test_simulation_spawn_workers.py tests/test_simulation_controller_branches.py -q` → **26 passed in 20.95s** (includes two full public lifecycle runs with matching semantic results).
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_wco_live.py tests/test_application_contracts.py -q` → **45 passed in 9.83s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_*.py -q` (PowerShell-expanded file set) → **85 passed in 43.74s**.
- Fresh evidence run with `--basetemp .codex\sol-luna\headless_acceptance_run` → **1 passed in 6.49s**.

This package was intentionally **not committed or pushed** pending Sol review.
The generated evidence directory and temporary simulation configuration are
untracked and must be excluded from any later package commit. No GUI, USB/COM,
hardware, non-loopback endpoint, runtime configuration, or physical A/B
commissioning was used; the live GUI acceptance gate remains unresolved.

## Sol review delta — P1 commit/push checkpoint (2026-09-07)

Sol independently reviewed the P1 public-boundary harness and collision/
backpressure corrections. The implementation uses the production
`ApplicationController` → loopback `TcpGrblConnection` → spawned backend and
independent supervisor boundaries; it does not reach into a plant or bypass
the public controller API. Hazard episodes are latched by semantic kind/body
identity, clear and re-arm on a genuine edge, and remain bounded. Runtime
telemetry publication is capped and poll budgets are split so supervisor
heartbeats and hazard responses cannot starve behind telemetry. Alarm reports
during the final controller-drain phase now fail the job even when all streamed
lines have already been acknowledged.

Sol reran the authoritative gates: **98 passed** across the public scenario,
spawn-worker, controller-branch, simulation-core, geometry/parity, and
application/WCO contract groups. Luna's retained acceptance counts remain 26
focused public/controller tests, 45 WCO/application tests, and 85 simulation
tests, with the deterministic public lifecycle passing twice. Results include
startup hazards `0`, exactly one `spindle_off_entry` incident, final job state
`failed`, WCO Z `30.0`, JSON+Markdown export, physical factory calls `0`, and
exact backend/supervisor cleanup.

Commit/push checkpoint:

- Commit `69bdfc3` — `Build hardware-free digital twin and public lifecycle
  harness`.
- Pushed successfully to `origin/main`.
- Generated evidence/config under `.codex/sol-luna/headless_acceptance_run/`,
  local `config/`, and `%SystemDrive%/` were explicitly excluded. No hardware,
  USB/COM, physical Wi-Fi, non-loopback endpoint, or physical A/B commissioning
  was used.

The P1 headless package is complete. P0 remains **PARTIAL** because the final
post-fix GUI collision visualization, GUI export action, and final tagged GUI
cleanup have not yet been observed. The next GUI run should be one concise
acceptance check against this passing headless lifecycle, followed by its own
reviewed commit/push.

## Sol review delta — simulator restore checkpoint and interrupted final GUI (2026-09-07)

- Restore affordance commit `a0702f0` was reviewed and pushed to `origin/main`;
  its focused Qt gate passed (`4 passed, 25 deselected`).
- A fresh tagged run `pine-twin-gui-c3519a5c93b1` independently proved the
  corrected public alarm path and exact cleanup, but the simulator could not be
  restored after minimization; no ring/details or GUI export claim was made.
- The subsequent final launch was stopped by the user's physical Escape key
  before UI control began. Exact tagged window `pine-twin-gui-142aa6aee490`
  (PID `9236`, no twin children) was re-identified and closed; no unrelated
  Pine window was touched. No hardware, USB/COM, non-loopback endpoint, or
  physical A/B was used.

P0 remains **PARTIAL**. The public collision/interlock/alarm and cleanup gates
are proven; first-contact visualization and GUI evidence-export observation are
pending one uninterrupted acceptance pass. Backend work may continue while
that narrow GUI gate is pending.

## P0 fresh tagged GUI acceptance — 2026-09-07

Fresh isolated validator:

- Marker: `pine-twin-gui-70089fdbe4be`
- Manifest: `C:\\Users\\EVANGO~1\\AppData\\Local\\Temp\\pine-twin-gui-70089fdbe4be-3hek7zug\\gui-validation-manifest.json`
- Main PID: `5792`; owned backend/supervisor PIDs: `13836`, `3784`
- Loopback endpoint: `127.0.0.1:63159`

Public UI evidence observed:

- Virtual Machine (Digital Twin) selected; physical transport fields were not
  used; persistent `DIGITAL TWIN — NO PHYSICAL MACHINE` banner shown.
- 10x and `Collision-only STEP` selected. The public Guided STEP flow imported
  `examples/showcase-mounting-plate.step`, generated and loaded
  `generated-step.gcode`, and showed the validated 290 x 170 x 40 mm profile.
- Machine reference became Trusted. Work zero was re-established at virtual
  machine Z6, yielding machine Z6/work Z0 and an in-envelope transformed job.
- Guided Run reached the public start confirmation, then visibly stopped with
  `Job stopped` / `ALARM:1` at machine `X8.46 Y5.72 Z25.24` (work Z -0.77),
  providing the alarm/interlock outcome for the collision-only path.

Limitations and cleanup:

- The simulator preview window was hidden after its earlier native minimize
  interaction, so first-contact visualization was not observed in this cycle.
- The current public QML surface exposes no trace/evidence export action (only
  validated G-code save); therefore GUI JSON/Markdown evidence export is not
  claimed. The headless public-boundary export remains the only export evidence.
- The exact tagged instance was disconnected through the UI and closed through
  the normal window close. Manifest ownership was rechecked; PIDs 5792, 13836,
  and 3784 were absent afterward. The log records physical factory calls `[]`.
  No hardware, USB/COM, non-loopback endpoint, or unrelated Pine window was
  accessed.
- The log contains two pre-existing QML warnings at `Main.qml:901`; no runtime
  error was introduced by this GUI cycle.

Overall P0 GUI status remains **PARTIAL**, not PASS: alarm/interlock and exact
cleanup passed, but first-contact visualization and GUI evidence export remain
unmet. No source/test files were changed and no commit/push was made.

## Sol review correction — simulation evidence and hazard UI surface (2026-09-07)

Implemented the bounded frontend correction after the tagged GUI run exposed
two missing public controls. The simulation-only simulator window now:

- Projects the active hazard kind, message, body pair, severity-safe XYZ point,
  and a clear `FIRST CONTACT — INTERLOCK ACTIVE` state from runtime hazard
  events; hazard clear edges remove the active projection.
- Draws a red first-contact ring/crosshair and `FIRST CONTACT` label at the
  authoritative machine XY point without driving simulation state.
- Exposes `Export evidence…` only while the digital twin is active. The native
  save dialog hands a selected path to `ControllerViewModel`, which records an
  application event and calls the existing `ApplicationController` JSON plus
  Markdown trace export boundary. Success and failure feedback are shown in
  the simulator and toast channel; physical transports are not involved.

Focused evidence:

- `.venv\\Scripts\\python.exe -m pytest tests/test_qt_shell.py -q` → **28
  passed in 13.77s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_qt_shell.py
  tests/test_application_contracts.py tests/test_simulation_public_scenarios.py
  -q` → **73 passed in 33.34s**.
- `git diff --check` passed. The diff is limited to
  `qt/view_model.py`, `qt/qml/Main.qml`, `tests/test_qt_shell.py`, and this
  result record. Existing generated evidence/config/unrelated files remain
  untracked and excluded.

No GUI was relaunched during this correction, no hardware/USB/COM/non-loopback
endpoint was accessed, and no commit or push was made pending Sol review.

## P0 final tagged GUI acceptance — 2026-09-07 (partial; evidence gap)

Fresh isolated validator against pushed commit `953b6b2`:

- Marker: `pine-twin-gui-c3519a5c93b1`
- Manifest: `C:\\Users\\EVANGO~1\\AppData\\Local\\Temp\\pine-twin-gui-c3519a5c93b1-8nopa319\\gui-validation-manifest.json`
- Main PID: `14792`; owned child PIDs: `15776`, `3692`
- Loopback endpoint: `127.0.0.1:50105`

Public UI gates observed:

- Virtual Machine (Digital Twin), 10x, and `Collision-only STEP` were selected;
  the public Guided STEP flow imported `examples/showcase-mounting-plate.step`,
  generated/loaded the validated G-code, established a Trusted virtual machine
  reference, moved to safe machine Z6, and confirmed work zero at Z0.
- The public guarded start path visibly produced `Job stopped` / `ALARM:1` at
  machine `X7.66 Y5.18 Z25.23` (work Z -0.77), with the main UI reporting the
  failed alarm/interlock outcome.

Evidence gap (not claimed as PASS):

- The simulator window had been natively minimized to reach the Guided STEP
  controls and could not be restored through the trusted UI surface after the
  alarm. Consequently, the first-contact ring/crosshair and labeled hazard
  kind/body/XYZ projection were not observed in this cycle.
- The simulator-only `Export evidence…` control and native save dialog were not
  reachable while that window was hidden; no GUI JSON/Markdown export is
  claimed and no evidence files were written by the GUI.
- The validator log records a `PermissionError [WinError 5]` while refreshing
  its temporary manifest at `18:47:00`; this did not prevent the main UI from
  reporting the alarm or the normal shutdown, but the manifest remains the
  original ownership record.

Exact cleanup/safety evidence:

- The owned tagged instance was disconnected via the public UI and normally
  closed. The trusted window inventory then contained no exact tagged window;
  exact PIDs `14792`, `15776`, and `3692` were absent. The log records
  `Simulation GUI validation physical factory calls: []`.
- No hardware, USB/COM, physical Wi-Fi, non-loopback endpoint, unrelated Pine
  window, runtime config, or repository evidence file was accessed or modified.

Overall status: **PARTIAL**. Public setup, alarm/interlock outcome, exact
cleanup, and no-physical-factory safety passed; first-contact visualization and
GUI JSON/Markdown export remain unobserved in this tagged run. No additional
source changes, commit, or push were made.

## Sol review correction — simulator restoration affordance (2026-09-07)

Implemented the bounded simulation-only restoration action requested after the
partial GUI run:

- Main connected UI now exposes `Show simulator` only when
  `appViewModel.simulation_active` is true. The action sets the owned simulator
  window visible, raises it, and requests activation; its function returns
  without changing state while disconnected.
- The existing simulator `onClosing` guard remains unchanged, including the
  refusal to close while a simulated job is active.
- Added a Qt/QML binding regression covering connected-only visibility, the
  guarded action, visibility/raise/activation calls, and preservation of the
  close guard.

Focused evidence:

- `.venv\\Scripts\\python.exe -m pytest tests/test_qt_shell.py -k "simulation" -q`
  → **4 passed, 25 deselected in 1.87s**.
- No GUI was launched in this correction, and no hardware, physical transport,
  non-loopback endpoint, or unrelated Pine instance was accessed.
- No commit or push was made; source changes are limited to the requested QML
  action and its focused test, with the existing generated/config files still
  excluded.

## P1 independent virtual operator package — 2026-09-07

Implemented the next headless-only supervisor package without launching GUI or
accessing physical transports:

- Added `simulation/operator.py` with immutable `OperatorFixture`,
  `OperatorIntent`, and `OperatorAssessment` records plus an
  `IndependentVirtualOperator` actor. It independently recomputes travel,
  frame, bed, stock, fixture, holder, spindle-off, excessive-depth, and stalled
  motion hazards from immutable snapshots and geometry proxies. It does not
  import or call `CollisionWorld.check_transition`, backend/controller,
  transport, Qt, or application code.
- Migrated `simulation/supervisor.py` to the independent actor while retaining
  the existing token/heartbeat/queue/process boundary and stock metrics. Actor
  outputs are typed `operator_intent` messages; the ViewModel routes hold and
  abort through public ApplicationController methods and reports interlock,
  recovery, and denial outcomes without direct plant mutation.
- Added explicit stale-snapshot and supervisor-failure fail-closed paths,
  deterministic hazard-edge deduplication, backend-verdict disagreement
  detection (including explicit empty verdicts), ordered hold/interlock/abort
  intents, and explicit recovery authorization requiring a fresh safe sample.
  Scenario/user intents are consumed by the independent actor in sequence
  before the raw public intent is forwarded.
- Added `HazardKind.STALLED_MOTION` and deterministic regressions for
  independent disagreement detection, intent ordering, stale snapshots,
  supervisor failure, recovery authorization, and the existing spawn/public
  supervisor paths.

Focused evidence:

- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_operator.py
  tests/test_simulation_spawn_workers.py tests/test_simulation_public_scenarios.py -q`
  → **17 passed in 20.16s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_application_contracts.py
  tests/test_job.py -q` → **52 passed in 0.66s**.
- All simulation/STEP test modules were run together (99 collected) after the
  actor migration; the run completed with no failure output. The targeted
  actor/spawn/public rerun above completed with exit code 0 after the final
  disagreement-semantics adjustment.
- Deterministic multi-seed corpus over built-in seeds `[1, 2, 3, 4, 5]` passed:
  `status`, `all_axis_motion`, `hold_resume`, `limit_alarm`, and `reset`, with
  stable trace digests for each result.

No commit or push was made pending Sol review. Generated evidence/config,
`%SystemDrive%`, credentials, GUI state, hardware, USB/COM, physical Wi-Fi,
non-loopback endpoints, and unrelated files remain excluded.

## H7 — public digital-twin E-stop and limit exercises (2026-09-08)

Implemented the public simulation-only safety exercise boundary without GUI
launch or physical transport access:

- The virtual controller now publishes one merged safety snapshot containing
  E-stop mode/active/latched/recovery state, symbolic reset/feedback pins,
  X/Y/Z logical limit states, Pn limit pins, and the `$23` homing position.
  Backend safety events use this snapshot for E-stop, release, acknowledge,
  and limit-input controls; a stable injected input is allowed to pass its
  declared debounce deterministically through the twin sensor bank.
- The default ApplicationController digital twin is configured with a
  symbolic reset-plus-feedback E-stop (`E`/`R`) only. Physical transports do
  not receive reset, GPIO, or limit traffic. Existing custom twin factories
  remain authoritative for explicit safety definitions.
- ViewModel exposes latched/released/acknowledged E-stop state, mode/pins,
  X/Y/Z limit state, Pn status, recovery readiness, and a guarded twin-only
  E-stop injection slot. Main.qml adds simulation-only reset/feedback assert,
  release, acknowledge-after-reference, and X/Y/Z limit toggles; all controls
  are hidden while disconnected and retain the no-physical-GPIO warning.
- Added loopback regressions proving E-stop assertion aborts/invalidate trust
  and work zero, release plus fresh reference plus acknowledge is required,
  X/Y/Z sensor input reaches the twin bank and clears, disconnect clears stale
  UI state, and forbidden physical factories remain untouched.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_h7.py -q`
  → **3 passed in 2.29s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_h7.py
  tests/test_simulation_h6.py tests/test_simulation_safety.py
  tests/test_qt_shell.py tests/test_simulation_spawn_workers.py -q`
  → **65 passed in 15.10s**.
- PowerShell-expanded simulation/application/STEP/job gate → **219 passed in
  74.49s**.
- `.venv\Scripts\python.exe -m compileall -q src tests` → **passed**.
- `.venv\Scripts\python.exe -m pytest -q` → **508 passed in 136.53s**.

No GUI was launched or relaunched; no hardware, USB/COM, Wi-Fi, non-loopback
endpoint, physical GPIO/reset, generated evidence, runtime config, or
protected `%SystemDrive%` artifact was touched. The native visual/export gate
remains a later manual relaunch requirement.

## QML warning audit — undefined STEP palette color (2026-09-07)

Audited the archived tagged-validator logs without launching or interacting
with any Pine instance. The historical logs consistently reported two copies
of `Unable to assign [undefined] to QColor` at `Main.qml:901:52` while the
STEP setup panel was created. The current source location is the STEP
operation delegate at `Main.qml:928`; it referenced `window.palette.elevated`,
but the shared palette declares `raised` and has no `elevated` key. This was a
real visual/QML defect (and not a digital-twin safety-state defect), so the
reference was corrected to `window.palette.raised`.

Added `test_main_qml_palette_references_are_declared`, which statically checks
that every `window.palette.*` reference in `Main.qml` is declared by the
palette. No GUI was relaunched for this audit; the archived warning is the
only runtime evidence, and a future clean validator run should confirm the
warning is absent.

Validation evidence:

- `.venv\\Scripts\\python.exe -m pytest -q tests/test_qt_shell.py -k
  "palette or simulation"` → **9 passed, 25 deselected in 1.17s**.
- `.venv\\Scripts\\python.exe -m pytest -q` → **500 passed in 133.89s**.

Only `Main.qml`, `tests/test_qt_shell.py`, and this result audit are in scope;
the contract, generated evidence, runtime/config files, `%SystemDrive%`, and
unrelated user work remain unstaged.

## H5 homing/E-stop/public auto-XYZ calibration — 2026-09-07

Implemented the H5 production-boundary slice headlessly, without GUI or
physical transport access:

- Added optional machine-frame `ProbeCornerCircle` geometry to the virtual
  plant/controller/backend. G38.2 X/Y now stops at the first swept circle
  intersection and emits the existing ordered `ok` then `[PRB:...]` response;
  Z surface probing, WCO, limits, and collision paths remain separate.
- Added runtime/application public methods for simulation-only homing profile
  and limit declarations, limit input injection, and conductive probe geometry
  configuration. Physical/disconnected paths fail closed and never emit GPIO,
  reset, USB, COM, Wi-Fi, or non-loopback actions. ViewModel/QML now project
  limit status and auto-XYZ transaction state alongside existing E-stop gates.
- Added `AutoXYZCalibrationService`, routed through ApplicationController
  `send_manual`, transport response, and status boundaries. It requires a
  current commissioning record and trusted Idle/spindle-off state, sequences
  bounded four-direction XY searches plus Z touch, waits for Idle boundaries,
  rejects no-contact/alarm/stale-WCO cases, requires a matching fresh WCO
  report after G10, and only completes after the final safe retract.
- Corrected the pre-existing calibration command plan to make modal distance
  explicit across probe/reposition transitions. Final retract uses a
  machine-safe delta after G10 rather than an unsafe absolute safe-Z target.

Validation evidence:

- `python -m compileall -q src/ttc3018_control` → passed.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_h5.py -q`
  → **4 passed in 2.80s**, including the real ApplicationController/TCP
  loopback calibration and exact disconnect cleanup.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_h5.py
  tests/test_simulation_safety.py -q` → **15 passed in 2.79s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_h5.py
  tests/test_simulation_safety.py tests/test_simulation_core.py
  tests/test_simulation_controller_branches.py tests/test_simulation_spawn_workers.py
  tests/test_qt_shell.py tests/test_application_contracts.py
  tests/test_homing_service.py tests/test_machine_config.py -q`
  → **152 passed in 19.23s**.
- `git diff --check` → passed.

No GUI, hardware, USB/COM, physical Wi-Fi, non-loopback endpoint, generated
evidence/config, `%SystemDrive%`, credentials, or unrelated files were staged.
The authoritative contract remains unmodified and is excluded from the H5
commit.

## H5 review correction — WCO confirmation transaction — 2026-09-07

Corrected the application boundary so calibration work-zero confirmation is
set only when `AutoXYZCalibrationService.observe_status()` consumes its pending
transaction on an Idle report whose WCO exactly matches the expected touch-point
offset. A stale/mismatched WCO leaves the transaction pending and work zero
unconfirmed; the matching fresh report confirms it. Added a regression covering
both outcomes.

Validation:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_h5.py
  tests/test_simulation_safety.py tests/test_simulation_core.py
  tests/test_simulation_controller_branches.py tests/test_simulation_spawn_workers.py
  tests/test_qt_shell.py tests/test_application_contracts.py
  tests/test_homing_service.py tests/test_machine_config.py -q`
  → **153 passed in 19.31s**.
- `python -m compileall -q src/ttc3018_control` and `git diff --check` passed.

## Sol independent review — H5 production calibration (2026-09-07)

Independent verification after the H5 correction passed:

- `tests/test_simulation_h5.py tests/test_simulation_core.py -k
  "calibration or estop"` → **2 passed, 25 deselected**.
- PowerShell-expanded simulation tests plus application, homing, machine-config,
  Qt shell, and H5 coverage → **238 passed in 81.98s**.

Remote `main` was confirmed at `3dd4382`. The remaining overall status is
**PARTIAL** only for the previously documented post-source-change GUI visual/
export acceptance and the intentionally deferred physical commissioning.

## Sol full-suite audit — 2026-09-07

The complete hardware-free repository suite was rerun after H5:

- `.venv\\Scripts\\python.exe -m pytest -q` → **499 passed in 137.32s**.

This confirms the H5 changes preserve the original application, protocol,
simulation, Qt-shell, and commissioning behavior. No physical transport or
non-loopback endpoint was selected.

## Sol read-only P0 GUI audit — 2026-09-08

No validator process or Pine window was available for observation. The current
headless/QML surface is ready for one concise manual acceptance: the simulator
canvas and labels expose the first-contact ring/crosshair, hazard kind/bodies/
XYZ/message, and the public export path normalizes JSON output and reports the
JSON/Markdown siblings. Existing Qt/headless tests cover those bindings and
export paths, but they cannot prove OS-window pixels, the native chooser, or
post-close process cleanup.

The remaining evidence is therefore unchanged and concrete: manually launch a
fresh tagged validator, run the collision-only or pocket/island public flow,
capture first-contact/interlock/alarm plus simulator visualization, export and
hash both evidence files, disconnect/close normally, and verify only the
manifest-owned PIDs/loopback endpoint changed while physical factories remain
unused. The overall status remains **PARTIAL** until those observations exist.

## H1-H4 homing, E-stop, and automated XYZ datum — 2026-09-07

Implemented the bounded safety-input package headlessly and simulation-only.
`simulation/safety.py` adds versioned machine-scoped per-axis declarations,
default-min homing ends with measured maximum overrides, active-low polarity,
input pins, hard-limit flags, debounce, profile fingerprints, migration, and a
debounced X/Y/Z sensor bank. `VirtualGrblController` exposes simulation
`$5/$21/$22/$23` semantics, sensor `Pn` telemetry, commissioned homing, and
fail-closed limit behavior without physical GPIO or reset access.

The E-stop contract supports disabled, reset-only, feedback-only, and combined
declarations with active-low polarity, debounce, latching, spindle/planner
stop, alarm reporting, and explicit release → Idle/unlock → re-reference
recovery. The twin injects these states in-process and emits no physical reset.
The automated XYZ workflow is separate from manual Zero actions, requires a
trusted reference, Idle/spindle-off state and an explicit interior seed, then
collects four contacts, fits a deterministic circle with residual checks and
tool-radius compensation, performs a fresh-WCO two-stage Z touch, and fails
closed on missing contacts, stale WCO, or envelope violations.

H4 public bindings now expose homing, E-stop, and automated-plate capability
status in the existing ViewModel/simulator surface. The automated workflow is
disabled until input/plate commissioning is current; no interior seed is ever
treated as a datum. Wiring caveats and an inert physical preflight checklist
are documented in `docs/SIMULATION_SAFETY_COMMISSIONING.md` and linked from
README.

Validation evidence:

- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_safety.py -q`
  → **8 passed in 0.19s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_safety.py
  tests/test_qt_shell.py -k "simulation_safety or simulation_hazard or
  simulation_show_action" -q` → **11 passed, 30 deselected in 1.97s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_safety.py
  tests/test_simulation_controller_branches.py tests/test_simulation_core.py
  tests/test_application_contracts.py tests/test_homing_service.py
  tests/test_machine_config.py tests/test_qt_shell.py -q` → **123 passed in
  23.96s**.
- `.venv\\Scripts\\python.exe -m compileall -q src tests` and `git diff --check`
  both passed.

No physical machine, GPIO/reset pin, USB/COM, Wi-Fi, LAN/non-loopback endpoint,
or new GUI validation was accessed for this package. Existing owned validator
state from the superseded GUI task was not interacted with by this package.
Generated evidence/config, `%SystemDrive%`, and unrelated dirty files remain
excluded. This package is ready for its separate safety checkpoint review.

## Sol independent review — safety checkpoint (2026-09-07)

The pushed safety checkpoints were independently reviewed after Luna's report:

- `tests/test_simulation_safety.py tests/test_simulation_spawn_workers.py
  -k "safety or production_boundary_homing"` → **12 passed, 11 deselected**.
- E-stop application and safety UI checks → **4 passed, 93 deselected**.
- Affected simulation/application/homing/config/QML set (PowerShell-expanded
  `tests/test_simulation_*.py` plus the affected application, homing, machine
  config, and Qt tests) → **230 passed in 79.78s**.

The new backlog contract was committed and pushed separately as `e0df1c7` after
review. No source/config/evidence artifacts are dirty; only pre-existing
untracked runtime/config artifacts remain preserved. The overall result stays
**PARTIAL** because the post-change public GUI acceptance and any physical
commissioning run were intentionally not performed.

### H1-H4 Sol review correction — production-boundary integration

The follow-up closes the review gaps without touching physical transports. The
spawned backend now receives the versioned homing profile and E-stop definition
through `SimulationRuntime`; its control boundary exposes deterministic limit
input, E-stop injection/release, and explicit Idle/unlock/re-reference
acknowledgement telemetry. `$23` applies X/Y/Z direction inversion, `$5`
inverts limit polarity independently of `$21` hard-limit alarming, and each
configured sensor drives deterministic `Pn` state. The application boundary
maps a latched twin E-stop to job abort, motion reset, reference/work-zero
invalidation, and a recovery gate; physical reset/GPIO remains inert.

The automated plate workflow now requires either an explicit commissioning
flag for simulation fixtures or a current `CalibrationCommissioningRecord`
fingerprinted to the plate geometry. It validates the interior seed against
the configured circle, emits four bounded orthogonal `G38.2` searches plus
safe-Z/retract/outside-circle witness moves, reports fitted and tool-radius-
compensated radius, and exposes typed `uncommissioned`, `seed_outside_circle`,
`no_contact`, `collision_interlock`, `estop_latched`, `stale_wco`, envelope,
and residual failure states. Manual work-zero actions remain separate.

Validation evidence for the correction:

- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_safety.py -q`
  → **11 passed in 0.12s**.
- `.venv\\Scripts\\python.exe -m pytest
  tests/test_simulation_spawn_workers.py -k production_boundary_homing -q`
  → **1 passed, 11 deselected in 0.76s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_core.py -k
  simulation_estop -q` → **1 passed, 21 deselected in 1.14s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_safety.py
  tests/test_simulation_core.py tests/test_simulation_spawn_workers.py
  tests/test_qt_shell.py tests/test_application_contracts.py
  tests/test_homing_service.py tests/test_machine_config.py -q`
  → **129 passed in 17.61s**.

Compile, diff, loopback-only process cleanup, and physical-factory sentinel
checks remain green; no GUI, hardware, USB/COM, Wi-Fi, non-loopback endpoint,
runtime config, generated evidence, or `%SystemDrive%` was accessed.

## P3 synthetic A/B commissioning plan and fixtures — 2026-09-07

Added a versioned, machine-readable synthetic twin/controller commissioning
plan at `examples/commissioning_ab_plan.json` and the inert implementation in
`simulation/commissioning.py`:

- The bounded plan defines read-only status, tiny-jog, WCO, probe, spindle, and
  explicitly optional cutting gates, with documented position/feed/spindle/
  timing tolerances and declared ignored hardware noise only.
- Supplied capture providers are compared in order while retaining tolerated
  numeric/timing drift as evidence. Reports identify malformed data, missing or
  extra events, outliers, semantic/WCO/probe differences, unexpected alarms,
  ignored fields, abort reason, and first divergence.
- Synthetic fixtures cover matched traces, tolerated drift, semantic mismatch,
  unexpected alarm, missing response, and malformed captures. Reports and both
  captures round-trip through replayable JSON/Markdown output with a stable
  digest.
- `PhysicalCaptureProvider` requires separate authorization plus an exact
  endpoint, then remains deliberately non-executable. The preflight checklist
  records emergency-stop, spindle-off, workholding, reference, endpoint, and
  abort requirements without performing any physical action.

Validation evidence:

- `.venv\\Scripts\\python.exe -m pytest tests/test_simulation_commissioning.py
  tests/test_simulation_geometry_and_parity.py -q`
  → **31 passed in 4.54s**.
- PowerShell-expanded `test_simulation_*.py` plus
  `tests/test_application_contracts.py` → **175 passed in 71.33s**.

Sol review completed and this package was committed and pushed as `5f7a8ee`
(`Add synthetic commissioning parity fixtures`). No GUI, hardware, USB/COM,
Wi-Fi, LAN/non-loopback endpoint, runtime config, generated evidence, or
physical commissioning was accessed or executed.

## P1 QML/frontend verification — 2026-09-07

Implemented deterministic headless frontend verification through the public
`ControllerViewModel`/`ApplicationController` boundary only; no GUI instance,
hardware, or non-loopback transport was used:

- The QML poll path now calls `ApplicationController.poll_simulation()` rather
  than reaching into the runtime directly. Supervisor health prefers the
  runtime heartbeat decision and fails closed when disconnected or unhealthy.
- The simulation surface visibly binds stock metrics, first-contact
  ring/crosshair and hazard details, safety/interlock state, evidence export
  availability/status, connected-only simulator restore, and truthful
  pause/resume/abort actions. Existing close-guard bindings remain asserted.
- Added headless Qt regressions for connected/disconnected projection and
  stale-state cleanup, snapshot/stock/hazard projection, 50-entry bounded
  hazard history, unhealthy supervisor state, operator hold/interlock notices,
  export success/failure feedback, and required QML visibility/action bindings.

Validation evidence:

- `.venv\\Scripts\\python.exe -m pytest tests/test_qt_shell.py -k simulation -q`
  → **7 passed, 25 deselected in 1.05s**.
- `.venv\\Scripts\\python.exe -m pytest tests/test_qt_shell.py
  tests/test_application_contracts.py -q`
  → **74 passed in 9.07s**.

No commit or push was made pending Sol review. Generated evidence/config,
`%SystemDrive%`, credentials, GUI state, hardware, USB/COM, physical Wi-Fi,
non-loopback endpoints, and unrelated files remain excluded. P0 GUI acceptance
is not claimed closed by this package.

## P2 long-duration randomized/property testing — 2026-09-07

Added a deterministic seeded property corpus that drives the virtual
controller/plant with a virtual clock only. Mixed actions cover XYZ motion,
G17 arc, jog, hold/resume, reset, spindle, probing, WCO changes, injected
ack/status/probe faults, collision fixtures, planner backpressure, and logical
disconnect/recovery. Each run records semantic actions/status/motion/hazard
events and returns seed, step, action, first-failure reason, digest, planner
and response maxima, hazard count, and monotonic stock volumes. A compact
replay-artifact writer persists that context for any first failure.

Invariants enforce finite in-envelope machine coordinates, bounded planner and
deferred FIFO admission, framed status, deterministic hazard latching,
monotonic bounded stock, deterministic replay digests, and bounded stress
controls (`1..4096` steps, `1..16` stress depth). The stress run exposed an
actual unbounded deferred FIFO; controller admission now uses a declared
RX-tied deferred capacity (`max(8, rx_capacity // 8)`) and returns deterministic
`error:11` beyond it, preserving normal planner saturation behavior.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_property_scenarios.py
  tests/test_simulation_controller_branches.py -q` → **25 passed in 1.43s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_property_scenarios.py
  tests/test_simulation_core.py tests/test_simulation_public_scenarios.py
  tests/test_simulation_spawn_workers.py tests/test_application_contracts.py
  -q` → **83 passed in 26.34s**.

## H6 public safety commissioning and Auto XYZ controls — 2026-09-08

Implemented the requested public, headless-only boundary without launching or
interacting with Pine and without selecting any physical transport:

- `ApplicationController.save_homing_limit_declarations()` validates all X/Y/Z
  declarations (enabled switch, min/max end, pin, active-low, hard-limit,
  debounce, and measured maximum override), persists disconnected physical
  declarations per machine, and maps the same profile into the active twin.
  Real GRBL receives only guarded `$5/$21/$22/$23` commands after Idle and
  safety checks; mixed per-axis values that cannot be represented by GRBL's
  global settings are rejected rather than collapsed silently.
- `CalibrationCommissioningRecord` now supports a required machine-scoped
  identity when checked through the public H6 path. The simulation-only
  commissioning action installs the explicit conductive corner-circle fixture
  through the runtime boundary and creates a session-scoped record. Disconnect
  and close clear that record.
- The ViewModel exposes declaration JSON, fixture/Auto XYZ availability,
  typed state, and the bounded search/retract/Z-touch plan. `MachineSetupDialog`
  now exposes per-axis fields and a save action. The simulator exposes guarded
  commission/preview/start/abort controls; QML does not mutate plant state and
  manual Zero X/Y/Z/XYZ controls remain unchanged.
- Added application/configuration, real GRBL setting-gate, twin-boundary,
  loopback Auto XYZ, and static QML binding regressions. An initial affected
  run caught two QML parser errors caused by compact nested validators; those
  ordinary defects were expanded into valid multiline QML and the gates were
  rerun successfully.

Validation evidence:

- `.venv\\Scripts\\python.exe -m pytest -q tests/test_simulation_h6.py` →
  **4 passed in 2.51s**.
- `.venv\\Scripts\\python.exe -m pytest -q tests/test_simulation_h6.py
  tests/test_simulation_safety.py tests/test_simulation_h5.py
  tests/test_qt_shell.py -k "h6 or simulation or auto_xyz or homing or palette"`
  → **30 passed, 25 deselected in 5.62s**.
- Affected simulation/application/spawn/Qt/machine gate → **245 passed in
  83.63s**.
- `.venv\\Scripts\\python.exe -m compileall -q src tests` → passed;
  `git diff --check` → passed.
- Final `.venv\\Scripts\\python.exe -m pytest -q` → **505 passed in
  133.73s**.

No GUI, hardware, GPIO/reset pin, USB/COM, Wi-Fi, non-loopback endpoint,
generated evidence, runtime config, `%SystemDrive%`, or unrelated user work
was staged. The unresolved native visual/export acceptance gate remains
PARTIAL as documented above.

No commit or push was made pending Sol review. No GUI, hardware, USB/COM,
Wi-Fi, non-loopback endpoint, generated evidence/config, `%SystemDrive%`, or
unrelated user files were accessed or staged.

## P2 STEP stock-removal fidelity — 2026-09-07

Implemented and validated the bounded STEP/stock package headlessly. The
isolated planar model now has an explicit work-frame origin and produces a
deterministic target height field for supported orthogonal 2.5D geometry.
`showcase-pocket-island.step` preserves the nested island at full stock height
while mapping the recessed feature to its measured target depth. Unsupported
orientation/tilted geometry is marked `collision_only` and never claims a
removal target. Stock grids retain exact partial boundary-cell areas and enforce
the configured resolution/cell budget.

Executed removal now consumes the accepted TCP polyline (including interior
linear/arc path samples), transforms machine coordinates through the current
WCO into the workpiece frame, and requires a spinning non-rapid motion before
applying the swept cutter footprint. The declared STEP workpiece path is now
loaded at both spawned production boundaries through the isolated importer;
unsupported models remain collision-only. Backend and independent supervisor
stock state use the same path/frame conversion. Metrics report stable stock,
removed, remaining, target, uncovered/undercut, gouged/overcut, cell,
resolution, and collision-only values; target fields are returned defensively.

Added deterministic regressions for shifted placement, target generation,
pocket/island retention, unsupported collision-only import, replay-stable
swept metrics, and the existing spindle-off/rapid/depth/tool rejection and
production loopback accepted-cut coverage.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_generated_step.py
  tests/test_simulation_geometry_and_parity.py
  tests/test_simulation_plant_and_safety_branches.py -q` → **41 passed in
  29.91s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_spawn_workers.py
  tests/test_simulation_core.py -q` → **30 passed in 5.29s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_controller_branches.py
  tests/test_simulation_core.py tests/test_simulation_evidence_branches.py
  tests/test_simulation_generated_step.py
  tests/test_simulation_geometry_and_parity.py tests/test_simulation_operator.py
  tests/test_simulation_plant_and_safety_branches.py
  tests/test_simulation_public_scenarios.py tests/test_simulation_settings.py
  tests/test_simulation_spawn_workers.py tests/test_simulation_wco_live.py
  tests/test_application_contracts.py -q` → **153 passed in 63.06s**.
- After wiring the declared STEP path through both spawned stock boundaries,
  `.venv\Scripts\python.exe -m pytest tests/test_simulation_generated_step.py
  tests/test_simulation_spawn_workers.py -q` → **17 passed in 35.89s**.

No commit or push was made pending Sol review. No GUI, hardware, USB/COM,
Wi-Fi, non-loopback endpoint, generated evidence/config, `%SystemDrive%`, or
unrelated user files were accessed or staged.

## P2 deterministic fault injection and recovery — 2026-09-07

Implemented the bounded headless fault-injection boundary without GUI or real
transport access. `SimulationFault` now validates its name, sequence, time,
and value and provides deterministic matching against virtual sequence/time;
time-scoped faults activate only once virtual time reaches the declared point.
The controller applies these scopes to existing acknowledgement faults and
adds fail-closed hooks for frozen motion, malformed/stale status, changed WCO,
spindle delay, probe failure, and reset-to-alarm. Clearing faults also cancels
pending delayed acknowledgements/spindle effects safely.

`SimulationRuntime` accepts initial faults and exposes install/clear methods
that forward injections to both owned backend and supervisor processes. The
backend handles deterministic telemetry-overflow, backend-heartbeat-loss, and
disconnect/reconnect injections; backend heartbeat loss emits a typed fault,
ALARM, and runtime safety incident rather than silent success. Runtime fault
and telemetry-overflow markers are now explicitly translated into one
deduplicated bounded `SUPERVISOR_UNAVAILABLE` incident, trace fault/hazard
events, and one backend interlock. The supervisor supports heartbeat-loss
injection while preserving its independent safety actor and owned-process
cleanup. Existing alarm, missing/delayed/duplicate/error-ack, status, reset,
queue, and loopback-only behavior remains intact.

Added deterministic regressions for sequence/time matching, invalid fault
scope rejection, frozen-motion safety, delayed spindle, probe failure,
changed/stale status, and initial fault propagation through the owned loopback
runtime. Existing job final-drain alarm and ack-fault tests remain passing.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_controller_branches.py
  tests/test_simulation_core.py -q` → **39 passed in 4.67s** (includes the
  typed backend-fault/telemetry-overflow interlock regression).
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_controller_branches.py
  tests/test_simulation_core.py tests/test_job.py
  tests/test_application_contracts.py -q` → **90 passed in 4.12s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_spawn_workers.py
  tests/test_simulation_public_scenarios.py tests/test_job.py
  tests/test_application_contracts.py -q` → **66 passed in 21.36s**.

No commit or push was made pending Sol review. No GUI, hardware, USB/COM,
Wi-Fi, non-loopback endpoint, generated evidence/config, `%SystemDrive%`, or
unrelated user files were accessed or staged.

## P2 deterministic evidence and replay completeness — 2026-09-07

Implemented the headless evidence/replay package without GUI or physical
transport access:

- Trace events now retain semantic command/response, controller state/status,
  planner capacity/use, motion, spindle, hazard, intent, and final-state data
  at scenario boundaries; runtime traces additionally capture backend status
  snapshots and supervisor heartbeat/hazard/stock/intent events.
- Canonicalization is explicit and recursive. Only the declared noise fields
  (`pid`, `port`, wall-clock/timestamp, absolute path, and session id) are
  removed; command, response, modal, WCO, planner, motion, spindle, stock,
  hazard, fault, intent, and final-state payloads remain semantic. Digest
  output is stable across key order and tuple/list representation.
- Trace loading now rejects unsupported schema, truncated/nonfinite JSON,
  malformed event identity/time/source/payload, non-monotonic time, and
  non-contiguous sequences. Runtime evidence is bounded to 16,384 events while
  preserving valid contiguous evidence when the cap is reached.
- Added `first_trace_difference` and `replay_scenario_trace`, which rerun a
  stored built-in scenario under its deterministic seed and report matched
  status, expected/actual digests, and the first semantic divergence. The
  verification CLI now supports `--replay` and emits machine-readable and
  Markdown replay reports.
- Added deterministic tests for JSON/Markdown round-trip, canonical digest
  stability, malformed/truncated/schema/payload rejection, first-difference
  reporting, bounded evidence, all built-in scenario replays, and CLI replay.
  Existing physical-parity authorization remains unchanged.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_evidence_branches.py
  -q` → **8 passed in 5.90s** (including all replay/bounded/schema regressions).
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_evidence_branches.py
  tests/test_simulation_geometry_and_parity.py tests/test_simulation_public_scenarios.py
  tests/test_simulation_core.py -q` → **30 passed in 28.00s**.
- `.venv\Scripts\python.exe -m pytest <PowerShell-expanded test_simulation_*.py>
  tests/test_application_contracts.py tests/test_job.py -q`
  → **160 passed in 58.55s**.

No commit or push was made pending Sol review. Generated evidence/config,
`%SystemDrive%`, credentials, GUI state, hardware, USB/COM, physical Wi-Fi,
non-loopback endpoints, and unrelated files remain excluded.

## P1 GRBL/DLC32 protocol-fidelity expansion — 2026-09-07

Implemented the bounded protocol-fidelity correction headlessly:

- Ordinary commands are now fail-closed while the virtual controller is in an
  alarm: only explicit `$X`, `$H`, or realtime soft reset can clear the alarm;
  motion is never queued behind an uncleared limit alarm. Soft reset also
  restores the default modal state while retaining FIFO/deferred-line cleanup.
  Homing clears the alarm state consistently.
- Added deterministic protocol regressions for fragmented partial lines with
  interleaved realtime `?`/`!`, exact status/ack ordering, alarm unlock and
  modal reset behavior. Existing parser/controller coverage continues to cover
  comments, malformed/nonfinite words, system queries/settings/WCS/TLO/probe
  reports, modal/linear/arc/helical/jog paths, spindle ramping, planner/RX
  `Bf`, and deterministic ack fault hooks.
- Preserved command acceptance versus plant completion, bounded planner
  admission, realtime responsiveness, and existing loopback-only transport
  boundaries.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_controller_branches.py
  tests/test_simulation_core.py -q` → **35 passed in 3.48s** (final rerun after
  system-command comment normalization).
- `.venv\Scripts\python.exe -m pytest <PowerShell-expanded test_simulation_*.py>
  tests/test_application_contracts.py tests/test_job.py -q`
  → **156 passed in 54.12s**.

No commit or push was made pending Sol review. Generated evidence/config,
`%SystemDrive%`, credentials, GUI state, hardware, USB/COM, physical Wi-Fi,
non-loopback endpoints, and unrelated files remain excluded.

## P1 collision and coordinate-frame hardening — 2026-09-07

Implemented the scheduled headless collision/frame package without GUI or
physical transport access:

- Added immutable `CoordinateFrame` helpers for validated machine↔work point
  conversion and work-space AABB translation using the GRBL convention
  `machine = work + WCO`. Workpiece stock and optional work-frame fixtures now
  use the same translation in both `CollisionWorld` and the independent
  operator; machine-frame bed, uprights, tool, and holder proxies remain in
  machine coordinates.
- Added strict `AABB.penetrates` semantics so cutter/bed/fixture and frame
  checks distinguish face/edge/point contact from solid overlap. The
  conservative holder/stock contact guard is intentionally identical in both
  assessors. Existing travel limits remain authoritative and endpoint-only
  checks were not substituted for sweeps.
- Extended immutable `MotionSnapshot` telemetry with the executed polyline.
  `swept_bounds` now samples only the executed portion of linear, G17, and
  helical paths (including interior arc points), preventing high-speed or
  endpoint-safe tunneling while avoiding future-path false alarms.
- Added deterministic coverage for frame round-trips and shifted stock,
  non-zero WCO production parity, all three axis limits, strict stock-top
  contact versus penetration, arc first-contact sweeps, stationary contact
  latching, rapid/spindle-off/excessive-depth/retained-gouge classifications,
  and valid spinning-tool stock removal.
- Added a spawned loopback production-boundary regression proving a shifted
  workpiece with non-zero Z WCO yields the same spindle-off hazard from backend
  and independent operator without divergence.

Validation evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_geometry_and_parity.py
  tests/test_simulation_plant_and_safety_branches.py
  tests/test_simulation_controller_branches.py tests/test_simulation_operator.py -q`
  → **55 passed in 3.43s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_spawn_workers.py
  -k "real_backend_and_operator_parity_on_wco_stock_entry" -q`
  → **1 passed, 10 deselected in 0.90s**.
- `.venv\Scripts\python.exe -m pytest <PowerShell-expanded test_simulation_*.py>
  tests/test_step_simulation.py tests/test_application_contracts.py tests/test_job.py -q`
  → **163 passed in 56.86s**.

No commit or push was made pending Sol review. Generated evidence/config,
`%SystemDrive%`, credentials, GUI state, hardware, USB/COM, physical Wi-Fi,
non-loopback endpoints, and unrelated files remain excluded.

## Sol review correction — backend-owned hazard telemetry boundary (2026-09-07)

Implemented the bounded production-boundary correction without GUI or physical
transport access:

- `simulation/backend.py` now owns a `CollisionWorld`, an independent
  `StockModel`, and the previous immutable plant snapshot. Every telemetry
  snapshot includes an explicit `backend_hazards` list, including `[]` when no
  backend hazard is present. Collision checks use the current machine WCO and
  the backend's own stock state; stock removal is applied only in that backend
  state after cutting observations.
- `simulation/supervisor.py` parses and compares that explicit list—including
  an explicit empty list—against the independent operator assessment. A
  semantic mismatch emits `commanded_executed_divergence` and the typed
  operator interlock path without waiting on or calling the backend oracle.
- The independent operator now gates physical transition recomputation to
  motion states and matches the backend's rapid horizontal/downward stock-entry
  semantics, preventing false disagreement during Idle/Alarm and preserving
  the existing WCO envelope behavior.
- Added a deterministic supervisor-boundary regression that deliberately sends
  an empty backend verdict for an out-of-travel Run snapshot and proves travel
  hazard + divergence + typed interlock are emitted and the worker terminates
  without deadlock. The real spawn-worker regression also verifies production
  backend snapshots carry an explicit empty hazard list.

Focused evidence:

- `.venv\Scripts\python.exe -m pytest tests/test_simulation_operator.py
  tests/test_simulation_spawn_workers.py tests/test_simulation_public_scenarios.py -q`
  → **18 passed in 20.48s**.
- `.venv\Scripts\python.exe -m pytest tests/test_simulation_*.py
  tests/test_step_simulation.py tests/test_application_contracts.py tests/test_job.py -q`
  → **153 passed in 54.54s** (PowerShell-expanded simulation file set).
- After hardening supervisor key-presence handling for explicit verdicts,
  `.venv\Scripts\python.exe -m pytest tests/test_simulation_spawn_workers.py
  -k "supervisor_worker" -q` → **3 passed, 7 deselected in 0.86s**.

No commit or push was made pending Sol review. Generated evidence/config,
`%SystemDrive%`, credentials, GUI state, hardware, USB/COM, physical Wi-Fi,
non-loopback endpoints, and unrelated files remain excluded.
