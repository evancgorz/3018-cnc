# Pine improvement backlog — Luna X-high handoff

Prepared 2026-09-09 from the current uncommitted UX2 implementation.

## Objective and review basis

Make the existing eight-step operator flow reliable, understandable, and easy to
test without a machine. Prefer fewer visible features. Preserve the existing
application services and digital twin; do not add another navigation system.

This is a source audit and execution proposal, not a new test certification.
The prior execution report records 595 passing tests. No tests or native app
sessions were run for this audit. Passing historical tests does not establish
the missing behaviors below. Findings marked **confirmed** describe observable
source behavior; **investigate** requires a reproducer before implementation.

The architecture already separates Qt from application services for motion,
jobs, homing, probing, fixtures, and calibration. The twin has a controller/plant
process, independent supervisor, deterministic scenarios, traces, stock geometry,
and parity infrastructure. Extend these boundaries rather than replacing them.

## Execution order

| Batch | Priority | Deliverable | Depends on |
| --- | --- | --- | --- |
| A | P0 | Isolated, trustworthy test harness | None |
| B | P0 | Run authorization and current safety evidence | A |
| C | P1 | Complete, minimal operator journey | B |
| D | P1 | Predictable configuration and probe workflows | A, B; integrate with C |
| E | P1 | End-to-end twin acceptance and evidence | B, C, D |
| F | P2 | Targeted maintainability and documentation | E |

One Luna X-high worker should execute one coherent batch at a time, persist its
results, and pass review before the next batch. Do not create overlapping writers.
This document is a handoff proposal; it does not itself launch a worker or
authorize hardware commissioning. Keep the current execution contract/result as
historical evidence; add dated batch sections when execution is requested.

## Batch A — Make isolated testing a provable property

### A1. Inject the root for every ViewModel store (confirmed)

Evidence: `qt/view_model.py:ControllerViewModel.__init__` uses `Path.cwd()` for
UI preferences/live settings even when supplied an `ApplicationController` with
a temporary root. A temporary controller alone therefore does not isolate all
ViewModel I/O. Previous claims that forbidden USB/Wi-Fi factories prove complete
test isolation are too broad.

Implement an explicit application context/root or injected stores and use it
consistently for preferences, live settings, logs, generated jobs, and evidence.
Avoid changing process working directory as the production solution.

Acceptance: instantiate from a different working directory; all reads/writes
remain within the supplied temporary root. Seed sentinel settings inside an
isolated fixture and verify unchanged hashes. Never read actual user settings to
prove this. Test missing, malformed, and future-version preference files.

### A2. Inject discovery as well as transports (confirmed)

Evidence: ViewModel initialization calls `_refresh_ports()`, which calls
`application.usb_ports()`. The controller defaults to real `available_ports`.
Forbidden connection factories do not prevent port enumeration.

Use the existing injectable `usb_ports` boundary in isolated tests; make discovery
lazy/contextual in production. Simulation initialization must not enumerate serial
ports or discover LAN devices. Verify separate counters for discovery and connect.

Acceptance: offscreen and loopback harnesses fail on any discovery/physical
factory call; settings remain temporary; every spawned runtime has recorded
ownership and is closed in `finally`. Clean only exact owned processes/paths.

## Batch B — Close authorization and evidence gaps

### B1. Bind job confirmation to the reviewed job (confirmed, highest priority)

Evidence: `ControllerViewModel.start_job()` and
`confirm_pending_action(... job_start ...)` check general readiness and preflight
but do not require `_review_acknowledged` or `_guided_preflight_confirmed`.
The QML Start button checks physical preflight but does not check review.
The pending job-start payload is `None`; confirmation therefore does not identify
the program reviewed when the dialog opened. Controller readiness checks still
exist, but they do not enforce the new review contract.

Implement an application-owned run authorization/revision identifying the loaded
program contents, machine definition, reference, WCO, relevant safety/fixture
state, and required acknowledgements. Validate it both when requesting and when
accepting confirmation. Reuse existing nonce/version concepts where suitable;
do not confuse the current active-job remote nonce with pre-start authorization.
Audit local UI, remote bridge, and direct public controller entry points for
consistent policy. Keep pause/abort available without a new review requirement.

Acceptance: reject start without review/preflight; reject old confirmation after
job replacement (including same filename/different contents), reference/WCO
change, reset, reconnect, hazard, or configuration change. Every rejection sends
zero job commands. A newly reviewed unchanged job starts once; replayed tokens
do not start it again. Exercise the public confirmation path, not private flags.

### B2. Represent status freshness and supervision truthfully (confirmed mapping;
end-to-end expiry behavior needs investigation)

Evidence: `_workflow()` assigns `fresh_status=status is not None` and defaults a
missing runtime supervisor attribute to healthy. `MachineSession.can_move` uses
the retained status with no age check. JobService has a controller-silence timeout,
but that alone does not establish stale-Idle protection before a job or manual
operation. Audit all existing timeout/recovery paths before adding a shared clock.

