# STEP and 2.5D Machining Progress

This file tracks the bounded STEP-to-G-code expansion for the TTC 3018 app.
The first release targets simple planar STEP designs and 2.5D machining only.
It must continue to use the existing validated G-code, preview, envelope, and
streaming pipeline.

## Scope

- [x] Import simple planar STEP files.
- [x] Display an imported model's extracted top view.
- [x] Let the user select model orientation, stock size, work-zero location,
  and fixed tool diameter.
- [x] Generate validated outside and inside contours.
- [x] Generate planar pockets, engravings, and holes.
- [x] Support multiple depth passes.
- [x] Support safe Z, cutting/plunge feeds, and optional spindle start.
- [x] Generate combined through-profile cutouts with inner-first ordering,
  breakthrough allowance, and outer holding tabs.
- [x] Distinguish axial circular recesses from raised bosses using STEP face
  topology and generate the corresponding inside-versus-surrounding clearing
  strategy at the detected feature depth.
- [x] Preserve accessible planar surface patches, including tilted planar ramp
  faces, as normalized height-field metadata across the isolated import worker.
- [x] Generate bounded varying-Z raster paths for accessible planar surfaces,
  split at abrupt vertical cliffs, and validate them through the shared metric
  G-code parser.
- [x] Use connected alternating scanlines for broad pocket regions and retain
  safe retracts around holes, islands, and disconnected material.
- [x] Connect concentric offset rings into stay-down paths when their links are
  contained by the compensated removal region, retaining retracts where they
  are not safe.
- [x] Schedule independent paths by nearest endpoint with deterministic open-
  path reversal and closed-loop start rotation while preserving inner-before-
  outer profile ordering.
- [x] Apply bounded deterministic 2-opt improvement to small path sets without
  increasing rapid-link cost, and reorient the final sequence from each actual
  predecessor endpoint.
- [x] Compare connected scanline and bounded offset pocket candidates using a
  weighted cut/rapid/retract cost and select the lower-cost valid strategy.
- [x] Preserve individual detected-feature depth targets and avoid applying the
  deepest recess depth to shallower recesses.
- [x] Classify detected axial recesses that reach the model bottom as through,
  carry that status through isolated import, and derive their target from
  confirmed stock thickness plus breakthrough while retaining blind depths.
- [x] Execute detected feature groups deepest-first while keeping nearest-path
  optimization scoped within each depth group.
- [x] Expose exact cut distance, rapid XY distance, and retract count for each
  generated STEP job.
- [x] Add a deterministic geometry-only verification gate for clearing-path
  containment and tool-reachable planar coverage before generated G-code loads.
- [x] Attach the current STEP operation groups and dependencies to generated
  results, review summaries, and G-code metadata.
- [x] Validate generated operation IDs, target depths, dependency references,
  and acyclic ordering before G-code emission.
- [x] Derive detected-feature parent/child dependencies from loop containment,
  topologically order nested groups inner-first, and reject later dependencies
  in the emitted operation sequence.
- [x] Anchor lower-left outside/profile compensated envelopes at nonnegative
  work X/Y zero and show the raw part boundary separately in the Qt preview.
- [x] Run flat pocket paths through a deterministic swept-cutter stock
  simulation, including reachable coverage, tool-unreachable corners, stock
  bounds, retained-material gouge checks, and physical-depth checks.
- [x] Apply the same simulation gate independently to each detected recess or
  boss-removal region, preserving each feature's own target depth.
- [x] Run accessible planar-surface paths through a height-field simulation
  that checks coverage, sampled Z error, slope/cliff transitions, stock bounds,
  and physical depth.
- [x] Validate compensated profile cutouts with a boundary-band and retained
  interior simulation, including the intentional cutter overhang at stock
  edges and physical through-depth limits.
- [x] Parse the exact G-code emitted by the STEP generator before returning it
  to the shared loading pipeline.
