# Movable Z Touch Plate / Puck

Pine treats a rigid cylindrical puck as a movable Z touch plate. It is a
workpiece datum, not a permanently mounted tool setter and it does not create a
tool-length offset.

## How it is used

1. Measure the puck thickness with calipers and enter it in Machine setup.
2. Confirm the probe input with `Test input (no motion)`. Pine expects an open,
   active, then open transition and never changes GRBL `$6` automatically.
3. Home the machine successfully; incomplete X/Y/Z homing-switch commissioning
   blocks the workflow and no manual reference fallback is available.
4. Move to the point where Z should be measured. A confirmed X/Y work zero is
   not required; the Z probe uses the current X/Y position and leaves both
   X/Y work offsets unchanged.
5. Place the puck flat on the workpiece, attach the probe lead to the cutter,
   turn the spindle off, and confirm the tool is above the puck.
6. Choose `Probe work Z`. Pine performs a bounded fast touch, retract, release
   check, and slow touch. It then sends only the Z work-offset update, leaving
   X/Y unchanged.
7. Wait for the verified offset and straight-up retract at the same X/Y. The
   result dialog appears only after a fresh spindle-off Idle report confirms
   the retract. It shows the measured contact Z and configured puck thickness.
8. Remove both puck and clip. Click `Continue to work Z0` once. This is the
   single confirmation for a slow Z-only descent to the calculated material
   surface. No machine homing or XY travel is part of this routine.
9. Wait for the completion message: Pine requires the movement acknowledgment
   and a later fresh Idle report at the target before saying the tool is at Z0.
   Do not interpret an acknowledgment alone as completed motion.

The configured thickness is the distance from the workpiece surface to the
touching cutter. Pine writes the absolute G54 Z offset as the slow-touch
machine coordinate minus the measured puck thickness. This uses the reported
probe trigger position, so probe deceleration after contact does not shift the
workpiece datum; X/Y offsets remain unchanged.

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
  is not treated as a successful datum. If the offset write has already been
  sent, Pine invalidates work-zero trust; verify or set the work zero again
  before machining.
- Per-axis homing/limit declarations are available in Machine Setup, and the
  Auto XYZ fixture plus E-stop exercises are available only in the
  simulation-only digital twin. Physical commissioning remains explicit and
  must be performed separately; hardware-free validation never certifies
  physical safety or GPIO/reset wiring.

Physical acceptance still requires a supervised continuity check, emergency-stop
check, repeatability check, Z accuracy check, puck-removal check, and air cut.


## Completion and recovery

Continue is rejected if position, reference, session, puck settings or work zero
changed, the probe remains active, the spindle is not known off, or another
operation is active. The target is checked against the trusted machine envelope.
There is no wall-clock expiry while waiting for the operator to remove the puck;
a fresh machine state is checked when Continue is clicked. A failed/reset or
canceled completion invalidates work-zero trust and cannot silently enable a job.
The older removal-acknowledgment API cannot bypass an active completion flow.

The flow assumes X/Y zero is already set and the tool is above the puck. It
never starts the spindle, locates X/Y, moves to machine home, or runs a job.
