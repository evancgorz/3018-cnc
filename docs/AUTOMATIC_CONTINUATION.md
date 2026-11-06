# Automatic job continuation

The operator can enable automatic continuation for the loaded, saved program:

```powershell
.\.venv\Scripts\pine-cli.exe --root . automatic-continuation --enabled true --confirm
```

This binds permission to that exact program, machine configuration and confirmed
saved XYZ work zero. The backend exposes `automatic_continuation` in status with
its state, reason and attempt count. The policy and original-source mapping are
recorded in `config/automatic-continuation.json`; backend restart requires an
explicit re-enable. It does not silently restore cutting permission from disk.

Following a connection-loss job failure, the existing watchdog reconnects,
acknowledges spindle stop, obtains fresh Idle/0-RPM status and homes. Automatic
continuation then returns through the existing safe saved-zero motion workflow.
It waits for a new fresh Idle/0-RPM report, trusted reference, completed motion,
confirmed work offset matching the saved offset and XYZ work position within
0.01 mm of zero. Existing application authorization, preflight and independent
safety-input checks apply before restarting.

Replay begins at the previous complete retract/XY-rapid/approach/plunge boundary
at least 32 accepted commands before the loss. Accepted commands are not physical
positions. Overlap recuts the uncertain planner/RX queue; it never skips to the
next boundary. Generated suffixes preserve the exact remaining executable path,
use fresh absolute metric G54 setup and the original spindle setting, and end
with M5/M2. Programs with other modal operations, arcs, tool changes, intermediate
spindle changes or no recognizable safe entry are rejected with a reason.

The current implementation allows three continuation attempts per enable.
Wi-Fi recovery itself uses the existing bounded retry delays. Work-zero return
times out after 120 seconds. Explicit pause, abort, stop, manual motion, work-zero
or relevant machine/tool configuration changes cancel permission. Independent
safety-input trips cancel it. Non-connection job failures do not auto-restart.

This feature is source-only until the normal backend restart activates it.
Enabling it does not require restarting or interrupting a running job once that
backend version is active. The unchanged physical cutter/fixture is an operator
assumption; the software cannot detect an unreported cutter swap or moved stock.
