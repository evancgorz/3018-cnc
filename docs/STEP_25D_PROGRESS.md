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
- [x] Preview the generated centerline toolpath before running.
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
- [ ] Add representative planar STEP fixtures that are safe to store in the
  repository.

### 2. Model inspection and setup

- [x] Add an **Import STEP…** action in the Prepare workspace.
- [x] Show model metadata, bounding box, and top-view preview.
- [x] Add orientation selection for the supported planar cases.
- [x] Add stock width, stock height, tool diameter, and work zero location
  controls. Stock thickness remains implicit in the imported solid for this
  bounded 2.5D release.
- [x] Reject non-planar or ambiguous geometry with an actionable explanation.

### 3. Planar geometry extraction

- [x] Extract closed top-view loops from the selected top face.
- [x] Classify outer boundaries and holes for the supported planar cases.
- [x] Preserve loop winding and reject open or unusable geometry.
- [x] Add a geometry normalization layer independent of OCP objects.
- [x] Add deterministic geometry unit tests using an OCC-generated planar box.

### 4. 2.5D toolpath generation

- [x] Add a machining-mode selector: engraving, outside contour, inside contour,
  pocket, and hole.
- [x] Implement tool-radius offsets for inside and outside contours.
- [x] Define behavior for internal corners, tight radii, islands, and offset
  failures by using bounded Shapely offsets and rejecting empty/out-of-stock
  results. CAM-grade lead-ins remain deferred.
- [x] Implement pocket clearing paths for simple planar regions.
- [x] Implement hole paths with a documented minimum diameter rule.
- [x] Implement multiple Z depth passes ending at the requested machining depth.
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
- [x] Preserve all existing text, plaque, parser, motion-safety, and streaming
  tests.

## Deferred deliberately

- [ ] General-purpose 3D STEP surface machining.
- [ ] Reliable arbitrary-face orientation and complex B-rep topology.
- [ ] 3D adaptive clearing, waterline, raster, or rest machining.
- [ ] Automatic stock collision simulation.
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
| 2026-08-29 | pending | Integrated the STEP/2.5D dialog, live preview, generated-program loading, and Qt view-model coverage. |
