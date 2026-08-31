# Architecture Decision Record: Modular Monolith

Status: Accepted and implemented

## Decision

TTC 3018 Control remains a single-process Qt Quick desktop application. The
Qt presentation layer talks to a Qt-independent Python `ApplicationController`,
which coordinates machine-session safety, connection, motion, job, and
generation services. USB, TCP, filesystem, Wi-Fi discovery, and isolated STEP
import remain infrastructure adapters.

```text
Qt Quick/QML
    -> ControllerViewModel
        -> ApplicationController
            -> application services and domain rules
                -> USB/TCP/filesystem/native-worker adapters
```

The controller is the only application-facing owner of the active transport
and command ordering. QML receives display properties and invokes intention-
level slots; it does not construct GRBL commands or perform envelope checks.

## Why this fits the product

- The app controls one locally attached 3018, so an HTTP server or daemon adds
  deployment and security surface without solving a current requirement.
- Motion safety, work-zero/reference trust, G-code validation, and job streaming
  stay testable without a GUI event loop.
- A future CLI or local API can call the same controller without moving safety
  rules into a network layer.
- The native STEP/OpenCASCADE import remains isolated because that boundary is
  about crash containment, not frontend/backend separation.

## Alternatives considered

### Separate HTTP/API backend

This would help only when headless operation, a second independently maintained
frontend, remote control, or external automation is required. It would require
single-client leases, authentication, event streaming, orphaned-job behavior,
emergency-stop semantics, and version compatibility. None is needed for the
current local desktop workflow.

### Fully separate local backend process

This could improve GUI crash isolation, but adds process supervision and IPC
failure modes. The existing STEP importer already isolates the highest-risk
native dependency. Revisit this option if GUI/backend crash isolation becomes a
demonstrated requirement.

### Direct Qt-to-domain wiring

This was the starting shape. It made the ViewModel responsible for transport,
motion state machines, job sequencing, persistence, and UI presentation at
once. It is retained only for display projection and Qt-specific dialogs/files.

## Revisit triggers

Reconsider a separate process or API only for one of these concrete needs:

- headless machine operation without the desktop UI;
- a second frontend maintained independently;
- remote monitoring or control;
- external automation integrations; or
- measured need for stronger GUI/backend crash isolation.

If one trigger appears, define control leases, authentication, heartbeats,
emergency-stop behavior, orphaned-job policy, and local IPC/network exposure
before selecting a protocol.

## Machine platform extension

Machine configuration is now a versioned local catalog rather than one flat
profile. The catalog keeps geometry, optional hardware declarations, controller
kind, and stable machine identity together. Work-zero, commissioning, fixture,
and tool records are machine-scoped so selecting another machine cannot reuse
coordinates or evidence accidentally.

Controller-specific behavior is behind capability adapters. The GRBL 1.1
adapter owns homing, probing, work-offset, and tool-length command semantics;
a generic adapter can expose only the basic motion contract. Declared hardware
alone never unlocks a production action: the capability must also be supported
by the adapter and have current commissioning evidence.

Homing and probing are explicit application services with exclusive response
ownership and fresh-status/report confirmation. They are separate from ordinary
job parsing and streaming. A reset, disconnect, or safety-relevant configuration
change clears session motion trust; persisted fixture geometry is reusable only
after a new homing and probe confirmation.