Introduce timestamped status/session generation and explicit supervisor states
(healthy, unhealthy, unavailable, not applicable). Use one documented freshness
policy across projection and command authorization. Avoid a Qt-only watchdog.

Acceptance: fake-clock stale Idle, delayed/reordered reports, transport connected
but silent, supervisor loss, and reconnect cannot authorize new operations.
Fresh reports from an old session cannot restore trust. Recovery requires current
evidence. Confirm active-run hold/abort remains reachable.

### B3. Stop displaying validation claims derived from filenames (confirmed)

Evidence: Review's `Validated envelope and supervisor result` row and Run's
`Job fits the virtual envelope` row use `job_file != 'No G-code loaded'` as their
pass condition. Review does not actually display a job-specific collision result.
Safety's combined hazard/E-stop label reads only `simulation_hazard_active`.

Provide typed review facts from the application/projection: bounds checked,
collision analysis completed or not run, supervisor availability, E-stop input
known/unknown, and relevant failure reason. A running supervisor or absence of a
current collision is not proof that an entire future path is collision-free.
For physical sessions, report unavailable feedback honestly.

Acceptance: a loaded out-of-envelope job never earns a checkmark; an untested
path says not checked; supervisor failure and E-stop state are independently
visible. UI rows and start gating consume the same facts. Add no fake green state.

## Batch C — Make the minimal operator journey complete

### C1. Restore obvious loading and reduce redundant decisions (confirmed)

Evidence: Main QML defines `gcodeFileDialog` and its accepted binding, but the
active shell has no `gcodeFileDialog.open()` action. Prepare advertises loading
yet exposes engraving and STEP creation. The terminal Continue button is labeled
`Start / monitor` although Run's `continuable` is always false.

Make `Load G-code` the first Prepare action; keep one secondary Create action
with existing creation options. Hide unavailable/advanced capabilities by
default. Hide the forward button on the terminal Run step; retain the explicit
Start job action. Keep one primary navigation rail.

Acceptance: an offscreen user can open the picker from Prepare, accept a valid
temporary URL, see updated preview, and proceed. Invalid/cancelled input preserves
the previous job. Verify public click handlers and focus, not just string presence.

### C2. Define progression, recovery, and repeat-job behavior (confirmed gap)

Evidence: navigation changes through selection/Back/Continue/reset; there is no
completion-driven progression mechanism in `_emit_state`. `guided_back()` simply
decrements the index even when the prior step is now locked. The current model
has no explicit successful-run finish/next-part state.

Implement a small documented navigation policy: advance after observed completion
of a user-initiated connect/home/zero operation, while respecting intentional
backward review. Safety loss presents a direct recovery route; Back cannot enter
a forbidden future step. Preserve Run monitoring during active jobs. After success,
offer a clear next-part action with explicit rules for keeping or invalidating
reference/work zero/review; never auto-start the next job.

Acceptance: table-driven public-state transitions cover completion, failure,
backward review, reconnect, job completion, and repeat part. No navigation event
sends motion. First-time configuration and valid-profile startup behavior are
explicitly tested. Keep this small; do not add a general workflow engine.

## Batch D — Make configuration and probing predictable

### D1. Make configuration saves atomic and failures visible (confirmed)

Evidence: `saveProbeDeclarations` calls two save slots sequentially and closes
the dialog regardless of either outcome. Axes save similarly closes immediately.
The first probe save can persist capability changes before invalid geometry is
rejected by the second. Reference invalidation also happens on capability save.

Validate one complete draft before persisting; return a structured accepted/error
result to the editor. Keep invalid drafts open with a field-specific explanation.
Separate local persistence from controller-settings acknowledgement so partial
hardware application cannot be presented as success. Preserve all unedited axis
and probe properties. No-op saves should not needlessly invalidate trust.

Acceptance: invalid geometry, persistence failure, controller rejection, and
unchanged saves have deterministic outcomes. No partial local draft commit;
reopening/cancelling does not leak stale edits. All tests use temporary stores.

### D2. Establish precise per-axis work-zero and plate-removal semantics (investigate)

Evidence: `MachineSession.request_work_zero_confirmation` marks an XYZ request
as awaiting confirmation, while individual axes invalidate aggregate confirmation.
The movable-Z route previously required `work_zero_confirmed`; C-041 removes
that prerequisite because the probe writes only the Z work offset at the current
X/Y position. Projection can mark Work Zero complete from the aggregate
boolean even when plate removal remains required by the controller's start gate.

First reproduce X→Y→Z and X→Y→movable-Z flows through the controller and matching
WCO acknowledgements. Define per-axis evidence or an explicit final confirmation
that makes both supported routes understandable. Block Continue while removal
is pending, with the acknowledgement on the current step. Preserve Auto XYZ's
fresh matching WCO requirement and simulation-only restriction.

