# Backend/Frontend Recovery Contract

This runbook describes the local, loopback-only Pine split. The backend owns
the transport, machine session, safety facts, job stream, and durable machine
configuration. Qt and CLI clients own only their connection, event cursor, and
presentation state.

## Startup and versions

`pine-backend --root <data-root>` creates one authenticated
`pine-backend.json` discovery record and one atomic `pine-backend.owner` marker.
Clients validate both schema and protocol versions before using a snapshot. A
version mismatch is reported as incompatible; a second backend is never started
to mask it. The backend and clients may be packaged independently, but the
client must support the advertised schema/protocol pair before attach.

When `--root` is omitted, the GUI and standalone backend retain their existing
launch-working-directory default. Backend startup also registers the root, PID,
and session ID in a per-user locator so CLI and Python clients can find it from
another working directory. This locator contains no authentication token.
Clients prefer a valid discovery record in their current directory, otherwise
attach to a single registered backend, and report an ambiguity when multiple
registered roots are active. With no registration they fall back to the current
directory. Use `--root <data-root>` or `BackendClient(Path(data_root))` to select
an isolated development root explicitly. `pine-cli discover --json` reports the
selected root and token-free owner/version metadata.

The root-local `pine-backend.json` contains the authentication token and must
remain private. Backend startup output and `pine-cli discover` deliberately omit
that token. Tests may set `PINE_BACKEND_REGISTRY_DIR` to isolate locator writes.

Durable JSON stores remain backward-compatible only when their own version is
recognized. Unknown future preference/configuration versions are rejected or
loaded with safe defaults; machine identity and installed hardware facts are
never silently migrated into a different machine.

## Selecting or migrating a data root

The GUI keeps its existing launch-working-directory default. Select another
root for one launch with `run.bat --data-root <path>` or
`pine-cnc --data-root <path>`; `--root` is accepted as an alias. To make the
desktop shortcut use a selected root, run `setup.ps1 -ShortcutOnly -DataRoot
<path>`. Omitting these options preserves the current shortcut and launcher
behavior.

`.\.venv\Scripts\pine-migrate-data.exe migrate <source-root> <new-root>`
copies only known durable machine settings and recovery records to a destination
that does not yet exist. The normal `setup.ps1` install registers the command in
the project virtual environment.
It includes machine profiles/catalogs, connection preferences, saved work zero,
touch-plate and STEP preparation settings, simulation/UI/live preferences,
homing and commissioning records, automatic-continuation review context, the
safety-input audit, and `job-recovery.json`. Connection settings are rewritten
from supported host/port/transport fields; unknown fields such as tokens or
passwords are discarded. Project files, generated jobs, logs, the backend
discovery record, and the backend owner marker are not copied. The migration
manifest records source and destination SHA-256 values (and notes transformed
files); run `.\.venv\Scripts\pine-migrate-data.exe verify <new-root>` to check
the destination.

Migration leaves the source untouched for rollback. It refuses a live backend
owner and creates the new root atomically only after the staged copy verifies.
The source root is briefly marked while migration runs; Pine startup on that
root waits for the migration to finish. If a process was interrupted and left
the marker behind, confirm no migration process remains, then remove the exact
`.pine-data-migration.lock` file. Migration does not switch the GUI to the new
root. Launch it explicitly with `--data-root <new-root>` after reviewing the
copy. The old backend ownership and its discovery token stay with the source;
the new root will acquire its own ownership metadata when Pine starts there.

## Client loss and reconnect

Closing the GUI calls the adapter's frontend-only `close()` and does not invoke
backend shutdown. A dropped client has no lease authority over an active job:
the backend continues polling and streaming. A new GUI or CLI client attaches
with the discovery token, obtains a full snapshot, then replays events after its
cursor. If the session identity changes, the cursor is reset and the client
must rebuild from the new snapshot before enabling actions.

`BackendClient.heartbeat()` is an authenticated, read-only health request. It is
diagnostic liveness, not a requirement for active work; losing heartbeats never
pauses, aborts, or disconnects the machine.

## Backend failure

The GUI reports `unavailable` and keeps machine-affecting controls fail-closed.
It does not auto-restart a backend into hardware motion. An operator or test
may explicitly relaunch the backend after confirming the old PID is dead; only
then may the exact stale discovery record be removed. A live PID with failed
health is surfaced as an owner fault rather than replaced.

## Shutdown and recovery

`shutdown` is an explicit operator action. Idle shutdown is accepted. Active
motion or jobs are rejected unless `safe_abort=true` is explicitly supplied;
that path asks the controller to abort before closing and never resumes work.
After controller reset, E-stop, or failed probing, review/preflight and the
required reference/work-zero recovery must be repeated. A reconnect never
restores trust from stale client state.

## Diagnostics

Capture the data-root path, backend PID, session ID, schema/protocol versions,
state revision, latest event sequence, capability snapshot, and structured
error code. Do not copy authentication tokens into logs or bug reports. The
authoritative evidence commands are:

```powershell
pine-cli --root <data-root> status --json
pine-cli --root <data-root> capabilities --json
pine-cli --root <data-root> events --after 0 --limit 500 --json
```

Only loopback transport is supported by this contract. Physical E-stop wiring,
power removal, and commissioning remain separately authorized work and are not
proven by a healthy software status or controller reset message.
