# Statement of Work: Virtual CNC Machine Simulation Mode

> Future implementation plan. This document is intentionally stored for later work; simulation mode is not implemented by this change.

## Purpose

Add a software-in-the-loop **Virtual Machine** mode to TTC 3018 Control. This mode will allow users and automated tests to operate the application without physical CNC hardware while exercising the same connection, GRBL protocol, motion, reference, work-zero, job-streaming, spindle, and recovery logic used with the real machine.

When connected in simulation mode, a separate animated window will represent the 3018 CNC and respond to commands as physical hardware would.

## Terminology

This feature is a software-in-the-loop simulator rather than true hardware-in-the-loop testing.

User-facing name:

**Virtual Machine (Simulation)**

Internal names may use:

- `SimulationTransport`
- `VirtualGrblController`
- `VirtualMachinePlant`
- `SimulationWindow`

## User workflow

1. Open the normal connection prompt.
2. Open the existing connection-type dropdown.
3. Select one of:

   - USB Serial
   - Wi-Fi TCP
   - Virtual Machine (Simulation)

4. When **Virtual Machine (Simulation)** is selected:

   - Hide or disable USB port, Wi-Fi host, and TCP port controls.
   - Show a short explanation that no physical controller will be accessed.
   - Show an optional virtual machine profile selector.
   - Change the primary action to **Start Simulation**.

5. Selecting **Start Simulation** shall:

   - Create and connect the virtual GRBL transport.
   - Close the connection prompt normally.
   - Open the separate simulator window.
   - Put the main application into its normal connected workflow.
   - Display a persistent indication that simulation mode is active.

6. The user can then:

   - Establish the virtual machine reference.
   - Jog the machine.
   - Set and return to work zero.
   - Generate or load G-code.
   - Start and stop the virtual spindle.
   - Run, pause, resume, or abort jobs.
   - Observe animated machine movement.
   - Test post-job return behavior.

7. Selecting **Disconnect** shall:

   - Stop virtual motion safely.
   - Close the virtual connection.
   - Close the simulator window.
   - Invalidate session trust using the normal disconnect workflow.

## Connection prompt requirements

Add **Virtual Machine (Simulation)** as a third option in the existing connection-type dropdown, directly alongside USB Serial and Wi-Fi TCP.

The simulation option must not be placed in a separate developer menu because it should be easy to discover and should exercise the normal connection workflow.

When simulation is selected, the connection prompt should display:

- Connection type: `Virtual Machine (Simulation)`
- Machine profile selector
- Simulation speed selector:
  - Realtime
  - 2×
  - 5×
  - 10×
- An explanation:
  > Runs a virtual 3018 controller and opens an animated machine window. No serial port or network controller will be accessed.
- Primary button: **Start Simulation**

The physical connection fields must not retain keyboard focus or appear required while simulation is selected.

## Safety and visual distinction

Simulation mode must be unmistakable.

Requirements:

- Display **SIMULATION — NO PHYSICAL MACHINE** in the main application status area.
- Display the same indicator in the simulator window.
- Use a distinct simulation connection icon and color.
- Include simulation mode in logs and exported reports.
- Never allow a physical and simulated transport to be connected simultaneously.
- Never open a COM port or network socket when simulation mode is selected.
- Keep simulated references, work zero, connection settings, and machine state separate from physical-machine persistence.
- A simulated reference or work zero must never become trusted when reconnecting to physical hardware.
- Closing the simulator window must request confirmation if a virtual job is running.
- Simulation mode must not weaken any normal application safety checks.

## Architecture

The simulator must integrate through the existing transport abstraction.

```text
Qt Quick main application
    |
ControllerViewModel
    |
ApplicationController
    |
ConnectionService
    |
    +-- USB Serial transport
    +-- Wi-Fi TCP transport
    +-- Simulation transport
            |
      Virtual GRBL controller
            |
      Virtual machine plant
            |
      Simulator window
```

