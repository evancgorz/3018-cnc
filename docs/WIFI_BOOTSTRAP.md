# USB bootstrap, Wi-Fi operation

The production backend treats USB as a setup/recovery transport, never a
cutting transport. Startup tries saved Wi-Fi first. If USB is the available
initial connection, the backend waits for fresh Idle and spindle-off status,
requests the controller's current station IP using read-only `[ESP111]`, and
tries that address followed by the saved address. It does not scan a subnet.

The existing controller Wi-Fi credentials must already be configured. No
password is extracted, logged, guessed or sent by this bootstrap. If the
controller is not on Wi-Fi, status reports setup required/unavailable. USB
does not become an operating fallback. This path never reboots the controller
or automatically starts homing, spindle, probing or a job.

USB remains connected during verification. A candidate TCP connection must
report valid, recent GRBL Idle status, zero feed/spindle, and a finite machine
position matching fresh USB status within 0.05 mm. The same verified socket
becomes the operating connection before USB closes. Position matching is a
consistency check, not cryptographic device authentication.

Handoff invalidates machine reference, work zero, pending run authorization,
and old status trust. The operator must home and establish work zero over
Wi-Fi before cutting. A socket opening alone does not enable operation: fresh
GRBL status from the new session is required.

USB permits only exact read-only queries (`[ESP111]`, `$$`, `$I`, `$G`, `$#`,
`$N`), spindle stop `M5`, and realtime status/hold/reset/jog-cancel. Motion,
work-offset changes, spindle start, job commands and resume are rejected at
both the controller and transport boundaries. Simulation remains available.
Normal production `BackendRuntime` activates this policy; explicitly injected
test/compatibility compositions retain their isolated legacy semantics.

The backend snapshot's `connection` section exposes `setup_only`,
`operation_transport_ready` and `wifi_bootstrap` (state, message and attempted
endpoints). A failed handoff keeps USB available for read-only diagnosis.
Disconnect cancels pending candidates and closes late results. Neither a lost
Wi-Fi connection nor a reconnect automatically resumes cutting.

Changes are tested using temporary roots and fake transports. No running
application or backend is restarted by source edits. Activating a new revision
requires an operator-authorized backend restart; it invalidates connection
and reference trust and does not automatically authorize physical motion.
