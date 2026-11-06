# Execution Result

## Status

BLOCKED

## Work Completed

Executed the authorized coordination backlog sequentially through C-012.
C-001–C-006 remain implemented from the prior run. C-007 added the separation
audit and gates. C-008 completed typed versioned snapshots/events/capabilities,
structured errors, optimistic revisions, idempotency, confirmations, bounded
program projections, and the finite guarded action registry. C-009 added
single-owner backend startup/discovery, exact stale cleanup, incompatible-client
fail-closed handling, heartbeat diagnostics, and safe shutdown behavior. C-010
migrated production Qt polling to a disposable/reconnecting client adapter and
exposed honest backend availability in the ViewModel/QML. C-011 expanded the
Qt-free CLI with read-only inspection, guarded actions, explicit confirmation,
revision/idempotency metadata, structured errors, and configuration preview/apply
flows. C-012 proved active digital-twin work survives frontend close/reconnect
and proved explicit backend-process crash/relaunch behavior with session
identity and no automatic motion state.

Added `docs/BACKEND_RECOVERY.md`, updated the README and architecture decision
record, and maintained the coordination queue, status, and append-only handoffs.

The safe software slice of C-013 is also implemented: a Qt-free typed
dual-channel safety-input adapter contract, deterministic fake adapter,
fail-closed debounce/disagreement/stale/loss/session handling, backend-owned
latched state, durable append-only audit and restart restoration, diagnostic and
explicit acknowledgement actions, and non-recovery command gating. The
physical portion remains uncommissioned and is not represented as complete. The
restartable Qt adapter, ViewModel, and guided Safety panel now expose the same
backend status and acknowledgement path as the CLI; published readiness is
suppressed while safety or hazardous-power evidence is not clear/confirmed.
Physical safety fields also participate in ViewModel workflow/review cache keys,
and the direct BackendClient safety methods plus synchronized runtime access are
covered by the latest contract tests.
If a runtime is marked commissioned without an adapter, startup itself is now
treated as an immediate adapter failure and latches before any polling or
machine action can proceed.

## Validation

- `tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py` → 19 passed in 5.74s.
- `tests/test_backend_lifetime.py -k "not backend_root_has_one_owner"` → 5 passed, 1 deselected in 0.89s.
- `tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog"` → 50 passed, 1 deselected in 17.53s.
- `tests/test_backend.py::test_client_backed_qt_composition_does_not_construct_controller` → 1 passed in 2.55s.
- `tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py tests/test_backend_lifetime.py -k "not backend_root_has_one_owner"` → 30 passed, 1 deselected in 7.60s.
- `tests/test_backend_lifetime.py::test_backend_shutdown_requires_explicit_safe_abort_when_active` → 1 passed in 0.62s after an earlier transient Windows owner-marker teardown race.
- Post-fix regression: `tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_separation_audit.py` → 21 passed in 1.20s; `tests/test_backend_qt_adapter.py tests/test_backend_separation_e2e.py tests/test_backend_lifetime.py -k "not backend_root_has_one_owner"` → 9 passed, 1 deselected in 5.35s; `tests/test_application_contracts.py` → 42 passed in 0.60s; `tests/test_machine_session.py tests/test_probing_service.py tests/test_z_touch_plate_controller.py` → 16 passed in 0.51s; UX/simulation regression with the documented stale layout test deselected → 134 passed, 1 deselected in 52.68s.
- Final safety-boundary tightening: `tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_e2e.py` → 20 passed in 7.13s; `power_removal` remains `unknown` in the software-only path and acknowledgement requires fresh GRBL Idle/spindle-off evidence.
- Final GUI projection gate: `tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py tests/test_qt_shell.py -k "not machine_setup_hardware_page_scrolls_within_the_dialog"` → 76 passed, 1 deselected in 20.18s; `compileall` → passed.
- Final parity/cache gate: `tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_cli.py tests/test_backend_qt_adapter.py tests/test_backend_separation_audit.py tests/test_backend_separation_e2e.py` → 27 passed in 5.92s; UX/simulation cache regression → 84 passed in 38.31s; `compileall` and `git diff --check` → passed.
- Final startup-loss gate: `tests/test_backend_safety_input.py tests/test_backend_api.py tests/test_backend_lifetime.py -k "not backend_root_has_one_owner"` → 19 passed, 1 deselected in 1.16s; `compileall` → passed.
- `.\.venv\Scripts\python.exe -m compileall -q src tests` → passed; `git diff --check` → passed.

The known stale `test_machine_setup_hardware_page_scrolls_within_the_dialog`
assertion remains deselected because it expects controls removed from the
current read-only setup dialog. A full post-change `pytest -q` result is not
claimed.

## Deviations

C-013 physical commissioning cannot be completed in this software-only run. It
requires machine-specific electrical review, selection of a maintained NC
dual-channel circuit, safety relay/contactor and isolated feedback adapter,
wiring, energization, measured power-removal evidence, and bench/final-machine
acceptance. The run authorization explicitly excludes those actions. No
physical commissioning is represented as complete by the software evidence.

## Failure Details

The stopping condition is an external authorization/equipment boundary, not an
unrepaired implementation defect. The current queue records C-013 as blocked
after its safe software slice and the C-012 acceptance evidence. Planning must
separately authorize and scope the electrical review and physical commissioning
work before execution can resume. The C-007–C-013 software work and uncommitted
user changes are preserved.

## Evidence

All verification used temporary roots, Qt-free backend clients, loopback-only
listeners, digital-twin processes, and owned test subprocesses. No running TTC
3018/Pine application was inspected, focused, resized, relaunched, or stopped;
no serial/USB, non-loopback Wi-Fi, physical CNC, purchasing, wiring, or
energization was accessed. Manual GUI relaunch is required to load source
changes into an already-running application.