The simulator must consume the same command bytes that would otherwise be transmitted over USB or TCP.

It must return normal transport events such as:

- Transmitted command log events
- Received GRBL messages
- Connection events
- Disconnection events
- Errors

The simulator must not directly change `MachineSession`, job state, work zero, references, or UI properties.

## Virtual GRBL controller

Implement a deterministic Qt-independent virtual GRBL controller.

### Required GRBL states

- `Idle`
- `Jog`
- `Run`
- `Hold`
- `Alarm`
- Reset/startup
- Optional future `Door` and `Home`

### Required realtime commands

- `?` status request
- `!` feed hold
- `~` resume
- `0x18` soft reset
- `0x85` jog cancel

### Required command support

Support every command that the TTC application can currently generate or transmit, including:

- `$J=...` jogging
- `G0`
- `G1`
- `G2`
- `G3`
- `G10 L20`
- `G17`
- `G21`
- `G40`
- `G49`
- `G54`
- `G80`
- `G90`
- `G91`
- `G94`
- `M0`
- `M1`
- `M2`
- `M3`
- `M4`
- `M5`
- `M30`
- Feed commands
- Spindle-speed commands
- Required GRBL setting and information queries
- DLC32 Wi-Fi configuration commands where useful for testing

Unsupported or malformed commands must produce realistic `error:n` responses.

### Status reporting

Generate GRBL-compatible status reports containing applicable fields:

- State
- Machine position
- Work position
- Work-coordinate offset
- Feed
- Spindle speed
- Pin state
- Planner/buffer information where useful

Examples:

```text
<Idle|MPos:10.000,20.000,5.000|WCO:5.000,10.000,5.000|FS:0,0>
<Jog|MPos:12.350,20.000,5.000|WCO:5.000,10.000,5.000|FS:500,0>
<Run|MPos:30.000,25.000,3.000|WCO:5.000,10.000,5.000|FS:300,12000>
<Hold:0|MPos:30.000,25.000,3.000|WCO:5.000,10.000,5.000|FS:0,12000>
```

Status messages must be delivered asynchronously and independently from command acknowledgements.

### Command acknowledgements

The virtual controller shall:

- Emit one `ok` or `error:n` response for each normal command.
- Keep realtime commands outside the normal acknowledgement queue.
- Separate command acceptance from completion of physical movement.
- Allow status polling while motion is active.
- Preserve command and event ordering deterministically.

## Virtual machine plant

Represent the simulated physical machine independently from the GRBL protocol parser.

### Configurable machine properties

- X travel
- Y travel
- Z travel
- Safe Z
- Maximum feed per axis
- Acceleration per axis
- Steps per millimeter
- Initial machine position
- Default work offset
- Spindle acceleration/deceleration time
- Optional limit-switch availability
- Optional homing capability

Defaults should match the normal TTC 3018 profile.

### Motion behavior

The plant shall:

- Track continuous X/Y/Z machine position.
- Convert machine position to work position using the current work offset.
- Simulate acceleration and deceleration sufficiently for realistic UI behavior.
- Follow linear and arc motion.
- Stop gradually for normal feed hold and jog cancellation.
- Stop immediately or enter alarm when required by the selected fault.
- Enforce configured virtual travel limits.
- Update animation and status reports from the same authoritative position.
- Support realtime and accelerated simulation clocks.
- Produce deterministic results independent of display frame rate.

The simulator is not required to model:

- Cutting forces
- Tool deflection
- Chatter
- Motor torque
- Thermal behavior
- Material physics
- Real missed steps

## Simulator window

Open a separate Qt Quick window when simulation starts.

### Visual elements

Display:

- 3018-style frame
- Machine bed
- X gantry
- Z carriage
- Spindle/tool
- Optional stock block
- Work-zero marker
- Machine-reference marker
- Loaded toolpath
- Current tool position
- Completed toolpath
- Remaining toolpath
- Rapid paths
- Cutting paths
- Current spindle state

