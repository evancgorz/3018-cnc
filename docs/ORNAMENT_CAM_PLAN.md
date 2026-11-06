# Hawkeye ornament: smallest useful CAM path

Date: 2026-11-01. Planning owner: `codex-ornament-planning`.

## Product and current authorization

Make a 100 mm circular ornament from nominal 3 mm hobby plywood. Black artwork
means shallow recessed engraving; white means retained face. Only the hanging
hole and outside perimeter go through. Preserve the E-2 patch artwork and its
lettering. The photographic mockup is a visual target, not a measured model or
material-removal simulation.

The user owns a 60-degree engraving bit and reports a SHARPRO
SPMS200-2ES-1/8. The engraving tip flat, actual endmill cutting diameter and
flute length, measured stock thickness/flatness, fixture layout, verified feeds,
RPM, breakthrough and pass depths remain unconfirmed. Do not substitute a saved
CAM value or generic example tool for these measurements.

This run authorizes planning and an offline exporter with isolated checks. It
does not authorize machine connection, motion, spindle use, commissioning,
backend restart, or interaction with a user-owned application. C-015 remains
owned by its existing execution agent.

## Reuse before expansion

- `gcode.py`: parser plus nonnegative-work-XY and rapid-clearance validators.
- `step_engraver.py`: compensated pockets, inner-before-outer profile cutout,
  stock thickness/breakthrough, holding tabs, pass-depth limits and profile
  verification. Reuse this for the disc/hole; do not build another profiler.
- `step_geometry.py`: normalized planar loops and containment relationships.
- `step_operations.py`: existing operation dependencies; extend rather than
  replace when tool identity is introduced.
- Existing application/backend owns review, authorization and execution. An
  offline generator prepares files only; it must never connect to hardware.

The app currently has no artwork machining importer. The text designer uses
centerline fonts and cannot reproduce these curved filled letters faithfully.
Current STEP operations use one cutter per generation. G-code rejects M6; the
streamer's support for ordinary M0/M1 commands is not a safe tool-change state
machine. Separate files are the first multi-bit workflow.

## Ordered delivery backlog

| ID | Outcome and scope | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| C-016 | Audit existing capabilities and record this bounded plan | — | Code-backed reuse/gap audit; concrete task order and physical unknowns |
| C-017 | Offline black-artwork to shallow engraving G-code, without a GUI rewrite | — | Explicit crop/physical placement, V-bit footprint compensation, retained white counters, parser/rapid checks, swept preview, report and isolated tests |
| C-018 | A reproducible ornament project describes geometry, stock, tools and operation order | C-017 | Versioned project; source/art hashes; separate artwork and part sizes; units/origin; measured vs provisional values; unknown dimensions block production export; output hashes tie review to exact files |
| C-019 | Finish and verify the physical-size artwork and hanger reserve | C-018 | Reviewable vector geometry at 100 mm; remove tracing artifacts; counters remain open; minimum feature/spacing report; hanger/edge ligament and no-engrave keepout checked against cutter sweep; distinguish engrave/pocket/through-cut layers; resolve unreachable fine detail through shallower/variable-depth or centerline paths rather than silent omission |
| C-020 | Export aligned engraving and tabbed disc/hole programs as one reviewed bundle | C-018, C-019 | Reuse STEP profile engine; exactly one hole plus one outside through contour; hole first; tabs only outside; common explicit stock XY transform across tools; compensate cutter radius without shifting artwork; depths and tool identity in per-file report; clamp/stock/spoilboard clearance checks; reduce raster retracts only through verified in-region stay-down links and compare runtime/coverage against baseline |
| C-021 | Guide manual tool changes through persistent backend state | C-020 | Confirm prior operation complete with fresh Idle, safe clearance and spindle off before tool-change prompt; retain XY reference; re-establish tool-specific Z; invalidate old run authorization; separate review/start for next tool; reconnect reconstructs state; abort/reset/reference loss fails closed; fake/twin tests before hardware |
| C-022 | Expose ornament preparation and material-removal review in Prepare/Review | C-020 | Select artwork/project, crop/scale preview, operation/tool table, depth-limited engraving controls, actual swept-width preview plus stock/hole/tabs preview, visible unresolved measurements and detail loss; no generated-image appearance presented as machining verification |
| C-023 | Validate a scrap coupon and then the ornament with operator-authorized hardware work | C-020 | First complete isolated export/parser/profile tests; separately authorize physical test; check plywood thickness/flatness, engraving width/depth, veneer tear-out, hold-down and tab retention; revise settings from measurements; only then release ornament files |
| C-024 | Correct inefficient air moves and measure runtime before further CAM work | C-017 | Retain compensated cutting primitives; bounded path scheduling; cost-aware, footprint-checked stay-down links; optional explicit vertical approach above stock; same-settings and changed-setting estimates distinguished; parser and retained-white tests |

