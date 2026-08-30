# TTC 3018 Control

A small, safety-focused desktop controller for the Two Trees TTC 3018 and its
MKS DLC32 GRBL-compatible motion controller.

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
- After a successful job, waits for spindle stop and GRBL Idle, then returns to
  virtual X0 Y0 Z0 through the configured safe-Z clearance.
- Invalidates position trust after disconnect, serial error, startup, or reset.
- Sets GRBL work zero for individual axes or XYZ using `G10 L20`.
- Retracts Z to a configured safe height at no more than 100 mm/min.
- Loads and validates pre-sliced metric G-code files.
- Rejects probing, reference-changing commands, tool changes, inch-mode jobs, and unsupported commands.
- Calculates XYZ job bounds and checks them against the session's virtual machine envelope and current GRBL work offset.
- Displays a lightweight XY toolpath preview with rapid and cutting moves distinguished.
- Streams one G-code command at a time and waits for GRBL acknowledgement before continuing.
- Provides guarded spindle start/stop plus job start, pause, resume, abort, and progress controls.
- Provides a plaque builder with title/subtitle layouts, six centerline border styles, and a live preview.
- After a successful job, returns through safe Z to the confirmed GRBL work X0 Y0 Z0 when it remains inside the trusted envelope.
- Stops sending on GRBL errors or alarms and requests spindle stop on completion or failure.
- Provides a gated commissioning workspace for home switches and an XYZ touch plate.
- Requires isolated press-and-release electrical tests before homing can be attempted.
- Reviews and applies only the GRBL settings needed for first commissioning.
- Keeps hard and soft limits off for the first homing cycle, then offers a separately confirmed protection step.

This version deliberately has no arbitrary command box or automatic probe motion.
Automatic `$H` homing is unavailable until home switches have been installed and
commissioned. Manual machine reference and work-zero setup are required for every
connection/reset session before an engraving job can start.

## Manual setup and engraving workflow

With no home switches or probe installed, machine reference and work zero are
separate manual operations:

For normal operation, select **Guided Setup Wizard…** after launching the app.
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
   GRBL; the job cannot resume and all manual references must be re-established.

The MVP accepts common metric engraving programs using G0/G1 and I/J-form G2/G3
arcs. Radius-form (`R`) arcs, inch mode, probing, automatic homing, tool changes,
and commands that alter coordinate references are rejected. Re-export such files
from the CAM program with millimeters and I/J arc centers, or linearize the arcs.

## Creating a text engraving

Select **Create Text…** in the Engraving Job panel, or select **Create text
engraving…** during the G-code step in Guided Wizard Mode. Enter one or more lines
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

## Creating a plaque

Select **Create Plaque…** in the Engraving Job panel. The plaque builder places the
lower-left plaque corner at work `X0 Y0`, supports title and optional subtitle text,
and offers Rectangle, Rounded Rectangle, Double-line, Inset-corner, Scallop, and
Simple Flourish borders. Its live preview is generated from the same centerline
geometry that becomes G-code.

## Commissioning new switches and probe

Open **Commissioning…**. Merely opening the workspace never sends a command.
Complete the tabs in order:

1. With the machine stationary, release every switch and leave the probe circuit
   open. The live input display should say `none`. Individually test X, Y, Z, and
   the probe by pressing/closing and then releasing only that circuit. A coupled
   or already-active signal fails or blocks the test.
   If inputs are active at rest, use **Read current settings**, change only
   `$5`/`$6`, and select **Apply input polarity…**. This cannot move the machine
   and deliberately clears all earlier electrical test results.
2. Confirm the already-tested positive motion directions. Read `$$` from GRBL,
   then review every commissioning value. `$5` controls limit-input polarity,
   `$6` controls probe polarity, and `$23` selects which homing directions are
   reversed (X=1, Y=2, Z=4). Derive `$23` from the installed switch locations;
   do not guess.
3. The first settings application requires `$20=0`, `$21=0`, and `$22=1`, so
   neither soft nor hard limits can complicate the initial homing test. Conservative
   default homing speeds are supplied, while polarity, direction, and travel values
   must be explicitly read or entered.
4. Clear the machine, raise the tool away from fixtures, keep one hand at physical
   power, and run the separately confirmed first homing cycle. Confirm success only
   if every axis reached its intended switch, stopped, pulled off, and GRBL returned
   to `Idle`.
5. After successful homing, use **Enable protections…** to write `$21=1` and
   `$20=1`. Test the limits cautiously at low speed before relying on them.
6. Measure the XYZ plate with calipers and save its actual thickness and edge/hole
   geometry. The plate is normally placed temporarily on the workpiece and removed
   after setting work coordinates. Electrical probe validation is included; probe
   motion remains intentionally locked until a separate probing routine is designed.

Commissioning progress and plate measurements are saved locally in
`config/commissioning.json`. They are not committed to Git.

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

Double-click `run.bat` in File Explorer, or run it from Command Prompt:

```bat
run.bat
```

The batch launcher automatically runs setup if the project virtual environment
is missing and keeps its console open when startup fails so the error remains
visible. PowerShell users can alternatively run:

```powershell
.\run.ps1
```

Select `COM3 — USB-SERIAL CH340`, connect, and wait for `Idle` before jogging.

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