A clean isometric or lightweight 3D representation is acceptable. Physical realism is less important than clear, accurate motion.

### Status panel

Show:

- Connection: Simulation
- GRBL state
- Machine X/Y/Z
- Work X/Y/Z
- Work offset
- Feed
- Spindle RPM
- Job progress
- Simulation speed
- Elapsed simulated time

### Controls

Provide:

- Pause animation
- Resume animation
- Realtime
- 2× speed
- 5× speed
- 10× speed
- Fit view
- Reset camera
- Show/hide rapid paths
- Show/hide cutting paths
- Show/hide stock
- Show/hide work and reference markers
- Reset virtual controller
- Power-cycle virtual controller
- Disconnect simulation

Pausing the animation should not necessarily pause the machine. Machine pause must continue to use the main application's normal feed-hold control. If a visual-only pause is provided, label it clearly.

## Toolpath animation

The simulator shall animate the exact commands accepted by the virtual GRBL controller.

Requirements:

- Do not animate from button clicks or preview geometry alone.
- Animate from the virtual machine plant's authoritative position.
- Show G0 motion differently from G1/G2/G3 cutting motion.
- Mark completed cutting segments progressively.
- Update Z motion visibly.
- Animate spindle rotation when spindle state is active.
- Stop spindle animation only when the virtual controller processes `M5` or resets.
- Preserve the loaded preview while allowing the executed path to be compared with it.
- Report a diagnostic if executed motion diverges from the parsed preview beyond tolerance.

## Simulation clock

Implement a deterministic virtual clock.

Requirements:

- Realtime mode approximately follows wall-clock time.
- Accelerated modes advance machine time faster without changing path geometry.
- Automated tests can advance time without sleeping.
- Animation frame rate must not alter final position or event ordering.
- Resetting the simulator resets its clock and pending events.
- Scenario results must be reproducible.

## Fault-injection panel

Provide an optional collapsible developer/test panel in the simulator window.

Supported faults should include:

- Delayed acknowledgement
- Missing acknowledgement
- Duplicate acknowledgement
- `error:n`
- `ALARM:n`
- Reset during motion
- Disconnect immediately
- Disconnect after the next command
- Controller stops responding
- Malformed status message
- Missing work offset
- Unexpected work-offset change
- Stale status report
- Limit activation
- Spindle-stop delay
- GRBL remains in `Run`
- GRBL remains in `Jog`
- Fragmented TCP-style message delivery
- Partial response line

Faults must be deterministic and recorded in the simulation log.

## Predefined scenarios

Ship reusable scenarios for:

1. Normal connect and status acquisition
2. Establish machine reference
3. Set XYZ work zero
4. Incremental jogging
5. Held jogging and release
6. Return to machine reference
7. Return to work zero
8. Successful text engraving
9. Successful plaque job
10. Successful STEP job
11. Pause and resume
12. Abort during cutting
13. Controller reset during jogging
14. Connection loss during a job
15. GRBL error while streaming
16. Alarm during motion
17. Missing fresh work-offset report
18. Spindle-stop acknowledgement delay
19. Post-job return skipped safely
20. Clean simulated shutdown

## Persistence

Simulation configuration shall be stored separately from physical-machine configuration.

Recommended files:

```text
config/simulation-profile.json
config/simulation-state.json
```

Do not place simulated values in:

```text
config/connection.json
config/work-zero.json
config/machine-profile.json
```

unless the persisted record explicitly identifies the value as simulation-only and the physical application cannot consume it.

The safest initial implementation is:

- Persist the simulation profile.
- Do not persist simulated reference trust.
- Do not persist simulated work-zero trust.
- Start each simulation as an unreferenced virtual machine.

## Logging and diagnostics

Simulation logs shall include:

