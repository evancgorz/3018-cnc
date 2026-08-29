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
- Invalidates position trust after disconnect, serial error, startup, or reset.
- Sets GRBL work zero for individual axes or XYZ using `G10 L20`.
- Retracts Z to a configured safe height at no more than 100 mm/min.
- Provides a gated commissioning workspace for home switches and an XYZ touch plate.
- Requires isolated press-and-release electrical tests before homing can be attempted.
- Reviews and applies only the GRBL settings needed for first commissioning.
- Keeps hard and soft limits off for the first homing cycle, then offers a separately confirmed protection step.

This version deliberately has no spindle-start button, arbitrary command box,
automatic probe motion, or G-code file streaming. Those features should be added
after commissioning and the safety controls have been exercised.

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

Do not expose its GRBL TCP port to the public internet. Guest networks with
client isolation may prevent the PC from reaching the controller. Wi-Fi loss
invalidates the application's virtual reference; physical power removal remains
the primary emergency stop.

## Safety

Until all switches are commissioned and a homing cycle succeeds, the machine
cannot prove its physical position. Even afterward, a stall, wiring fault, or
manual movement can invalidate coordinates. Keep the cutting area clear and
remain ready to use physical power removal or the emergency stop.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
