# Production 2.5D STEP-to-G-code Implementation Plan

## Purpose

Build a reliable CAM pipeline for STEP parts near the practical limit of 2.5D
machining on a 3018 CNC. The system must support complex combinations of
planar levels, pockets, islands, holes, bosses, slots, through-cutouts, outer
profiles, and machinable planar ramps without pretending to support arbitrary
3D surfaces or undercuts.

The implementation must also replace the current collection of mostly
independent concentric loops with connected clearing strategies and a
dependency-aware path scheduler. The goals are correct material removal,
predictable stock-thickness behavior, fewer retracts and rapids, shorter jobs,
and deterministic output that can be comprehensively tested.

This plan extends, but does not invalidate, the completed foundation tracked in
`docs/STEP_25D_PROGRESS.md`.

## Non-negotiable machining contract

### Coordinate and stock semantics

- Work `Z0` is the physical top of stock.
- The operator-confirmed stock width, height, and thickness are authoritative.
- Stock width and height must contain the transformed model footprint plus any
  cutter-compensated outside path. Importing a model never proves that the
  physical blank is large enough.
- Model height/depth differences describe feature depths and retained material.
- A feature classified as **through** is cut to
  `-(stock_thickness + breakthrough)`, not merely to the STEP model's Z extent.
- Therefore, a through-feature in a 2 mm-thick part placed in confirmed 2 mm
  stock is cut completely through the stock, with the configured breakthrough.
- A blind feature is cut only to its STEP-derived floor depth and must not be
  converted to a through-feature merely because its floor is close to the
  model bottom.
- The outer profile is a through operation when the user requests extraction
  of the modeled part from the stock. Holding tabs or an explicit alternative
  workholding strategy are required before that operation can run.
- Changing stock thickness must recompute every through depth, pass schedule,
  tab floor, bounds result, preview, duration estimate, and operation warning.

### Supported 2.5D definition

A part is supported when all material to remove can be represented from one
selected machining direction as:

- vertically accessible XY regions with a single target floor per XY point;
- nested planar floors, vertical walls, holes, islands, slots, and bosses;
- planar ramps that form a single-valued height field from the selected view;
- operations executable with a fixed, vertical cylindrical/end-mill tool.

Reject or require another setup for:

- undercuts, re-entrant geometry, hidden cavities, or more than one model
  surface height at the same XY location;
- side holes and features inaccessible along the tool axis;
- arbitrary curved/freeform surface finishing;
- geometry requiring a tool smaller than the selected tool to reach it;
- zero-thickness/non-manifold/open shells, ambiguous solids, or self-
  intersecting projected regions;
- ramps steeper than the configured machine/tool capability or any path whose
  cutter body/shank would collide with retained material.

The importer must return an actionable diagnostic that identifies the rejected
feature and its location. It must never approximate unsupported geometry and
quietly generate plausible-looking G-code.

## Target workflow

1. Import STEP in the existing isolated OCP worker.
2. Select or confirm machining direction and model orientation.
3. Enter physical stock width, height, and thickness; select work-zero origin.
4. Select a tool from an explicit tool definition.
5. Analyze machinability and show supported operations, warnings, and rejected
   geometry before generating paths.
6. Review the automatically inferred operation plan and override only safe,
   explicit choices such as blind/through intent, tabs, feeds, and stepdowns.
7. Generate roughing, rest clearing where applicable, finishing, hole, and
   final profile operations in dependency-safe order.
8. Preview the exact generated centerline path by operation and depth, with
   rapids and retracts visible.
9. Run simulation, parser validation, stock/envelope validation, and a final
   preflight before loading the job.

## Architecture

Keep native OCP objects behind the isolated STEP adapter. Add four Qt-
independent layers between import and G-code emission:

```text
STEP B-rep
  -> Geometry analyzer
  -> Normalized 2.5D machining model
  -> Operation planner and dependency graph
  -> Toolpath strategies and global scheduler
  -> Motion verifier and stock simulation
  -> Existing metric G-code parser/validator/preview/streamer
```

No UI type, OCP object, or GRBL connection object may enter the normalized CAM
layers. Every intermediate representation must be serializable and deterministic
so it can be fixture-tested without opening Qt or connecting a machine.

## Normalized machining model

