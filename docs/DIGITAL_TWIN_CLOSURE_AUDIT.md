# TTC 3018 Digital-Twin Closure Audit

**Date:** 2026-09-08  
**Scope:** software-only closure of the original TTC 3018 digital-twin request  
**Overall disposition:** implemented software scope is evidenced and pushed;
native 1180×720/splash observations and physical commissioning remain outside
the closure claim.

This audit maps the original request to the current public boundaries, source,
deterministic tests, pushed checkpoints, and the persisted evidence record. It
does not replace the historical GUI report or erase any earlier observation.

## Closure matrix

| Original request | Implemented software boundary and source | Deterministic tests | Checkpoints | Evidence / disposition |
|---|---|---|---|---|
| Three-axis TTC 3018 envelope and motion: X 290, Y 170, Z 40 mm; finite motion, arcs, hold/resume/reset, spindle and swept limits | `src/ttc3018_control/simulation/{models,clock,plant,geometry}.py`; authoritative status/plant paths in `simulation/controller.py` | `tests/test_simulation_core.py`, `test_simulation_plant_and_safety_branches.py`, `test_simulation_property_scenarios.py`, `test_simulation_spawn_workers.py` | `69bdfc3`, `72e6f39`, `7e31059` | The result’s implementation evidence and property/plant sections record the 290/170/40 profile, bounded motion, deterministic clocks, and invariant coverage. Physical accuracy, force, heat, chatter, runout, and missed-step claims are deliberately excluded. |
| GRBL/DLC32-compatible controller boundary over ordinary raw TCP, including parser, realtime, modal/WCO/TLO/probe/status, planner/RX and ordered acknowledgements | `src/ttc3018_control/simulation/{protocol,controller,backend,runtime}.py`; existing `ApplicationController`/`TcpGrblConnection` remain the public path | `tests/test_simulation_controller_branches.py`, `test_simulation_core.py`, `test_simulation_spawn_workers.py`, `test_simulation_public_scenarios.py` | `69bdfc3`, `263487b` | The protocol-fidelity result section records fragmented input, realtime interleaving, alarms/reset/unlock, reports, bounded planner admission, and acceptance-versus-completion semantics. |
| Independent operator/safety supervisor that recomputes hazards and interlocks without sharing mutable plant/oracle state | `src/ttc3018_control/simulation/{operator,supervisor,runtime,scenarios}.py` | `tests/test_simulation_operator.py`, `test_simulation_spawn_workers.py`, `test_simulation_public_scenarios.py`, `test_simulation_safety.py` | `e3a5b18`, `69bdfc3` | The independent-operator and headless-first stabilization sections record typed intents, disagreement detection, heartbeat failure, semantic hazard latching, bounded queues, and public-boundary cleanup. |
| STEP/workpiece/stock placement, supported planar 2.5D removal, retained island, collision-only fallback, and swept collision hazards | `src/ttc3018_control/simulation/{geometry,collision,stock}.py`; isolated import/generation in `src/ttc3018_control/{step_geometry,step_engraver,step_simulation}.py` | `tests/test_simulation_generated_step.py`, `test_simulation_geometry_and_parity.py`, `test_simulation_plant_and_safety_branches.py`, `test_simulation_spawn_workers.py`, `test_step_geometry.py`, `test_step_engraver.py` | `40dd05a`, `72e6f39`, `69bdfc3` | The STEP stock-removal and collision-frame sections record work-frame transforms, target height fields, swept executed TCP paths, spindle/rapid/depth/tool/fixture hazards, retained islands, and collision-only labeling. Unsupported arbitrary-3D removal is a deliberate capability boundary, not an unfinished safety claim. |
| Per-axis homing/limit declarations: end selection, polarity, pins, hard-limit behavior, debounce, overrides and GRBL `$5/$21/$22/$23` semantics | `src/ttc3018_control/simulation/safety.py`, `simulation/controller.py`, `application/controller.py`, `qt/view_model.py`, `qt/qml/MachineSetupDialog.qml` | `tests/test_simulation_safety.py`, `test_simulation_h6.py`, `test_simulation_h7.py`, `test_simulation_spawn_workers.py`, `test_homing_service.py`, `test_machine_config.py` | `6e87809`, `3a70d66`, `85a7fee`, `293b937`, `3b8e16d` | H1–H4, H6, H7 result sections record production-boundary wiring, persisted profile seeding, polarity/end/pin mapping, Pn state, reconnect behavior, and physical-factory isolation. |
| E-stop definitions and fail-closed recovery: reset/feedback modes, polarity/debounce/latch, spindle/planner stop, release, fresh reference and acknowledgement | `src/ttc3018_control/simulation/safety.py`, `simulation/controller.py`, `simulation/backend.py`, `application/controller.py`, `qt/view_model.py`, `qt/qml/Main.qml` | `tests/test_simulation_safety.py`, `test_simulation_h7.py`, `test_simulation_core.py`, `test_simulation_spawn_workers.py`, `test_qt_shell.py` | `6e87809`, `85a7fee` | H1–H4 and H7 evidence records twin-only injection, application-boundary invalidation, recovery gates, UI controls, and no physical GPIO/reset traffic. |
| Automated XYZ datum from a conductive corner circle: bounded four-point searches, residual/tool-radius checks, safe retract, Z touch, fresh WCO confirmation and fail-closed states | `src/ttc3018_control/simulation/safety.py`, `simulation/controller.py`, `simulation/backend.py`, `application/controller.py`, `application/calibration_service.py`, `qt/view_model.py` | `tests/test_simulation_h5.py`, `test_simulation_safety.py`, `test_simulation_core.py`, `test_simulation_spawn_workers.py`, `test_qt_shell.py` | `1e94e6d`, `3dd4382`, `79bcc2e`, `b8739d3` | H5 and native Auto XYZ evidence record loopback production-boundary execution, default conductive surface repair, fresh WCO matching, completion, stale/no-contact/collision/E-stop failure states, and exact cleanup. Manual Zero X/Y/Z/XYZ remains separate. |
| Backend-first deterministic validation, replayable evidence, seeded properties, CLI and synthetic parity/A-B tooling | `src/ttc3018_control/simulation/{trace,verify,property_scenarios,public_scenarios,parity,commissioning}.py` | `tests/test_simulation_evidence_branches.py`, `test_simulation_property_scenarios.py`, `test_simulation_public_scenarios.py`, `test_simulation_commissioning.py`, `test_simulation_spawn_workers.py`, plus the full suite | `c09a5bb`, `7e31059`, `69bdfc3`, `5f7a8ee` | Evidence/replay, property, public lifecycle, and synthetic commissioning sections record schema/digest/replay checks, bounded traces, 5/5 CLI scenarios, seeded invariants, parity fixtures, and physical-provider inertness. The latest full suite is **521 passed**. |
| Isolated commissioning/A-B boundary with physical access inert until separately authorized | `scripts/run_simulation_gui_validation.py`; `src/ttc3018_control/simulation/{commissioning,parity}.py`; sentinel setup in the validator | `tests/test_simulation_commissioning.py`, `test_simulation_geometry_and_parity.py`, `test_qt_shell.py`, `test_simulation_spawn_workers.py` | `5f7a8ee`, `1883ef8`, `a3405ed` | Native digital-twin runs document loopback endpoints, sentinel hashes, forbidden USB/Wi-Fi factories, exact owned cleanup, STEP/G-code picker and hazard/export observations. No physical A/B session occurred. |

