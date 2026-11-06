# Final Batch Evidence Index

Updated: 2026-09-12

This index consolidates the current executable evidence for the authorized
C-001–C-006 run. “Implemented” means the execution agent completed and
self-verified the task in this working tree; planning sign-off remains at the
combined review checkpoint. Dated audit and progress reports remain unchanged
so their historical claims and context are preserved.

| Batch | Status | Primary evidence | Scope |
| --- | --- | --- | --- |
| C-001 | Implemented | `tests/test_ux2_batch_ab.py` | Isolated ViewModel/application storage, lazy discovery, and future-preference rejection. |
| C-002 | Implemented | `tests/test_ux2_batch_ab.py`, `tests/test_application_contracts.py` | Job authorization bound to the reviewed job, current session, machine/reference/WCO state, and live safety evidence. |
| C-003 | Implemented | `tests/test_ux2_batch_cd.py`, `tests/test_workflow_projection.py` | Session-local guided completion, recovery, and active-run navigation. |
| C-004 | Implemented | `tests/test_ux2_batch_cd.py`, `tests/test_probing_service.py`, `tests/test_z_touch_plate_controller.py` | Atomic capability/probe persistence and explicit probing abort/recovery. |
| C-005 | Implemented | `tests/test_simulation_public_scenarios.py`, `tests/test_simulation_h6.py::test_ux2_public_viewmodel_loopback_guided_progression_and_cleanup`, `tests/test_ux2_batch_ef.py` | Reloadable digital-twin route, collision, transport-command, transition, and owned-cleanup evidence. |
| C-006 | Implemented | `tests/test_ux2_batch_ef.py::test_c6_workflow_and_review_projection_cache_until_facts_change`, `README.md`, this index | Shared workflow/preflight cache with state-keyed invalidation, capability-boundary documentation, and consolidated evidence index. |

## Verification snapshot

- `.\.venv\Scripts\python.exe -m pytest -q tests/test_ux2_batch_ef.py tests/test_ux2_batch_cd.py tests/test_workflow_projection.py tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog" --maxfail=1` → **112 passed, 1 deselected**.
- `$testFiles = @(Get-ChildItem tests -Filter 'test_simulation_*.py' | ForEach-Object { $_.FullName }); & .\.venv\Scripts\python.exe -m pytest -q $testFiles tests/test_ux2_batch_ef.py --maxfail=1` → **173 passed, 1 warning**.
- `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed.
- `git diff --check` → passed.

## Known boundaries

- `tests/test_qt_shell.py::test_machine_setup_hardware_page_scrolls_within_the_dialog`
  remains a known stale legacy assertion for controls removed from the current
  read-only `MachineSetupDialog.qml`; it is excluded only from the focused
  verification command above and remains documented in the handoff history.
- No native application instance, physical hardware, or non-loopback endpoint
  was accessed. Source changes require a manual GUI relaunch before they appear
  in an already-running application.
- Historical reports remain audit records: `docs/GUI_USER_TEST_REPORT.md`,
  `docs/STEP_25D_PROGRESS.md`, and `docs/DIGITAL_TWIN_CLOSURE_AUDIT.md`.
- `docs/CNC_PLATFORM_BACKLOG.md` remains the retained future hardware/platform
  backlog; C-007 and later architecture work are outside this execution run.
