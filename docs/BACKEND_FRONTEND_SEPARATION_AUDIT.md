# Backend/frontend separation audit

Updated: 2026-09-12

This is the C-007 gap audit of the current working tree against the separation
contract in [`coordination/BACKLOG.md`](../coordination/BACKLOG.md). It records
the initial C-007 state and the continuation evidence below. The audit is
intentionally software-only: no native Pine instance, serial/USB device,
non-loopback endpoint, or physical CNC was accessed.

## Reconciled topology

The current tree contains a useful backend foundation:

- `backend/runtime.py` owns one Qt-free `ApplicationController`, polls it, drains
  controller/transport events, and publishes a JSON-safe snapshot plus a bounded
  sequence of events.
- `backend/server.py`, `client.py`, `discovery.py`, and `protocol.py` provide a
  loopback-only, token-authenticated, versioned HTTP boundary with atomic
  discovery metadata and exact-owner cleanup.
- `backend/dispatcher.py` exposes a finite action registry and routes actions to
  public controller methods. Raw `send_line` and `send_realtime` are not actions.
- `backend/process.py` attaches to a healthy discovery record or spawns one
  backend process and remembers whether it spawned it. `qt/main.py` uses this
  manager in production `main()` and releases only the client on Qt shutdown.
- `backend/qt_adapter.py` is a compatibility-shaped snapshot/action facade. The
  production shell now polls it through the backend snapshot/event cursor and
  can reconnect without asking the backend to close.
- `backend/cli.py` is a Qt-free command adapter for read-only inspection,
  guarded motion/connection/job/probe/spindle operations, simulation, typed
  configuration preview/apply, revisions, idempotency, and structured errors.

The legacy path remains deliberately available to isolated tests through
`build_engine(application=...)` and the default `build_engine()` compatibility
composition. That seam must not be used by production `qt.main.main()`.

## Authority and lifecycle contract

| Concern | Authoritative owner | Client-local state | Current status / next boundary |
| --- | --- | --- | --- |
| Transport, polling, GRBL parsing, job streamer | Persistent backend `ApplicationController` and services | None | Backend runtime owns it; C-008 must make all supported actions explicit. |
| Machine/session safety facts | Backend snapshot and ordered events | Cached display projection only | Snapshot contains core facts; adapter is incomplete for homing/probe/calibration detail. |
| Durable machine/calibration configuration | Backend stores under its application root | UI preferences, layout, preview settings | In-process ViewModel still writes operational settings directly; move these operations behind typed API. |
| G-code parsing, bounds, review, preflight, start authorization | Backend job service and dispatcher | Generated preview strokes and navigation | Dispatcher has load/review/preflight/authorization actions; adapter lacks a usable program snapshot and review lifecycle. |
| QML navigation and presentation | Qt ViewModel | Guided index, dialogs, preview, notices | QML calls only ViewModel slots/properties; ViewModel still has a broad in-process facade. |
| Authentication and compatibility | Backend protocol/server | Client record and cached session id | Token/version checks exist; reconnect must reset client state from a fresh snapshot. |
| Backend ownership | Backend process + exact discovery record | `BackendProcessManager.spawned` marker | Attach/spawn exists; startup races, stale metadata, and duplicate owner cases need C-008/C-009 coverage. |
| Frontend close/reconnect | Client adapter | Qt engine and local preview | Production manager does not stop backend; adapter refresh/events and unavailable state are incomplete. |
| Active work after client loss | Backend job/motion services | None | Runtime can continue independently, but end-to-end client-loss/reconnect proof is missing. |
| Lease/orphan policy | Not yet represented as a protocol concept | None | C-009 must define heartbeat/lease semantics without making GUI presence necessary for active work. |

## GUI call inventory

All QML machine-affecting intents enter `ControllerViewModel` slots. The
ViewModel currently reaches an in-process `self.application` in these groups:

| Surface in `qt/view_model.py` | Direct in-process reach | Required migration |
| --- | --- | --- |
| Connection | `connect_usb`, `begin_wifi`, `connect_simulation`, `disconnect`, `poll_wifi`, `poll_wifi_setup`, `request_status`, transport-event handling | Route through backend actions and event/snapshot polling; USB discovery must become a backend query. |
| Motion/reference | `jog`, live jog, `move_to`, `cancel_jog`, `hold`, `resume`, `return_to_reference`, `return_to_work_zero`, `home_machine` | Preserve public ViewModel slots while issuing typed backend actions; homing is the only public reference-establishment path. |
| Work zero/probe/calibration | `set_work_zero`, `start_probe`/`probe_work_z`, `abort_probe`, Auto XYZ, plate commissioning and removal acknowledgement | Add complete typed action payloads and typed snapshot facts; never recreate safety decisions in Qt. |
| Job | `load_program`, `load_generated`, `preflight`, `authorize_job_start`, `start_authorized_job`, `pause_job`, `resume_job`, `abort_job` | Backend must publish program/review facts and one-use authorization/confirmation state. |
| Spindle | `start_spindle`, `stop_spindle` | Typed backend action only. |
| Configuration | machine/profile selection and save, homing declarations, probe configuration, Wi-Fi/USB settings, STEP settings | Retain editable calibration values but move operational writes behind validate/preview/apply/verify API. |
| Simulation/evidence | simulation connect/configure, limit input, E-stop exercise, trace export | Keep simulation actions loopback-only and expose evidence as backend events/snapshots. |
| Lifecycle | `close()` currently calls `self.application.close()` | Production adapter close must release only frontend resources; compatibility mode may retain legacy tests. |
| Live bridge | `qt/live_bridge.py` calls controller job state/nonce and pause/resume/abort directly | Move Live command authority to backend or explicitly disable it until a backend-backed bridge exists. |