Introduce immutable domain records, with stable IDs and source-face references:

- `StockDefinition`: width, height, thickness, origin, safe Z, breakthrough.
- `ToolDefinition`: diameter, cutting length, flute count, maximum stepdown,
  maximum stepover, plunge/ramp capability, feeds, spindle RPM.
- `MachiningRegion`: compensated/uncompensated polygon, top Z, target floor Z,
  parent region, islands, accessibility, and confidence.
- `Feature`: pocket, open pocket, slot, hole, bore, boss-surround, planar ramp,
  through-cutout, or outer profile.
- `PlanarSurfacePatch`: projected boundary and `Z = aX + bY + c` coefficients.
- `Operation`: tool, strategy, depth schedule, geometry IDs, allowance, tabs,
  entry method, and predecessor IDs.
- `Toolpath`: ordered 3D segments with motion type, operation ID, feed, spindle
  state, and source geometry ID.
- `Diagnostic`: severity, code, geometry/location, and remediation.

Do not reduce the model to a single “top face” and a flat list of loops. Build a
containment tree and Z-level arrangement capable of representing multiple
features at different depths and several disconnected components.

## Geometry analysis and feature inference

### B-rep validation

- Read all solids, shells, faces, wires, and edge tolerances in the isolated
  worker.
- Heal only within a documented tolerance; report every repair.
- Validate closed solids and consistent orientation.
- Reject mixed units or convert once to millimeters at the adapter boundary.
- Detect duplicate/coincident faces and sliver regions below tolerance.

### Z-level decomposition

- Collect unique planar face levels normal to the selected tool axis and merge
  levels only within an explicit tolerance.
- Project face regions into XY and build a planar arrangement at every level.
- Use vertical-wall adjacency and face orientation to connect each boundary to
  its upper and lower region.
- Build a containment tree for outer regions, holes, islands, nested islands,
  and disconnected bodies.
- Classify a void as blind or through using full solid topology: a blind void
  has a material floor; a through void remains open to the model bottom.
- Classify retained volumes as bosses/islands and derive the surrounding
  removal region rather than machining the boss itself.
- Detect the outer part silhouette separately from internal through-cutouts.
- Preserve analytic circles/arcs where available instead of polygonizing them
  prematurely.

### Planar ramps

- Extract every planar face with a usable tool-axis normal component as a
  bounded height-field patch.
- Resolve the topmost accessible height at each XY position.
- Detect discontinuities/vertical cliffs and split paths instead of making a
  diagonal cutting move between unrelated heights.
- Use raster or waterline roughing followed by parallel-plane finishing.
- Reject overlapping patches that create a multi-valued surface or inaccessible
  underside.

### Confidence and user review

Every inferred feature receives `high`, `review`, or `rejected` confidence.
Through/blind classification must be shown in the UI, including its resulting
absolute work-Z target. User overrides are explicit and logged in G-code
comments; changing a feature to through immediately applies stock-thickness
semantics and safety validation.

## Operation planning

Generate an operation dependency DAG rather than emitting paths while geometry
is discovered. Default precedence is:

1. Facing, only when explicitly requested.
2. Deep/open roughing before narrow rest regions where this improves access.
3. Blind pockets and boss-surround clearing, deepest nested regions first when
   required to preserve access.
4. Rest machining and pocket finishing.
5. Holes/bores and internal through-cutouts.
6. Wall/floor finishing and planar-ramp finishing.
7. Outer profile last, with tabs or another confirmed retention method.

Additional constraints:

- Never remove an island or outer support before dependent interior work.
- Keep each operation's depth passes together unless a proven depth-first
  grouping reduces travel without violating chip evacuation or rigidity.
- Finish passes follow roughing and use configurable radial/axial allowance.
- Through-cutouts use stock thickness; blind floors use STEP depths.
- The planner reports unreachable regions, minimum required tool diameter, and
  any residual material that the selected tool cannot remove.

## Toolpath strategies

### Pocket roughing

Replace independent concentric-boundary output as the primary strategy with:

- connected bidirectional zigzag clearing for broad/simple regions;
- connected offset clearing for shapes where offsets are materially shorter;
- adaptive/trochoidal-style clearing only after a bounded engagement model is
  implemented and tested;