- [x] Build and serialize deterministic projected-loop containment metadata,
  attach parent indices to detected features, and reject partial overlaps or
  self-intersecting loops before machining.
- [x] Preview the generated centerline toolpath before running.
- [x] Show the current validated operation plan with target depths and
  dependencies, and disable generation when the preview is stale or rejected.
- [x] Reject geometry or generated motion outside the trusted virtual envelope.

## Completed foundation

- [x] Qt Quick desktop UI is the default application interface.
- [x] Shared metric G-code parser and safety validation pipeline.
- [x] Shared XY toolpath preview pipeline.
- [x] Virtual machine envelope and work-zero safety checks.
- [x] Acknowledged, one-command-at-a-time GRBL job streaming.
- [x] Text engraving and plaque-builder generators use the shared pipeline.
- [x] Manual reference and persistent work-zero workflow.

## Implementation milestones

### 1. Dependency and import boundary

- [x] Select and document the OpenCASCADE/OCP dependency and supported Python
  versions (`cadquery-ocp` 7.9.3.1.1; Python 3.14 wheel verified).
- [x] Add a small STEP import adapter; do not implement a STEP parser or
  geometric kernel in this repository.
- [x] Add clear import errors when OCP is unavailable or a STEP file is invalid.
- [x] Add representative planar STEP fixtures that are safe to store in the
  repository.
- [x] Add paired removed-cylinder and extruded-circle STEP fixtures for
  topology-classification regressions.

### 2. Model inspection and setup

- [x] Add an **Import STEP…** action in the Prepare workspace.
- [x] Show model metadata, bounding box, and top-view preview.
- [x] Add orientation selection for the supported planar cases.
- [x] Add stock width, stock height, stock thickness, tool diameter, and work
  zero location controls. Profile cutout uses the operator-confirmed stock
  thickness instead of assuming the imported solid matches the physical stock.
- [x] Reject non-planar or ambiguous geometry with an actionable explanation.

### 3. Planar geometry extraction

- [x] Extract closed top-view loops from the selected top face.
- [x] Classify outer boundaries and holes for the supported planar cases.
- [x] Preserve loop winding and reject open or unusable geometry.
- [x] Add a geometry normalization layer independent of OCP objects.
- [x] Add deterministic geometry unit tests using an OCC-generated planar box.

### 4. 2.5D toolpath generation

- [x] Add a machining-mode selector: engraving, combined profile cutout,
  outside contour, inside contour, pocket, and hole.
- [x] Implement tool-radius offsets for inside and outside contours.
- [x] Define behavior for internal corners, tight radii, islands, and offset
  failures by using bounded Shapely offsets and rejecting empty/out-of-stock
  results. CAM-grade lead-ins remain deferred.
- [x] Implement pocket clearing paths for simple planar regions.
- [x] Implement hole paths with a documented minimum diameter rule.
- [x] Implement multiple Z depth passes ending at the requested machining depth.
- [x] Classify profile-cutout loops automatically, cut inner loops before outer
  loops, derive through depth from stock thickness plus breakthrough, and leave
  configurable outer tabs.
- [x] Add planar-surface mode for accessible flat/ramp patches with multiple
  passes and cliff-safe path splitting.
- [x] Add regression coverage for Wedge varying-Z output, parser bounds, and
  nonnegative work coordinates.
- [x] Keep all generated moves within the supported metric command subset.

### 5. UI and shared job pipeline

- [x] Add a STEP/2.5D job dialog with live settings and toolpath preview.
- [x] Reuse the existing generated-program loading and parser validation path.
- [x] Reuse existing bounds checks, preflight, spindle controls, and job
  streaming.
- [x] Show stock, tool diameter, work zero, cut depth, pass count, and final
  transformed bounds in the preview/review screen.
- [x] Add save-to-G-code support through the existing validated output path.

### 6. Safety and verification gates

