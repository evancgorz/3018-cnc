# TTC 3018 Control

A small, safety-focused Qt Quick desktop controller for the Two Trees TTC 3018
and its MKS DLC32 GRBL-compatible motion controller. The production launcher is
the PySide6/Qt Quick interface; the former Tk implementation remains in the
source tree only as a reference during the migration.

## Current capabilities

- Keeps one persistent USB serial connection open.
- Connects through either USB serial or the DLC32's raw Wi-Fi TCP stream.
- Detects Windows COM ports and defaults to the detected COM3 controller.
- Polls and displays live GRBL state and reported XYZ position.
- Provides guarded incremental X, Y, and Z jogging.
- Labels positive Z as up, based on the tested machine direction.
- Sends jogs only while GRBL reports `Idle`.
- Provides feed hold, resume, jog cancel, and confirmed soft reset.
- Records every transmitted and received message in `logs/`.
- Saves a machine profile with measured X/Y/Z travel and a safe-Z height.
- Maintains a session-only virtual reference and coordinate display.
- Checks referenced jog endpoints against the configured virtual envelope.
- Accepts virtual XYZ targets, rejects coordinates outside the configured travel,
  and reaches them by raising to safe Z before lateral motion.
- After a successful job, waits for spindle stop and GRBL Idle, then returns through
  safe Z to the confirmed GRBL work X0 Y0 Z0 when it remains inside the trusted envelope.
- Invalidates position trust after disconnect, serial error, startup, or an uncontrolled reset; a confirmed operator abort retains references while the controller remains powered and connected.
- Sets GRBL work zero for individual axes or XYZ using `G10 L20`.
- Retracts Z to a configured safe height at no more than 100 mm/min.
- Loads and validates pre-sliced metric G-code files.
- Rejects probing, reference-changing commands, tool changes, inch-mode jobs, and unsupported commands.
- Calculates XYZ job bounds and checks them against the session's virtual machine envelope and current GRBL work offset.
- Persists a confirmed XYZ work zero and restores it only after a fresh GRBL report matches the saved work offset.
- Displays a lightweight XY toolpath preview with rapid and cutting moves distinguished.
- Streams one G-code command at a time and waits for GRBL acknowledgement before continuing.
- Provides guarded spindle start/stop plus job start, pause, resume, abort, and progress controls.
- Provides a plaque builder with title/subtitle layouts, six centerline border styles, and a live preview.
- Stops sending on GRBL errors or alarms and requests spindle stop on completion or failure.

This version deliberately has no arbitrary command box or automatic probe motion.
Automatic `$H` homing is unavailable until home switches have been installed and
commissioned. Manual machine reference and work-zero setup are required for every
connection/reset session before an engraving job can start.

## Application architecture

The production app is a modular monolith: Qt Quick/QML is the presentation
layer, `ControllerViewModel` is a thin Qt adapter, and the Qt-independent
`ApplicationController` coordinates connection, motion, job, generation, and
machine-session services. The controller owns transport access and command
ordering; QML never sends GRBL commands or makes safety decisions. This keeps
the local desktop deployment simple while leaving a clean seam for a future CLI
or API adapter if headless or remote control becomes a real requirement. See
[`docs/ARCHITECTURE_DECISION_RECORD.md`](docs/ARCHITECTURE_DECISION_RECORD.md).

## Manual setup and engraving workflow

With no home switches or probe installed, machine reference and work zero are
separate manual operations:

For normal operation, select **Guided Setup** after launching the app.
Guided Wizard Mode presents the complete workflow as nine explained, state-gated
steps: manual-operation safety, controller connection, measured machine profile,
manual machine reference, XYZ work zero, G-code loading, preview/envelope review,
physical preflight, and guarded job start. The wizard will not advance when the
application cannot verify a required state. All motion and spindle actions remain
explicit operator actions.

1. Connect and wait for GRBL to report `Idle` with a machine position.
2. Save a valid machine profile containing measured X/Y/Z usable travel and a
   safe-Z position.
3. With the spindle off, use cautious unreferenced jogs to place the machine at
   the chosen X-negative, Y-negative, and Z-negative physical reference. Select
   **Establish reference here**. The application assumes all usable travel is in
   the positive direction from this location.
4. Jog to the engraving's intended work origin. For a typical engraving this is
   an X/Y corner or center and the material surface for Z. Select **Zero XYZ** (or
   zero the axes individually). This changes work coordinates without moving.
5. Wait for a fresh work-offset/status report, then select **Load G-code…**. Only
   pre-sliced metric G-code is accepted. Review the file name, bounds, and XY
   preview.