- automatic strategy selection using estimated cut length, linking length,
  retract count, corner load, and disconnected-region count.

Clip zigzag lanes to the compensated pocket region, account for islands, and
link adjacent lanes inside already-cleared material. Use short stay-down links
only when a swept-tool check proves the link is inside cleared stock at the
current depth. Otherwise retract to safe Z.

### Contours and through profiles

- Preserve arcs and emit `G2/G3` only after the shared parser and simulator
  fully validate them; otherwise use tolerance-bounded linearization.
- Select a start point that minimizes travel and avoids tabs/tight corners.
- Add configurable lead-in/lead-out where stock allows it.
- Cut internal through-loops before the containing outer profile.
- Distribute tabs away from corners, holes, thin walls, and lead-ins.
- Add an optional low-force final tab/skin operation, but never detach the part
  without explicit user intent.

### Holes and slots

- Distinguish drill-sized holes, helical bores, circular pockets, and slots.
- Use helix/ramp entry when the selected tool permits; otherwise require a safe
  plunge point or pre-drill operation.
- Through holes terminate at `-(stock_thickness + breakthrough)`.
- Blind holes terminate at the STEP floor and respect drill-tip/end-mill
  semantics defined by the selected tool.

### Planar ramps

- Rough in bounded depth layers, leaving finishing allowance.
- Finish with alternating raster passes oriented to minimize slope error and
  retracts; sample at a chordal/scallop tolerance.
- Split and retract at vertical discontinuities.
- Prohibit a single XYZ segment whose inferred slope crosses a detected cliff.

## Global path optimization

Optimize only after operation dependencies and local strategy safety are known.
Correctness always outranks shortest travel.

### Within an operation

- Treat each open path in both directions and each closed path at multiple
  candidate start points.
- Build a candidate endpoint graph.
- Seed with deterministic nearest-neighbor ordering, then improve with bounded
  2-opt/or-opt swaps.
- Penalize retracts and unsafe links more heavily than XY distance.
- Prefer staying down within a connected, already-cleared component.
- Alternate zigzag lane direction and connect adjacent lanes directly.
- For concentric paths that remain useful, connect adjacent rings with a safe
  spiral/radial link where possible instead of retracting between every ring.

### Across operations

- Topologically sort the operation DAG.
- Among currently eligible operations, choose the next operation using a cost
  function for current endpoint distance, retract/tool-change cost, depth,
  retention risk, and estimated duration.
- Re-optimize from the actual endpoint of the preceding operation.
- Keep output deterministic with stable tie-breaking by operation and geometry
  ID.

### Metrics and regression limits

Record before/after metrics in `StepMachining` and G-code comments:

- cutting distance;
- stay-down linking distance;
- rapid XY distance;
- retract/plunge count;
- estimated duration;
- operation count and unsupported/rest-material area.

For representative pocket fixtures, the new planner must reduce retract/plunge
count by at least 60% and rapid XY distance by at least 40% versus the current
concentric implementation, without increasing uncut area or gouging retained
material. Store the legacy baseline metrics as test data rather than invoking
legacy code in production.

## Motion verification and material-removal simulation

Add a lightweight 2.5D stock simulator independent of the visual preview:

- Represent stock as exact planar arrangements for vertical operations and a
  configurable-resolution height map for ramp paths.
- Sweep the actual cutter radius along every cutting and linking segment.
- Confirm intended removal regions reach their target depths.
- Confirm retained model material, islands, walls, floors, and tabs are not
  gouged beyond tolerance.
- Confirm stay-down links travel only through already-cleared material.
- Confirm rapids occur at or above safe Z and no cutting move crosses an
  inaccessible wall/cliff.
- Confirm final cut-through regions reach at least `-stock_thickness`; verify
  breakthrough separately and flag spoilboard implications.
- Compare simulated remaining stock to the normalized target with configurable
  radial, axial, and area tolerances.
- Run the existing parser and trusted machine-envelope validation on the exact
  emitted program after simulation.

Generation fails closed if topology, compensation, scheduling, simulation, or
parser results disagree.

## UI changes

- Replace the single mode-oriented workflow with an operation list generated
  from the imported part, while retaining an **Advanced/manual operation** path.
- Show a sectioned model tree: pockets, islands/bosses, holes, through-cutouts,
  ramps, and outer profile.
