# Movable Z Touch Plate / Puck

Pine treats a rigid cylindrical puck as a movable Z touch plate. It is a
workpiece datum, not a permanently mounted tool setter and it does not create a
tool-length offset.

## How it is used

1. Measure the puck thickness with calipers and enter it in Machine setup.
2. Confirm the probe input with `Test input (no motion)`. Pine expects an open,
   active, then open transition and never changes GRBL `$6` automatically.
3. Establish the machine reference manually if the 3018 has no homing switches.
4. Set and confirm the X/Y work zero on the material.
5. Place the puck flat on the workpiece, attach the probe lead to the cutter,
   turn the spindle off, and confirm the tool is above the puck.
6. Choose `Probe work Z`. Pine performs a bounded fast touch, retract, release
   check, and slow touch. It then sends only the Z work-offset update, leaving
   X/Y unchanged.
7. Wait for the fresh GRBL work-offset confirmation, retract to safety, remove
   the puck and clip, and acknowledge their removal before starting a job.

The configured thickness is the distance from the workpiece surface to the
touching cutter. After `G10 L20 P1 Z<plate thickness>` is confirmed, the
workpiece surface is work Z0.

## Commissioning

Commissioning runs three supervised double-touch samples on a known flat
surface. Pine records the slow-touch trigger positions and accepts the plate
only when their spread is within the configured repeatability tolerance. The
thickness remains the operator's measured value; Pine never infers it from a
probe position.

If the plate, wiring, feeds, search distance, retract, tolerance, machine
travel, or reference geometry changes, the commissioning evidence becomes
stale and must be reviewed again.

## Safety boundaries

- All probe distances and retracts are checked against the trusted virtual
  envelope before motion.
- Probing requires a connected Idle controller, fresh position/work-offset
  information, spindle off, an open input, and no competing motion or job.
- A failed, stale, alarmed, cancelled, timed-out, or disconnected transaction
  changes no work offset and is not treated as a successful datum.
- Per-axis homing/limit declarations are available in Machine Setup, and the
  Auto XYZ fixture plus E-stop exercises are available only in the
  simulation-only digital twin. Physical commissioning remains explicit and
  must be performed separately; hardware-free validation never certifies
  physical safety or GPIO/reset wiring.

Physical acceptance still requires a supervised continuity check, emergency-stop
check, repeatability check, Z accuracy check, puck-removal check, and air cut.