- Simulation start and stop
- Initial profile
- Selected simulation speed
- Every transmitted command
- Every generated response
- State transitions
- Position milestones
- Fault injections
- Disconnect or reset cause
- Final simulated position
- Job completion or failure reason

Allow export of:

- Human-readable log
- Machine-readable JSON event trace
- Final simulator snapshot
- Scenario pass/fail report

Passwords and sensitive Wi-Fi values must remain redacted.

## Automated testing

### Unit tests

Test:

- Command parsing
- Modal-state handling
- Work-coordinate calculations
- Linear and arc interpolation
- Jog execution
- Jog cancellation
- Hold and resume
- Reset behavior
- Spindle state
- Limit enforcement
- Status formatting
- Acknowledgement ordering
- Virtual-clock determinism
- Fault scheduling

### Application integration tests

Using the simulation transport, test complete workflows through `ApplicationController`:

- Connect
- Receive fresh status
- Establish reference
- Set work zero
- Jog
- Move to a coordinate
- Return to reference
- Return to work zero
- Load and stream jobs
- Pause and resume
- Abort and recover
- Complete a job
- Stop spindle
- Return after completion
- Disconnect and invalidate trust

### Qt tests

Test:

- Simulation appears in the connection dropdown.
- Selecting simulation hides physical connection fields.
- Starting simulation closes the connection dialog.
- Simulator window opens.
- Main status clearly shows simulation mode.
- Simulator animation follows controller position.
- Disconnect closes the simulator window.
- Closing during a job requests confirmation.
- No test opens a physical COM port or network socket.

### Deterministic scenario tests

Run every predefined scenario without real-time sleeping and verify:

- Expected state transitions
- Expected transmitted commands
- Expected final position
- Expected work offset
- Expected spindle state
- Expected trust state
- No prohibited command was sent
- No physical transport was constructed

## Acceptance criteria

The feature is complete when:

1. **Virtual Machine (Simulation)** appears under USB Serial and Wi-Fi TCP in the normal connection-type dropdown.
2. Starting simulation opens a separate animated machine window.
3. No serial port or network connection is opened.
4. The main application treats the virtual controller through the normal transport interface.
5. The full reference, work-zero, jog, generator, job, pause, resume, abort, and return workflows operate in simulation.
6. Machine animation is driven by the virtual controller's authoritative position.
7. Position, work offset, state, feed, and spindle reports are internally consistent.
8. Simulation can run in realtime and accelerated time.
9. Fault scenarios are repeatable.
10. Simulated trust and persistence cannot contaminate physical-machine state.
11. Existing USB, Wi-Fi, safety, parser, generation, and job-streaming tests continue to pass.
12. Automated tests prove that simulation mode cannot instantiate or write to a physical transport.
13. Closing or disconnecting the simulator leaves the application in the same safe disconnected state as losing a physical connection.
14. Documentation clearly states that simulation validates application behavior but does not prove physical machining safety.

## Out of scope

This implementation does not include:

- Physical hardware-in-the-loop equipment
- Real motor or spindle control
- Cutting-force simulation
- Tool/material collision physics
- Tool deflection or spindle-load modeling
- Automatic validation of workholding
- Certification that a generated job is physically safe
- General-purpose 3D material-removal simulation

Those capabilities may be considered separately after the virtual controller and animation system are stable.

## Recommended implementation order

1. Add the simulation option to the connection model and prompt.
2. Implement the deterministic virtual clock.
3. Implement the virtual machine plant.
4. Implement the virtual GRBL protocol engine.
5. Implement `SimulationTransport`.
6. Integrate it through `ConnectionService`.
7. Add complete headless workflow tests.
8. Add the separate simulator window.
9. Connect animation to authoritative simulator snapshots.
10. Add accelerated time.
11. Add predefined scenarios.
12. Add fault injection.
13. Add Qt integration tests.
14. Add trace export and documentation.
15. Run the complete regression suite and perform a safety review.