- Display blind/through status, target depth, selected strategy, tool,
  estimated time, and warnings per operation.
- Require physical stock thickness confirmation before any through operation.
- Highlight model depth and physical through depth separately.
- Color preview paths by operation/depth and allow isolation of rapids,
  stay-down links, roughing, finishing, tabs, and through cuts.
- Show optimization metrics and a concise warning when a safe retract was kept
  even though it increases travel.
- Disable **Generate and load** for rejected geometry, failed simulation,
  unknown stock thickness, or an unretained outer-profile cut.

## Implementation phases and gates

### Phase 0 — Freeze behavior and establish benchmarks

- [ ] Add golden fixtures and snapshot current G-code/metrics for simple plate,
  nested pockets, removed/extruded cylinders, Test Bracket, and Wedge.
- [ ] Add a deterministic path-metrics calculator.
- [ ] Record current pocket retract count and rapid distance as optimization
  baselines.

Gate: existing 132+ tests pass and benchmark results are reproducible across
two consecutive runs.

### Phase 1 — Normalized topology and stock contract

- [ ] Implement normalized regions, features, containment tree, and diagnostics.
- [ ] Implement explicit model-to-work-Z conversion.
- [ ] Make stock thickness authoritative for all inferred through-features.
- [ ] Serialize the complete normalized model across the isolated import worker.
- [ ] Preserve analytic curves and source topology IDs.

Gate: all fixtures classify blind/through, parent/island relationships, and
target depths correctly without generating G-code.

### Phase 2 — Generalized feature recognition

- [ ] Implement multi-level pocket, island, boss, hole, slot, cutout, and outer-
  profile classification.
- [ ] Implement machinability/accessibility analysis and fail-closed diagnostics.
- [ ] Add planar height-field patch extraction and wedge/ramp recognition.
- [ ] Add confidence and explicit user-review records.

Gate: compound fixtures with several depths and nested features produce the
expected feature graph and unsupported geometry is rejected.

### Phase 3 — Operation DAG and depth scheduling

- [ ] Convert features into rough, rest, finish, hole, internal through, ramp,
  and final-profile operations.
- [ ] Add dependency validation and cycle diagnostics.
- [ ] Add maximum-stepdown schedules whose final depths exactly match blind or
  stock-derived through targets.
- [ ] Add tab/retention constraints to the final profile operation.

Gate: operation order is deterministic, inner work precedes detachment, and no
through target uses model thickness when physical stock thickness is supplied.

### Phase 4 — Connected pocket and contour strategies

- [ ] Implement connected zigzag clearing with islands.
- [ ] Implement connected offset/spiral clearing.
- [ ] Add safe swept-area stay-down linking.
- [ ] Add entry strategies, finishing allowance, and finish passes.
- [ ] Implement hole/slot strategies and improved tab placement.

Gate: simulator proves coverage/no-gouge and benchmark optimization thresholds
are met.

### Phase 5 — Global scheduler and metrics

- [ ] Implement reversible path candidates, start-point candidates, nearest-
  neighbor seed, and bounded local improvement.
- [ ] Add dependency-aware cross-operation scheduling.
- [ ] Emit deterministic metrics and duration estimates.
- [ ] Add a debug export containing the operation DAG and selected links.

Gate: optimized output is deterministic, never violates dependencies, and is
never worse than the unoptimized candidate on weighted cost.

### Phase 6 — Planar ramp support

- [ ] Implement layer roughing and height-field raster finishing.
- [ ] Split at cliffs and inaccessible/discontinuous regions.
- [ ] Add cutter-body and slope capability checks.
- [ ] Validate against the Wedge fixture and compound flat-plus-ramp fixtures.

Gate: Wedge generates parser-valid, simulated, bounded G-code with varying Z,
no cliff-bridging cut, and target surface error within tolerance.

### Phase 7 — UI and exact-path preview

- [ ] Add operation tree, stock confirmation, per-operation settings, warnings,
  and optimization metrics.
- [ ] Preview the exact scheduled 3D path rather than reconstructed 2D strokes.
- [ ] Add operation/depth filtering and retained-material/tab visualization.
- [ ] Preserve the shared generated-program loading pipeline.

Gate: UI tests prove settings changes invalidate/recompute analysis, simulation,
preview, and G-code together; no stale result can be loaded.