6. If the file does not control the spindle itself, set the RPM and select
   **Start spindle…**. Secure the tool and material and keep physical emergency
   power within reach.
7. Select **Start job…** and read the final preflight confirmation. The job is
   sent conservatively, one acknowledged command at a time.
8. **Pause** uses GRBL feed hold and is resumable. **Abort** feed-holds and resets
   GRBL; the job cannot resume, but references are retained while the controller
   stays connected and powered.

The MVP accepts common metric engraving programs using G0/G1 and I/J-form G2/G3
arcs. Radius-form (`R`) arcs, inch mode, probing, automatic homing, tool changes,
and commands that alter coordinate references are rejected. Re-export such files
from the CAM program with millimeters and I/J arc centers, or linearize the arcs.

## Creating a text engraving

Select **Text engraving** in the **Prepare** workspace. Enter one or more lines
of text and choose:

- Simple, Rounded, Technical, Italic, Script, Playful, or Cursive bundled centerline font
- Live centerline toolpath preview while editing text, font, size, spacing, or alignment
- physical text height in millimeters
- negative engraving depth relative to work Z0
- positive safe-Z clearance
- cutting and plunge feed rates
- letter spacing, line spacing, and alignment

Select **Start spindle in generated job (M3)** and set its RPM when the generated
file should start the spindle itself. Leave it unchecked for an air cut or when
using the separate **Start spindle…** control in the Engraving Job panel. A
manually started spindle is no longer stopped at the beginning of generated text;
all generated programs still request `M5` at completion.

**Generate and Load** sends the generated program through the same parser, bounds
calculation, preview, envelope-fit check, and guarded job controls as an imported
file. **Save G-code…** also writes a reusable `.gcode` or `.nc` file. Generation
never sends machine commands. Spindle startup is included only when explicitly
selected.

The lightweight centerline fonts support letters A–Z (lowercase input uses the
same durable capital forms), digits, spaces, and common engraving punctuation.
Unsupported characters are reported before a program is created. System TrueType
font outlines and filled/pocketed lettering are outside the current text MVP.

## Creating a STEP / 2.5D job

Select **STEP / 2.5D** in the **Prepare** workspace and choose **Import STEP…**.
The bounded workflow imports a `.step` or `.stp` file, selects the largest usable
orthogonal planar face by default, normalizes its closed loops, and shows a
top-view preview. Use **Machining face** to choose XY (top/bottom), XZ
(front/back), or YZ (left/right) when the CAD model is standing on its side;
then use **Path rotation** for the in-plane XY/YX direction. Tilted, open,
unreadable, or otherwise unsupported geometry is rejected with an explanation.

Choose one of these operations:

- Engraving: follows the imported closed loops.
- Detected feature: uses face topology to distinguish a recessed/removed region
  from a raised boss. It clears inside a recess or clears the surrounding base
  face to leave a boss, using each feature's own measured depth from the STEP
  solid.
- Planar surface: follows accessible flat and tilted planar faces as a bounded
  varying-Z raster, including ramp-like parts such as `examples/wedge.step`.
  Abrupt vertical cliffs are split into separate safe paths rather than crossed
  by a diagonal cut.
- Profile cutout: cuts inner loops first and the compensated outer profile last,
  with stock-based through depth, breakthrough allowance, and holding tabs.
- Outside contour or Inside contour: applies the selected tool radius.
- Pocket: clears planar regions with connected alternating scanlines, staying
  down only when the link remains inside the cleared region; holes and islands
  cause safe retracts.
- Hole: cuts circular inner loops with a tool-center path.

The dialog also supports XY/YX orientation, centered or lower-left work zero,
stock width and height, tool diameter, negative depth, multiple depth passes,
safe Z, cut/plunge feeds, and optional `M3` spindle startup. For lower-left
outside/profile jobs, work `X0 Y0` is the lower-left extreme of the compensated
cutter envelope; the raw part boundary is inset/up-right by the tool radius and
no generated XY motion is allowed below work zero. The preview draws the raw
part boundary separately from the cutter path and reports cut distance, rapid
distance, and retract count. Flat pocket and detected-feature jobs pass a
deterministic swept-cutter stock-coverage simulation, while planar-surface jobs
also check the varying-Z height field and slope. Tool-unreachable corner
material is reported separately from uncovered reachable area. **Generate and load** sends the result through
the same metric parser, bounds checks, preflight, save, and streaming pipeline as
imported G-code; generation itself never moves the machine.