The QML files do not import or call a transport, controller, or store directly;
the remaining bypass surface is the Python ViewModel/Live bridge composition.

## Gap matrix and sequencing

| Contract area | Evidence in current tree | Gap | Planned batch |
| --- | --- | --- | --- |
| Versioned loopback protocol/auth | `backend/protocol.py`, `server.py`, `client.py` | Snapshot schema and error/confirmation types are still too generic for the full UI. | C-008 |
| Single backend owner | `BackendProcessManager`, atomic discovery | Spawn race and exact-owner lifecycle need stronger tests and a lease/orphan policy. | C-009 |
| Complete action boundary | `ActionDispatcher.ACTIONS` | Several ViewModel actions/configuration writes are absent; some payloads coerce rather than strictly validate. | C-008 |
| Backend-first production GUI | `qt/main.py::main` uses `BackendProcessManager` | `ControllerViewModel` has a broad in-process path and the adapter is partial. | C-010 |
| Reconnectable presentation | `BackendClient.attach()` requires a full snapshot | Adapter does not consume ordered events or report generation/unavailable state to QML. | C-010 |
| CLI parity | `backend/cli.py` | CLI lacks typed review/confirmation, work-zero, probe, spindle, simulation, and safe-abort options. | C-011 |
| Active-job continuity | `BackendRuntime` owns controller | No subprocess test proves frontend destruction/recreation during active work. | C-012 |
| Dedicated TTC UI | `TTC3018_HARDWARE`, current setup QML | Current QML still contains legacy editable/general setup surfaces in dirty work. | C-010 |
| Physical commissioning | Explicit uncommissioned declarations | No physical evidence is implied or required. | C-013, separately authorized |

## C-007 targeted gates

`tests/test_backend_separation_audit.py` locks the audit's non-negotiable
boundaries before further architectural changes:

1. Production `qt.main.main()` composes through `BackendProcessManager`; the
   in-process controller is retained only as an explicit test seam.
2. The ViewModel has no direct transport-byte calls, and the finite dispatcher
   excludes raw transport operations.
3. The backend remains loopback-only and the audit names every known direct
   application/service/configuration reach that C-008–C-012 must remove.

These tests are audit gates, not a claim that the listed future gaps are already
closed. C-007 is complete when the matrix and gates are reviewable; later batches
must turn each remaining gap into implementation and end-to-end evidence.

## Continuation updates — C-008 through C-010

C-008 completed the contract layer: `contracts.py` defines typed snapshots,
events, capabilities, commands, results, and structured errors; the runtime
publishes semantic revisions and bounded validated program detail; and the
dispatcher exposes only finite, typed actions with optimistic revision checks
and idempotency. Discovery, machine configuration, job loading/review,
commissioning evidence, probing, simulation, and safety decisions now route
through those backend operations. Raw GRBL send/injection remains absent.

C-009 added an atomic `pine-backend.owner` root marker, authenticated live-owner
startup checks, dead-PID discovery cleanup, incompatible-client fail-closed
behavior, exact-owner release, and a client heartbeat. Client loss does not call
controller close, pause, abort, or disconnect; only explicit backend shutdown
can close the persistent runtime, and active work requires the safe-abort option.

C-010 added snapshot/event polling and retry/re-attach behavior to the Qt adapter,
backend availability/session properties to the ViewModel and QML header, and
frontend-only adapter close semantics. The legacy in-process `build_engine` mode
remains an explicit isolated test/development seam; production `qt.main.main()`
continues to compose only through `BackendProcessManager`.

## Continuation updates — C-013 software slice

C-013 added the backend-owned typed dual-channel safety-input contract,
fail-closed state machine, append-only transition audit, restart latch
restoration, controller-reset correlation diagnostics, and guarded diagnostic /
acknowledgement actions. The Qt adapter, ViewModel, guided Safety panel, and CLI
consume the same `safety.physical_estop` snapshot; backend readiness projections
remain blocked while the input or hazardous-power evidence is not trustworthy.
The only concrete adapter is a deterministic fake for software tests. The
maintained NC circuit, safety relay/contactor, isolated physical adapter,
machine-specific electrical review, measured power removal, and acceptance
remain separately authorized physical work and are not implied by this audit.