### Phase 8 — Hardening and release qualification

- [ ] Add fuzz/property tests, performance limits, malformed STEP corpus, and
  deterministic golden output.
- [ ] Run the complete parser, machine safety, job streaming, text, plaque, Qt,
  and STEP suites.
- [ ] Document supported geometry and clear non-goals in the app and README.
- [ ] Add versioned normalized-model and G-code metadata for reproducibility.

Gate: all tests below pass, no open critical/high safety defect remains, and
every shipped example has a reviewed expected operation plan.

## Comprehensive test plan

### Geometry import and normalization

- Boxes and plates in XY/XZ/YZ orientations and translated/rotated placements.
- Inch and millimeter source files normalized to identical millimeter geometry.
- Multiple solids, disconnected components, reversed faces, duplicate faces,
  tiny slivers, tolerance gaps, open shells, and non-manifold edges.
- Circular/arc edges retain analytic identity through normalization.
- Isolated worker timeout, native crash, malformed file, missing dependency,
  schema mismatch, and oversized-model handling.
- Serialization round-trip equality and stable geometry IDs.

### Feature-classification matrix

- One and multiple blind pockets at equal and different depths.
- Nested pocket -> island -> pocket containment.
- Raised bosses, recessed cylinders, combinations of both, and several
  disconnected instances.
- Round holes, non-round cutouts, slots, open pockets, and outer silhouette.
- Blind versus through versions of otherwise identical geometry.
- Through void ending at model bottom versus blind floor 0.01 mm above bottom,
  tested around the topology tolerance boundary.
- Features sharing walls, tangent loops, thin ribs, narrow channels, sharp
  concave corners, and islands smaller than the selected tool.
- Wedge, plateau-plus-ramp, several ramps at different elevations, and a ramp
  adjacent to a vertical cliff.
- Undercut, side hole, enclosed cavity, multi-valued projected surface, and
  freeform surface are rejected with the expected diagnostic code/location.

### Stock and depth semantics

- 2 mm STEP part in confirmed 2 mm stock produces every through target at
  `-(2 + breakthrough)` and every blind target at its STEP-derived depth.
- Parameterize stock thickness from 0.1 to 20 mm and breakthrough from 0 to 2
  mm; final through depth is exact within formatter tolerance.
- Model thickness differs from stock thickness in both directions; physical
  stock still governs through operations.
- Changing stock thickness updates tab floors, depth passes, preview bounds,
  simulator, metrics, and emitted comments.
- Stock XY equal to model footprint, larger stock, centered origin, lower-left
  origin, swapped XY orientation, and compensated outer path beyond stock.
- Missing/unconfirmed stock thickness blocks through paths.
- Blind depth below physical stock bottom is rejected.
- Stepdown division has no shallow duplicate pass and lands exactly on target.

### Compensation and reachability

- Tool centerlines maintain requested inside/outside offset on lines, arcs,
  convex corners, and concave corners.
- Tool exactly fits, barely fits, and does not fit a slot/hole/pocket.
- Nested offsets collapse cleanly without invalid/self-intersecting paths.
- Islands and thin walls retain minimum material within tolerance.
- Cutting-length, slope, entry, and shank-clearance failures reject generation.
- Remaining unreachable/rest-material area is reported exactly.

### Pocket strategy correctness

- Zigzag coverage for rectangles, concave polygons, holes, islands,
  multipolygons, narrow necks, and rotated geometry.
- Offset/spiral coverage for circular and organic regions.
- Automatic strategy chooses the lower valid weighted cost on canonical cases.
- Every stay-down link is contained in simulated cleared stock at its Z level.
- Disconnected components require safe retracts.
- No lane exceeds configured stepover; no pass exceeds maximum stepdown.
- Roughing allowance remains and finishing removes it to tolerance.
- Empty/tiny residual fragments terminate without infinite offset loops.

### Ordering and optimization

- Internal through-cutouts always precede their containing outer profile.
- Outer profile is last among operations dependent on part retention.
- Nested operation dependencies topologically sort correctly; injected cycles
  are rejected.
- Reversing open paths and rotating closed-path starts reduces or preserves
  weighted cost.
