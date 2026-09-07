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
