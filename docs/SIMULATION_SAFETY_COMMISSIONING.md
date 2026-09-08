# Safety inputs and automated XYZ datum

This document describes the software contract only. The digital twin is
loopback-only and never drives GPIO, a controller reset pin, USB/COM, or a
physical machine.

## Homing and limits

Each machine-scoped declaration names X, Y, or Z, the homing end (`min` by
default), nominal travel and any measured maximum override, input pin,
active-low polarity, debounce, and whether the input is a hard limit. The
configuration fingerprint is included in the commissioning record. Any change
to travel, end, polarity, pin, or hard-limit mode invalidates that record.

Commissioning tests each axis input independently in the sequence inactive →
active → released, confirms direction/end, and then runs a homing cycle. A
GRBL `$22` value of 1 enables homing, `$23` declares the direction mask, `$5`
declares limit polarity, and `$21` enables hard limits in the twin. A `Pn:X/Y/Z`
status field is observation telemetry; it is not a physical switch guarantee.

## E-stop boundary

The safety-rated physical power cutoff remains the primary protection. A GRBL
reset pin can stop a controller but may provide no feedback. The versioned
declaration therefore supports `disabled`, `reset_only`, `feedback_only`, and
`reset_plus_feedback`, with active-low polarity, debounce, a latched state, and
manual recovery. A latched event stops scheduling, requests spindle-off/hold
when possible, invalidates reference/work-zero trust, and blocks motion,
probing, homing, and restart until the input is released, the controller is
known Idle, and the user explicitly resets and re-references. Contradictory,
missing, or stale feedback fails closed. The twin can inject these transitions
for deterministic tests; it never emits a real reset or GPIO write.

## Automated XYZ calibration plate

The `Auto XYZ calibration plate` workflow is separate from the existing manual
`Zero X`, `Zero Y`, `Zero Z`, and `Zero XYZ` actions. It remains unavailable
until a machine-scoped plate/input record is current. The plate definition
stores diameter, thickness, tool-radius compensation, safe-Z, bounded search
distance/feed, and repeatability tolerance.

The workflow requires trusted reference, Idle and spindle-off state plus an
explicit interior seed. It retracts to safe Z, collects at least four bounded
orthogonal contact points, fits the circle with a residual check, compensates
for tool radius, moves outside the circle, and uses the existing two-stage Z
touch before setting only G54. No contact or vision signal means refusal to
guess. Every move is subject to the twin and independent-operator collision
checks; stale WCO, E-stop, switch alarm, collision, uncertain feedback, or
out-of-envelope motion fails closed and leaves work zero unconfirmed.

Before any future physical commissioning, verify: power removal and E-stop are
within reach; spindle is off; workholding and tool are secure; all switch and
probe inputs are tested with no axis motion; the exact endpoint is explicitly
authorized; and abort criteria are understood. This checklist is inert and
does not authorize or execute physical commissioning.