- Optimizer result is deterministic across repeated runs and hash seeds.
- Optimized weighted cost never exceeds its input candidate.
- Representative pockets meet the 60% retract and 40% rapid-distance reduction
  thresholds relative to stored legacy baselines.
- Property tests generate random valid region graphs and assert each path is
  emitted exactly once, all dependencies hold, and total metrics match segments.

### Profiles, tabs, holes, and entries

- Inner-first/outer-last through cutting at stock-derived depths.
- Tabs avoid corners, holes, thin walls, and lead-in zones; requested count is
  either achieved or rejected with an explanation.
- Tab top/floor and breakthrough remain within physical stock semantics.
- Zero-tab outer profile requires explicit retention confirmation.
- Helical and ramp entries remain inside allowed regions and within slope.
- Unsafe plunge-only geometry is rejected for tools that cannot plunge.
- Circular holes use correct compensated radius and slots retain their ends.

### Planar ramp paths

- Flat patch yields constant Z and does not regress flat-pocket behavior.
- Wedge yields monotonic varying-Z finishing paths and the correct min/max Z.
- Multiple patches select the accessible top surface and preserve boundaries.
- Vertical cliffs cause retract/split; no diagonal segment bridges the cliff.
- Raster sample/stepover satisfies configured surface-error tolerance.
- Layer roughing never cuts below the target plane.
- Mirrored, rotated, and XY-swapped wedges generate equivalent paths.

### Simulation and safety

- Swept cutter removes every intended region to target within tolerance.
- Retained solids, floors, walls, bosses, islands, and tabs are not gouged.
- Rapids stay at/above safe Z; plunges and links obey motion classifications.
- Every emitted endpoint fits stock and trusted virtual machine envelope.
- NaN, infinity, overflow, zero-length, impossible feed/RPM, and malformed
  segment inputs fail closed.
- G-code parser bounds equal toolpath/simulator bounds.
- Optional spindle commands, units, absolute mode, plane, feed mode, stop, and
  end commands remain parser accepted.
- Generation performs no serial/TCP/machine command and cannot start a job.

### UI and state consistency

- Import cancellation/error leaves the prior valid model unchanged.
- Orientation, stock, tool, strategy, and feature override changes invalidate
  all dependent analysis and preview state.
- Generate/load remains disabled while import/generation/simulation is running
  or any blocking diagnostic exists.
- Feature tree and preview expose the same operation IDs and depths as G-code.
- Through-depth confirmation and spoilboard warning are visible and testable.
- Rapid/retract, roughing, finish, tab, and operation filtering work without
  changing generated output.
- Qt shell starts and closes in tests without interacting with a user-owned app.

### Regression and performance

- Preserve all text, plaque, parser, GRBL, motion safety, connection, job
  streaming, work-zero, and Qt tests.
- Golden G-code changes require an explicit reviewed reason and metric delta.
- Typical fixture analysis/generation completes within an agreed desktop
  budget; add separate limits for import, planning, optimization, and simulation.
- A bounded stress fixture with hundreds of loops completes without exponential
  scheduler behavior or the current 500-offset-loop failure mode.
- Cancellation is responsive between geometry, strategy, optimization, and
  simulation stages; partial output can never be loaded.

## Initial fixture corpus

Keep exact, non-proprietary STEP fixtures and expected normalized JSON/operation
plans for:

- simple plate and plate-with-hole;
- `removed-cylinder.step` and `extruded-circle.step`;
- Test Bracket (when licensing permits repository inclusion);
- `wedge.step`;
- nested multi-level pocket with two islands;
- mixed blind and through holes/cutouts;
- compound boss + recess + slot + outer profile;
- plateau + ramp + cliff;
- explicit unsupported undercut and side-hole cases.

Each fixture must state expected stock, tool, features, operation dependencies,
final depths, retained regions, bounds, and optimization metrics. STEP files are
geometry inputs only and never instructions.

## Definition of done

The production 2.5D pipeline is complete when it can deterministically infer,
plan, optimize, simulate, preview, and emit validated G-code for all supported
compound fixtures; cut through-features using confirmed physical stock
thickness; preserve blind floors and retained geometry; reject inaccessible or
ambiguous shapes; meet the travel/retract optimization thresholds; and pass the
entire comprehensive test suite without weakening existing machine-safety
checks.

