# TTC 3018 Digital Twin

Pine's Digital Twin is a software-in-the-loop controller and machine model for
development and regression testing when a physical CNC is unavailable.

It is deliberately connected through the same GRBL byte boundary as the real
MKS DLC32: Pine's ordinary `TcpGrblConnection` connects to an ephemeral
`127.0.0.1` endpoint owned by a twin backend process. The backend contains an
independent inbound GRBL parser, planner, spindle model, and deterministic
three-axis plant. A second Windows-spawned supervisor process observes immutable
telemetry and independently evaluates safety hazards. Neither process can write
Pine's application state.

## What is modelled

The default profile uses the stated TTC 3018 usable travel:

| Axis | Travel | Convention |
| --- | ---: | --- |
| X | 290 mm | positive from the virtual reference |
| Y | 170 mm | positive from the virtual reference |
| Z | 40 mm | positive/up from the virtual reference |

The plant tracks continuous position, velocity, coordinated linear and G17
arc motion, feed, hold/resume/jog cancel/reset, spindle acceleration and actual
RPM, work-coordinate offsets, probe contact, and virtual travel limits. Status
reports are generated from the same snapshot used for animation, so MPos, WPos,
WCO, feed, spindle and Bf remain internally consistent.

The visual machine is a parametric 3018 proxy: base/bed, Y table, uprights, X
gantry/carriage, Z carriage, spindle, holder, and cutter. Travel values are
authoritative. Frame and body dimensions are conservative visual/collision
proxies, not manufacturer CAD measurements; the simulator labels them as such.

The executed-stock model is a bounded height grid. It can sweep the actual tool
through stock, report removed/remaining/gouged/uncovered volume, and compare a
supported 2.5D target. The default target is
`examples/showcase-pocket-island.step` (40 x 30 x 5 mm, with a retained island),
loaded through the existing isolated OpenCASCADE importer. Unsupported geometry
is explicitly collision-only; it is never presented as a verified finished part.

## Starting a session

Open Pine's normal **Connect** dialog and select **Virtual Machine (Digital
Twin)**. Physical serial and Wi-Fi fields disappear. Choose a simulation speed
and workpiece, then select **Start Digital Twin**. The main window and simulator
window show `DIGITAL TWIN — NO PHYSICAL MACHINE`.

The simulator window is an observation surface. Its rendered machine view and
visual window close guard cannot advance machine time or issue GRBL commands. Use Pine's
normal reference, jog, work-zero, spindle, job, pause, resume, abort and
disconnect controls. The supervisor is shown as healthy while its heartbeat is
fresh; a supervisor failure is a safety error, not a successful run.

Simulation state is volatile. Simulation settings, workpiece choice, faults and
traces are stored separately from physical connection, machine, work-zero and
probe files. Starting or ending a session never makes a simulated reference or
work zero trusted on a physical machine.

## Collision semantics

The backend and supervisor evaluate swept transitions, not just endpoints. The
following hazards are distinct in the trace and simulator view:

- virtual travel/limit violation;
- machine-frame or moving-body collision;
- tool or holder versus stock;
- tool or holder versus fixture/clamp;
- tool versus bed/spoilboard;
- rapid entry into stock;
- spindle-off entry into stock;
- excessive depth and retained-part gouge;
- commanded/executed pose divergence; and
- unavailable supervisor or malformed protocol telemetry.

Legitimate spinning-tool material removal is not itself a collision. Expected
joint contacts are explicit allow-listed pairs. A fixture, holder or bed
intersection remains a hazard even when the cutter is spinning. On a hazard the
supervisor emits evidence and the runtime sends a normal virtual interlock;
the controller enters Alarm and Pine observes that through its ordinary GRBL
response path.

## Headless verification

Run the deterministic scenario CLI from the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m ttc3018_control.simulation.verify `
  --all --output C:\Temp\pine-twin-evidence
```

The output contains `summary.json` and `report.md`, including scenario result,
final pose/state, trace digest, seed and assertion failures. The same
profile/scenario/seed produces the same normalized semantic result regardless
of display frame cadence or accelerated clock mode.

For feature tests, prefer the simulation fixtures and deterministic clock over
ad-hoc fake transports when controller, status, motion, collision or stock
behavior is part of the feature. The backend can also be tested directly with
an unmodified `TcpGrblConnection`; this is the strongest check that the
application is using the same connection contract as hardware.

## Evidence and replay

The trace/evidence primitives support normalized TX/RX lines, parser and modal
transitions, queue and motion blocks, status snapshots, spindle changes, stock
metrics, hazards, supervisor heartbeats, faults, user intents/outcomes and
final state. The built-in headless CLI currently records scenario intents,
final state, hazards, and deterministic trace events; an embedding test or
application session can record the richer transport events through
`TraceRecorder`. Canonical JSON removes only declared environment noise such
as process ID, random loopback port and wall-clock timestamp. Exported Markdown
contains the canonical SHA-256 digest.

Do not treat a green scenario as proof of physical safety. It proves that the
software's command ownership, state transitions, safety gates and virtual
geometry behaved as specified for that input.

## Later twin-versus-machine A/B commissioning

Physical A/B testing is a separate activity and is not part of ordinary
simulation execution. It requires an explicit user request, a supervised
session, and a machine-specific safety review. The parity module is inert unless
an endpoint is explicitly selected and authorization is supplied.

The prepared procedure is:

1. **Twin baseline.** Run the exact script against the twin and save its
   canonical trace, profile hash, scenario seed, and expected tolerances.
2. **Physical read-only gate.** With spindle off and emergency power removal
   available, connect only to the explicitly selected controller. Capture the
   startup banner, `$I`, `$G`, `$#`, `$$` and fresh Idle status. Abort on alarm,
   malformed report, unexpected firmware/settings or uncertain physical pose.
3. **Tiny motion gate.** After a trusted manual reference, perform only bounded
   spindle-off X/Y/Z jogs that remain well inside the measured envelope. Compare
   state, MPos/WPos/WCO, feed, Bf and acknowledgement ordering. Abort on any
   unexpected movement or discrepancy.
4. **Work-offset gate.** Perform a reversible work-offset round trip with
   explicit expected values and fresh confirmation. Do not infer machine geometry
   or rewrite offsets from a mismatch.
5. **Optional accessory gates.** Probe, spindle and cutting tests are separate
   approvals with their own physical preflight, tool/plate/workholding checks,
   emergency stop readiness and abort criteria. They are never implied by a
   passing read-only or jog comparison.
6. **Compare and report.** Normalize only declared firmware/hardware variability.
   Report every ignored field, coordinate/timing distribution, reordered/missing
   response, outlier and unexplained difference. A/B output may suggest a twin
   calibration investigation; it never auto-tunes the model or claims that the
   physical machine is safe.

## Limitations

The twin does not model cutting forces, motor torque, thermal behavior, chatter,
tool deflection, runout, missed steps, workholding strength or general arbitrary
3D material physics. A collision-free virtual run is not an air-cut approval and
does not replace a physical emergency-stop, enclosure, tool, stock or workholding
checklist. Physical acceptance remains a supervised, separately authorized step.
