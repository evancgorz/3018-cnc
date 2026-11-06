# Independent safety-input contract

This document records the software boundary implemented for C-013. It does
not commission a machine, select electrical parts, or authorize wiring,
energization, or power-removal acceptance.

## Adapter boundary

The Qt-free backend owns a typed `SafetyInputAdapter`. Each sample contains
two normally-closed channel observations, a monotonic sample timestamp, the
backend session identity, a source label, and non-secret raw input fields.
`True` means that a channel is closed and electrically healthy; `False` means
open/active; `None` means that the channel could not be observed.

`FakeSafetyInputAdapter` is the only concrete adapter in this software-only
slice. It is deterministic and hardware-inert. A future physical adapter must
be separately reviewed and must not reuse an axis-limit, probe, I2C, or
undocumented controller pin.

## State and recovery

The backend publishes `clear`, `active`, `latched`, `unknown`, or `fault` with
timestamps, both raw channel states, sample count, debounce and stale limits,
session identity, adapter availability, power-removal status, and a reason.

- Open, disagreeing, missing, stale, future-dated, or wrong-session feedback
  latches the software safety state immediately.
- Both channels must be closed and fresh for the configured settling interval
  before a clear candidate is observable.
- A latched state never clears automatically. An explicit backend or CLI
  acknowledgement is accepted only after the settled clear candidate is
  present.
- The software slice leaves hazardous-power removal as `unknown`; an input
  channel returning closed is not measured proof that spindle/driver power has
  dropped. That unknown state continues to block non-recovery actions.
- A trip performs best-effort secondary hold, spindle-stop, jog/probe abort,
  and job abort actions, then invalidates reference, work zero, run
  authorization, and software commissioning trust. These software actions are
  never the primary hazardous-power stop.
- Latched transitions are appended to `safety-input.audit.jsonl`. A new
  commissioned backend restores the prior latch and requires fresh feedback;
  a backend restart is never treated as a physical reset.

Diagnostics remain available while latched. `status` includes the same
`safety.physical_estop` object exposed by `safety-input-status`; the CLI also
offers `acknowledge-safety-input --confirm`. No motion, spindle start,
probing, homing, job start, or other non-recovery action is accepted while a
commissioned safety input is latched.

The independent physical portion remains uncommissioned until a
machine-specific electrical review records the maintained NC dual-channel
topology, safety relay/contactor, isolated auxiliary feedback adapter, exact
parts and schematic, measured continuity, measured hazardous-power removal,
and final acceptance with the GUI closed.