Acceptance: shuffled/missing/stale acknowledgements cannot complete zero;
manual individual-axis and movable-Z workflows can finish without an unexplained
extra Zero XYZ operation. Probe no-contact, stuck input, abort, and removal gates
have direct recovery instructions. Do not enable physical Auto XYZ in this batch.

## Batch E — Prove the operator journey against the twin

### E1. Extend public acceptance through actual job execution

Evidence: `test_ux2_public_viewmodel_loopback_guided_progression_and_cleanup`
ends at Prepare with no job loaded. It proves Auto XYZ/WCO progression but not
Prepare→Review→confirmation→streaming→drain→spindle stop→completion.

Add deterministic temporary jobs and run the entire public flow against the
loopback controller with the independent supervisor. Cover at least: manual
reference/manual zero; three-switch homing; partial-switch fallback; Auto XYZ;
movable-Z where twin support is established. Use pairwise configuration coverage
plus explicit high-risk combinations, not every possible Cartesian product.

Fault scenarios: lost status, disconnect, E-stop/reset, limits, probe no-contact,
holder/fixture collision, unsafe rapid into stock, supervisor loss, and job
replacement while confirmation is open. Verify no commands after interlock,
matching WCO before progress, and visible recovery state.

Acceptance: each scenario records configuration, seed, transport commands,
observed transitions, expected outcome, and owned-process cleanup. Include a
successful completed job and failed-job reload/review. Replay failures with the
same seed. Run backend tests frequently; run representative offscreen UI paths
per batch and native UI only in a separately authorized isolated session.

### E2. Improve evidence quality without increasing test count for its own sake

Replace UI tests that only assign `guidedIndex` or assert window dimensions with
real ViewModel state and reachable control clicks for the principal flows.
Keep clearly labeled isolated render fixtures for visual variants. Verify bounds,
scroll reachability, focus order, and no obscured required actions at 1180×720 and
1500×920. Render offscreen screenshots for review if supported.

Acceptance: assertions fail for a missing Load action, false validation checkmark,
inaccessible recovery action, duplicated navigation, or bypassable review. Evidence
reports describe behaviors verified and limitations; raw test count is secondary.

## Batch F — Maintainability after correctness

Extract the major QML step surfaces and the guided-navigation/review projection
from the large Main QML/ViewModel only where this reduces duplication exposed by
the earlier batches. Compute/cached immutable workflow facts once per relevant
state revision instead of recalculating preflight separately for every QML
property access. Verify invalidation before introducing caching.

Update README to the implemented guided flow and distinguish supported,
simulation-only, declared-but-unavailable, and hardware-commissioned capabilities.
Retain `CNC_PLATFORM_BACKLOG.md` for future hardware expansion. Consolidate dated
PASS claims into a final batch evidence index while preserving audit history.

Acceptance: existing application APIs still work; measured repeated projection
work decreases without stale readiness. Documentation names controls that exist.
Avoid unrelated architecture rewrites and dependency changes.

## Deferred deliberately

- Physical Auto XYZ release and physical-vs-twin commissioning: require actual
  plate dimensions, tool/holder geometry, wiring/controller identity, and a
  separately authorized, supervised hardware procedure with recorded tolerances.
- New machine types, rotary axes, dual-motor squaring, tool changers, auxiliary
  outputs, new cloud/live features, and broader CAM capabilities.
- Replacing the existing simulator, UI framework, or application service layer.

## Worker instructions and completion gates

Use Luna X-high when available; do not silently substitute another model/effort.
Read AGENTS.md and the applicable Sol–Luna workflow skill before execution.
Preserve all current uncommitted changes. Do not read/modify the user's untracked
configuration or `%SystemDrive%/` and historical acceptance directories. Do not
launch/interact with a native app instance or connect to hardware/non-loopback
endpoints. No commit, push, dependency upgrade, or destructive cleanup is part
of this backlog.

For each batch:

1. Record the baseline and reproduce the named gap using isolated fixtures.
2. Implement the smallest coherent fix and meaningful regression tests.
3. Run targeted suites; broaden to affected suites and loopback acceptance.
4. At an integration boundary, run compileall, the full suite once, and
   `git diff --check`. Do not repeatedly rerun unchanged full suites.
5. Write a result with exact commands, counts, failure/recovery evidence, remaining
   limitations, changed files, and ownership/cleanup proof. Mark PASS only for
   accepted behaviors; distinguish implementation defects from external blockers.
6. Request review of the concrete diff/evidence before proceeding to the next
   batch. Escalate material architecture changes; handle routine repairs locally.

Suggested initial worker prompt:

> Read docs/LUNA_XHIGH_IMPROVEMENT_BACKLOG.md and the repository instructions.
> Execute Batch A first using Luna X-high, preserving the current uncommitted
> implementation. Create a dated execution contract/result for the batch. Prove
> temporary-root and discovery isolation before running UI/twin acceptance.
> Return the reviewed scope, test evidence, and remaining risks for the next batch.