The `examples/removed-cylinder.step` and `examples/extruded-circle.step` fixtures
exercise the topology distinction. They have the same top-view rectangle and
circle, but the first contains a 2 mm circular recess while the second contains
a 2 mm raised circular boss.

This release is intentionally planar. It does not yet perform arbitrary-face
selection, general 3D surface machining, adaptive/rest clearing, full-resolution
stock collision simulation, or CAM-grade lead-in/lead-out compensation. Confirm
the stock, tool, work zero, and machine envelope before starting a generated job.

## Creating a plaque

Select **Plaque builder** in the **Prepare** workspace. The plaque builder places the
lower-left plaque corner at work `X0 Y0`, supports title and optional subtitle text,
and offers Rectangle, Rounded Rectangle, Double-line, Inset-corner, Scallop, and
Simple Flourish borders. Its live preview is generated from the same centerline
geometry that becomes G-code.

Commissioning of switches and probing is intentionally deferred from this Qt
workflow while the machine remains switchless and probe-less.

## Establishing the virtual reference

1. Connect and wait for GRBL to report `Idle`.
2. Use cautious unreferenced jogs to approach the chosen negative end of X, Y,
   and Z. Do not drive an axis against its physical stop.
3. Enter measured usable travel for all three axes and a safe Z between zero
   and the entered Z travel, then select **Save profile**.
4. Select **Establish reference here** and read the confirmation carefully.

The current position becomes virtual `X0 Y0 Z0`, and the allowed envelope runs
from zero to the configured travel in each positive direction. The reference is
never restored across a disconnect or reset because this machine has no sensors
that can prove its physical position.

GRBL work zero is separate from this safety reference. Work zero describes the
origin of the current part; the virtual reference describes the application's
temporary estimate of the machine's usable travel.

## Setup

Open PowerShell in this directory and run:

```powershell
.\setup.ps1
```

## Run

The recommended entry point is the **TTC 3018 Control** desktop shortcut. It is
created or refreshed automatically by `setup.ps1`. You can also double-click
`run.bat` in File Explorer, or run it from Command Prompt. This launches the Qt
Quick interface:

```bat
run.bat
```

The batch launcher automatically runs setup if the project virtual environment
is missing and keeps its console open when startup fails so the error remains
visible. There is one supported application launcher; `setup.ps1` is only for
installing or repairing the environment and desktop shortcut.

Select a detected serial port, connect, and wait for `Idle` before jogging. The
same centered connection dialog also supports Wi-Fi TCP when USB is removed.

## Wireless connection

The detected controller configuration uses access-point mode with:

- Wi-Fi network: `MKS_DLC`
- Controller address: `192.168.4.1`
- Raw GRBL TCP port: `23`
- Browser interface: `http://192.168.4.1/`

To use the desktop application wirelessly, join the controller's Wi-Fi network
in Windows, select **Wi-Fi TCP**, keep `192.168.4.1` and port `23`, then connect.
USB and Wi-Fi are alternative transports for the same GRBL protocol and safety
model. Do not connect two control applications at once.

The preferred permanent setup is station mode, where the controller joins a
trusted 2.4 GHz home network. Connect through USB, wait for `Idle`, select
**Wi-Fi Setup**, and enter the network details. The password remains in
memory only long enough to configure the controller and is redacted from both
transmitted-command and echoed-response logs. After the controller restarts,
the application reads its new address from the DLC32 connection/startup messages,
places it in the Wi-Fi host field, and saves it for subsequent launches. A
successful Wi-Fi connection also becomes the preferred startup transport.
If the saved address is missing or DHCP changes it, selecting **Wi-Fi TCP** and
**Connect** automatically scans the PC's local `/24` network for a port-23 GRBL
status response, saves the verified address, and connects without requiring USB.
USB is still required once to place a controller into station mode and provide
credentials for a reachable 2.4 GHz network.

Do not expose its GRBL TCP port to the public internet. Guest networks with
client isolation may prevent the PC from reaching the controller. Wi-Fi loss
invalidates the application's virtual reference; physical power removal remains
the primary emergency stop.

Routine control feedback appears in the non-modal status strip at the bottom of
the window. Jog commands are ignored while GRBL is not `Idle`; reference,
work-zero, virtual-limit, and similar routine results do not open modal dialogs.
Confirmations remain for spindle start, job start/abort, reset, and potentially
downward safe-Z motion.

## Safety

Until all switches are commissioned and a homing cycle succeeds, the machine
cannot prove its physical position. Even afterward, a stall, wiring fault, or
manual movement can invalidate coordinates. Keep the cutting area clear and
remain ready to use physical power removal or the emergency stop.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