- [x] Reject invalid stock dimensions, zero/negative tool diameters, impossible
  offsets, invalid depths, and unsafe safe-Z values.
- [x] Reject geometry extending beyond stock; the existing start preflight
  rejects motion outside the configured machine envelope.
- [x] Verify no rapid or cutting move crosses the trusted envelope before a
  job can start.
- [x] Verify every depth pass and final depth against the selected stock/work
  zero configuration.
- [x] Test optional spindle commands and parser acceptance.
- [x] Test preview geometry against generated G-code bounds.
- [x] Verify the compensated lower-left cutout envelope reaches work X0/Y0 and
  actual emitted profile commands use the same placement translation.
- [x] Test varying-Z Wedge paths for parser bounds and cliff-safe segment
  splitting.
- [x] Preserve all existing text, plaque, parser, motion-safety, and streaming
  tests.

## Deferred deliberately

- [ ] General-purpose 3D STEP surface machining.
- [ ] Reliable arbitrary-angle face orientation and complex B-rep topology.
- [ ] 3D adaptive clearing, waterline, raster, or rest machining.
- [ ] Full-resolution stock collision simulation for every operation and ramp.
- [ ] Full CAM-grade cutter compensation and lead-in/lead-out strategies.
- [ ] Boundary tracing and probing.

## Working rules

- Commit each coherent milestone before starting the next one.
- Keep STEP/OCP objects behind an adapter; the generator should consume plain
  normalized geometry.
- Do not send machine commands during import, preview, setup, or generation.
- Generated programs must pass the existing parser and trusted-envelope checks
  before they can be loaded for a run.
- If an app instance is running, follow the repository agent instruction and do
  not terminate, restart, activate, focus, resize, or interact with it.

## Change log

| Date | Commit | Update |
| --- | --- | --- |
| 2026-08-29 | `6090a37` | Baseline Qt controller, preview, safety, and agent-running-instance guard. |
| 2026-08-29 | `9fad6ee` | Added the OCP/Shapely dependency boundary and normalized planar STEP importer. |
| 2026-08-29 | `9707c0c` | Added validated engraving, contour, pocket, and hole paths with tool offsets and depth passes. |
| 2026-08-29 | `1e9a983` | Integrated the STEP/2.5D dialog, live preview, generated-program loading, and Qt view-model coverage. |
| 2026-08-29 | `bb211a8` | Added explicit STEP review bounds/settings and malformed-loop validation. |
| 2026-08-30 | `68ea9a8` | Added Auto/XY/XZ/YZ planar-face selection and verified the real Test Bracket STEP file. |
| 2026-08-30 | `2f642b6` | Added compensated inner-first profile cutouts, through depth, breakthrough, and outer tabs. |
| 2026-08-30 | `2922670` | Added Qt profile-cutout controls and live preview/review details. |
| 2026-08-30 | `479edb7` | Added paired STEP feature fixtures plus automatic recess/boss detection and slicing. |
| 2026-08-30 | `517a611` | Added normalized planar surface patches, Wedge ramp slicing, connected pocket scanlines, and nonnegative cutout placement. |
| 2026-08-30 | `4038506` | Added deterministic flat-stock swept-cutter coverage, depth, stock, and retained-material checks. |
| 2026-08-30 | `ab42ae1` | Applied independent simulation gates to detected recess and boss-removal regions. |
| 2026-08-30 | `46efaec` | Added height-field coverage, Z-error, slope, and depth simulation for planar surfaces. |
| 2026-08-30 | `77340c0` | Added compensated profile-cut simulation with intentional stock-edge cutter overhang. |
| 2026-08-30 | `cb9e5f9` | Exposed the validated STEP operation plan and blocked stale/rejected previews in Qt. |
| 2026-08-30 | `dc0bd44` | Connected safe concentric pocket rings into stay-down paths. |
| 2026-08-30 | `7ba66c8` | Fixed final path orientation after bounded 2-opt optimization. |
