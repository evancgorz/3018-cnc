# CNC Platform Backlog — Rollout Step 10+

This document is intentionally backlog-only. None of the capabilities below are commissioned or available as production controls in the current application.

## Gantry and controller capabilities

### Independent dual-motor homing and squaring

- Prerequisites: controller firmware with separately addressable gantry motors and independent limit inputs, or a verified external squaring controller.
- Safety: never move both motors independently without a known kinematic model, switch polarity, current limits, and a recovery path after one side triggers first.
- Extension point: add a controller-adapter capability and a per-motor axis model; do not overload the current single-axis `AxisDefinition`.
- Future tests: trigger each side independently, verify skew correction bounds, timeout/alarm handling, and no squaring claim on stock GRBL 1.1.

### Stepper enable/disable and idle policy

- Prerequisites: firmware/driver output with explicit enable semantics and a known consequence of releasing holding torque.
- Safety: disabling can lose position and invalidate homing/reference trust; the app must clear trust unless position is independently verified.
- Extension point: controller adapter and lifecycle policy, with per-axis enable state.
- Future tests: enable acknowledgement, disconnect/reset, idle timeout, and position-trust invalidation.

## Auxiliary outputs and safety inputs

### Coolant/mist, air assist, dust collection, and vacuum

- Prerequisites: mapped controller outputs, electrical ratings, interlocks, and a safe default-off policy.
- Safety: output ordering, spindle synchronization, emergency-stop behavior, and unexpected output state must be fail closed.
- Extension point: typed auxiliary-output declarations and adapter command/capability contracts.
- Future tests: startup/shutdown ordering, job pause/abort/failure, disconnect, and output feedback where available.

### Door, interlock, and E-stop feedback

- Prerequisites: a controller input with documented alarm semantics or a safety relay independent of application software.
- Safety: an application notification is not a substitute for a safety-rated E-stop. Any uncertain signal must stop/hold and invalidate motion trust as appropriate.
- Extension point: safety-input adapter and a first-class safety state in application state.
- Future tests: debounce, stuck input, open/close during jog/job/probe, reconnect, and recovery authorization.

### Spindle RPM feedback

- Prerequisites: tachometer/encoder feedback and controller support for actual RPM.
- Safety: distinguish commanded RPM from measured RPM; define minimum-speed interlock and timeout.
- Extension point: spindle capability and status report model.
- Future tests: startup ramp, underspeed, overspeed, loss of feedback, pause, and M5 confirmation.

## Future machine types

### Rotary axes

- Prerequisites: controller kinematics and safe rotary envelope model.
- Safety: angular units, wrap behavior, cable limits, and collision checking require a different envelope than the current XYZ-only model.
- Extension point: axis-kind enum, kinematics adapter, and job bounds validator.
- Future tests: wrap/unwrap, shortest-path policy, limits, homing, and transformed job bounds.

### Tool changers

- Prerequisites: documented tool-change mechanism, tool table, sensors, and a safe parked position.
- Safety: tool identity and clamp state must be confirmed before motion; failure must stop with spindle off.
- Extension point: tool lifecycle service layered over the existing tool-setter/TLO service.
- Future tests: tool mismatch, empty pocket, clamp feedback, failed change, and power loss.

### Sensorless homing and encoders

- Prerequisites: firmware/driver support, reliable signal quality, and repeatability characterization.
- Safety: sensorless detection cannot be treated as a limit switch without measured repeatability and collision limits.
- Extension point: homing/probe adapter capability and evidence model.
- Future tests: repeatability distribution, false positives, missed triggers, and stale evidence.

## Exit criteria for this backlog

Each item requires a concrete adapter, declared schema, commissioning evidence, fail-closed behavior, deterministic fake-controller tests, and a manual hardware validation procedure before it may move into production scope.