## Implemented software scope

The matrix above is closed through the normal public application and raw
loopback boundaries. The pushed history includes the headless twin/lifecycle
checkpoint (`69bdfc3`), each backend fidelity package, safety checkpoints, UI
surface corrections, G1–G3 picker/focus (`422f14e`), native picker evidence
(`1883ef8`), and constrained-shell regression (`78cb023`). The complete
implementation and test counts are in
[`EXECUTION_RESULT.md`](../.codex/sol-luna/EXECUTION_RESULT.md).

The software claim is intentionally narrower than a physical-machine claim:
proxy machine dimensions are configurable observations, and simulation proves
protocol/state/geometry contracts rather than cutting force, thermal behavior,
tool deflection, missed steps, real repeatability, or manufacturing accuracy.

## Native observation gaps

The constrained shell now has complementary offscreen evidence: the real QML
root held `1180×720` through Prepare/Preview & Run/Machine transitions with no
`pine.qt` warnings or transport creation. A native splash attempt was
transparent about the absence of a UIA-visible splash/top-level window, so no
screenshot or timing claim was made. Native visual resize at approximately
1180×720 and splash capture remain open observations. Historical GUI findings
and screenshots remain preserved in
[`GUI_USER_TEST_REPORT.md`](GUI_USER_TEST_REPORT.md).

Native digital-twin acceptance has otherwise recorded loopback connection,
reference/WCO, STEP import/generation, Auto XYZ, collision alarm/interlock,
first-contact projection, evidence export, G-code picker success, and exact
owned cleanup. Those observations do not convert the remaining native layout
or splash gaps into a physical-safety claim.

## Physical commissioning prerequisites

Physical commissioning is deliberately not part of this closure. A later
session would require explicit user authorization, an exact selected endpoint,
supervised preflight, emergency-power/E-stop readiness, spindle-off and
workholding checks, trusted reference and safe envelope, stage-specific
approval for probe/spindle/cutting gates, and captured parity evidence. The
physical capture provider remains inert unless those conditions are explicitly
met; no USB/COM, physical Wi-Fi, GPIO/reset, or non-loopback controller was
selected by this work.

## Deliberately deferred CAM/product capabilities

Unsupported arbitrary 3D STEP machining remains collision-only and is never
reported as verified removal. The twin does not claim CAM strategy quality,
cutting-force/thermal/runout behavior, manufacturer-accurate frame
measurements, rotary axes, tool changers, or physical encoder/sensorless
repeatability. These are product or later commissioning capabilities, not
unresolved defects in the implemented twin safety boundary.

## Audit conclusion

The original software-only TTC 3018 digital-twin request is evidenced through
the implemented modules, deterministic tests, pushed checkpoints, and result
sections in the matrix. Overall project status remains **PARTIAL** only for
the explicitly named native splash/1180×720 observations and the separately
authorized physical commissioning boundary.
