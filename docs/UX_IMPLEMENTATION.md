# UX and Responsiveness Implementation

This document records the first implementation milestone from the Sol–Luna UX
contract.

## User-facing behavior

- The header now exposes a compact readiness path: connection, trusted
  reference, work zero, validated job, and ready-to-run state.
- Readiness items are actionable and route the operator to the relevant
  workspace. The strip never performs physical motion by itself.
- Background work has a consistent operation banner with a phase and progress
  indicator. STEP import and the new preview request path use the Qt thread
  pool, so file and geometry work does not run in the GUI event loop.
- Failures that affect machine trust or recovery are represented as a visible
  issue banner instead of relying only on a transient toast.
- Preview requests are delayed by 150 ms, latest-request-wins, and retain the
  last valid preview while a replacement is being generated.
- Workspace selection and non-safety display preferences are stored in the
  versioned `config/ui-preferences.json` file. Physical safety acknowledgements
  and active operation state are never persisted.

## Application architecture

`application/ux_state.py` contains Qt-independent immutable snapshots and the
`OperationCoordinator`. It coordinates UI conflicts and stale results without
replacing the GRBL response ownership in the controller services.

`qt/task_runner.py` contains the `QThreadPool`/`QRunnable` bridge. Workers only
receive immutable inputs and return values or exceptions. ViewModel state is
updated only by queued Qt callbacks.

`qt/ui_preferences.py` provides versioned atomic persistence for non-safety UI
preferences.

`MotionService.phase` exposes safe-move phases such as raising safe Z, moving
X/Y, and lowering Z. It does not mark a move complete until the existing
acknowledgement and controller-state logic completes.

## Validation evidence

- `python -m compileall -q src` passed.
- `python -m pytest -q tests/test_ux_state.py tests/test_qt_shell.py` passed:
  21 tests.
- Full suite passed: 283 tests.
- Offscreen Qt shell loading passed through the existing Qt shell tests.
- `git diff --check` passed; only line-ending normalization warnings were
  reported by Git.

The optional live GUI validation was deferred because TTC 3018 application
instances were running. They were not focused, restarted, or otherwise
disturbed.