C-018 through C-023 are planned work, not part of this execution run. C-021 and
C-022 can be deferred: an operator can use separately reviewed files and manually
change/re-zero tools without adding a new backend protocol. C-023 needs separate
current-request hardware authorization. Physical readiness remains governed by
the existing commissioned-machine and safety gates.

## Engraving strategy and its limits

The first exporter uses fixed-depth raster-region clearing, not adaptive
variable-depth V-carving. At positive engraving depth `d`, the tool's top-surface
diameter is `tip_diameter + 2*d*tan(included_angle/2)`. Erode the intended black
region by its radius before generating tool-center paths. Retract before every
disconnected XY transfer; never bridge a white letter counter at cutting depth.
Keep depth below actual stock thickness and bound the pass depth.

This strategy fits solid black letters/shapes at one shallow depth. It can omit
lines narrower than the cutter footprint and leaves V-shaped slopes around
larger recesses. A swept-width preview and measured lost-area report are required;
silently rounding every narrow feature up would destroy the retained geometry.
Adaptive V-carving/centerline recovery is a later option only if the 100 mm
preview demonstrates a need. High raster pixel count alone does not prove
machinability.

The first real-artwork example with explicitly assumed 0.10 mm tip, 0.25 mm
depth, 0.15 mm stepover and two passes produces 6,259 paths per pass and a
rough 626-minute estimate. Morphological inaccessibility is about 9.34% of
black area. This demonstrates the need for C-019 fine-detail refinement and
C-020 path optimization; it is not a suitable released production strategy.
The runtime estimate assumes nominal feed and 3,000 mm/min rapids and excludes
real acceleration/controller overhead. Raster V-bit floors are scalloped,
unlike the idealized flat recesses in the photographic mockup.

### Runtime correction after user review (C-024)

The user rejected the ten-hour result. Baseline analysis found 498.76 of
625.63 minutes came from 12,518 feed plunges through the 3 mm air clearance.
This was a generator defect/strategy problem, not an accepted ornament runtime.

Implemented bounded endpoint scheduling and verified, cost-aware stay-down
links. An optional `approach_z` allows a vertical rapid down to an explicitly
chosen positive clearance, only after XY positioning at full `safe_z`.
`approach_z: null` preserves the prior full-clearance approach. Reduced approach
requires verified stock flatness and no obstruction at the cut starts; it is
not selected implicitly for the operator.

| Scenario on identical source art | Nominal engraving minutes | Changed assumptions |
| --- | ---: | --- |
| Original baseline | 625.63 | None |
| Scheduling/stay-down only | 238.67 | No depth, feed or clearance changes |
| Scheduling plus 0.2 mm vertical approach | 146.94 | Reduced approach explicitly assumed; XY rapid remains at 3 mm |
| Single-pass timing projection with that approach | 75.74 | Also assumes a 0.25 mm depth pass instead of two 0.125 mm passes; untested |

These are engraving-only nominal estimates, not promised cycle times. No
physical settings were verified or run. The same 9.34% inaccessibility remains;
none of these files is production released. C-019/C-020 must prioritize actual
vector/variable-depth engraving, appropriate filled-area clearing and contour
simplification over further polishing the fine-raster baseline. Preserve the
approved engraved appearance when evaluating strategies; do not silently switch
to outline-only lettering or reduce artwork coverage to obtain a faster number.
The reproducible comparison is `artifacts/ornaments/hawkeye/compare_runtime.py`.

The current illustration needs deliberate cleanup before production: some wing
lines extend beyond the inner ring, the tail/propeller fine gaps need a minimum
width check, and the hanging hole must receive a reserved wood margin. Do not
auto-detect a photographic circle and call it an exact 100 mm cut boundary.
Define the outside circle analytically, independent of the image pixels.

## Review checkpoint and release facts

Current deliverable: offline engraving generation capability, documented settings
and verification. Production cut files are not released while measured tooling,
stock, hanger placement and fixturing are unresolved. This is an input boundary,
not a reason to omit the exporter or its isolated tests.

Before release, check final emitted coordinates and tool sweep, not merely the
pre-rounding path. Verify depths, positive stock XY, safe-Z transfers, supported
commands, line length, source/settings hashes, expected operation ordering and
common XY across tools. A file that parses is not proof of physical feasibility.
