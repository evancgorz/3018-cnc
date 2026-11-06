# Agent-guided CNC job preparation

Use this guide for agent-assisted CAM, G-code generation, review, and offline
optimization in this repository. Keep preparation reproducible and reviewable;
the existing application/backend remains the only machine-control path.

## Run the workflow

1. Turn the concept into a design spec. Copy the closest example and keep the
   design intent in `concept`. The CAM engine uses `settings` and any source
   file to generate geometry. For original artwork or a CAD part, create or
   obtain that source first and check its outline and scale.

   | Template | Source | Operation |
   | --- | --- | --- |
   | [Plaque](../examples/agent-cam/plaque.json) | Text and layout in JSON | Single-pass V-bit lettering and border |
   | [Raster](../examples/agent-cam/raster.json) | Dark-on-light artwork, square crop | Fixed-depth V-bit fill |
   | [STEP pocket](../examples/agent-cam/step-pocket.json) | STEP outline | Shallow flat-endmill pocket from the top XY face |

   Source paths are relative to the JSON. Dimensions are mm, feeds are mm/min,
   depths are positive distances below the stock top, and the origin is G54
   lower-left XY with Z0 on the top. Use measured or supplied stock and tooling.
   Set spindle RPM to explicit `null` for a candidate without spindle startup.
   Use the optional `notes` field for material, clamp layout, and the source of
   measurements.
2. Build into a new directory from the repo root. The installed equivalent is
   `pine-cam`.

   ```powershell
   .\.venv\Scripts\python.exe -m ttc3018_control.agent_cam examples\agent-cam\plaque.json artifacts\pine-plaque-review
   ```

3. Inspect `candidate-review-only.nc`, `cutter-sweep.svg`, and `report.json`.
   Check the footprint against the intended geometry, stock, and clamping.
   The report contains hashes of the exact files, emitted bounds, depth levels,
   nominal motion metrics and CAM-specific evidence. The SVG shows the top
   footprint using emitted cutting moves. CAM runs without a backend.
4. Rebuild with the bundle's `design.json` and a fresh output directory to
   reproduce it. The source is copied into the bundle when present. Use the
   same Pine version and dependencies for a byte-for-byte comparison.

For variable-depth carving, tabs, through cuts, or multi-tool projects, use the
underlying CAM tools and the review checklist below.

## Backend API and CLI

The GUI and CLI share an authenticated, versioned JSON API over loopback HTTP.
The GUI and standalone `pine-backend` keep their current launch default: their
data root is the process working directory. The backend also registers only its
root, PID, and session ID in a per-user locator; that locator never contains the
authentication token. `pine-cli` and `BackendClient()` first use a valid
`pine-backend.json` in the current directory, then a unique registered backend,
and otherwise retain the current-directory default. If multiple registered
backends are active, select one explicitly with `--root` or
`BackendClient(Path(data_root))`. The backend selects its port at startup. Keep the
root-local `pine-backend.json` private; it contains the authentication token.

Discover commands offline:

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.backend.cli --help
.\.venv\Scripts\python.exe -m ttc3018_control.backend.cli load-job --help
```

When the current request permits backend observation, set `$pineRoot` to the
running backend's data root and query it. From another working directory, ask
the CLI to discover and attach to the unique registered backend first:

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.backend.cli discover --json
.\.venv\Scripts\python.exe -m ttc3018_control.backend.cli --root $pineRoot capabilities --json
.\.venv\Scripts\python.exe -m ttc3018_control.backend.cli --root $pineRoot status --json
```

If attachment fails, check the root, whether the existing backend is running,
and whether client and backend versions match. The CLI never starts a backend.
For Python auto-discovery, use `BackendClient()`; for an isolated development
root, pass it explicitly as `BackendClient(Path(data_root))`. Call `attach()`
and then `snapshot()`. `discover --json` returns the selected root and
token-free owner/version metadata. See the
[CLI implementation](../src/ttc3018_control/backend/cli.py) for action names
and payloads.

When the current request authorizes loading the reviewed file, use
`load-job <absolute-path-to-report.json> --json` with the same root. The desktop
job picker also accepts the report, and both entry points still accept plain
G-code. The backend verifies the bundle hashes before replacing the loaded job.
See the [review bundle contract](CNC_REVIEW_BUNDLES.md). `job-status`,
`review`, and `preflight` report on its current job. Loading changes that job,
and starting it requires separate authorization and physical checks.

For an isolated machine data root, launch the GUI with
`run.bat --data-root <path>`; the default remains the launch working directory.
To copy durable machine settings and review-only recovery context to a new root,
use `.\.venv\Scripts\pine-migrate-data.exe migrate <source-root> <new-root>`
and verify it with `.\.venv\Scripts\pine-migrate-data.exe verify <new-root>`.
The source stays intact for rollback;
backend discovery/owner records and connection credentials are not migrated.
See [backend recovery](BACKEND_RECOVERY.md#selecting-or-migrating-a-data-root)
for the allowlist and desktop shortcut options.

## Reusable prompts

Fill in the bracketed fields and send one short prompt. Attach or point to the
source art/model and known measurements.

### Prepare an offline candidate

> Prepare `[part/job]` from `[source path]` for `[machine/material]`. Use only
> the stated tool, stock, work origin, depth, feed, spindle, and clearance
> values; list unknowns instead of guessing. Reuse the repository CAM/parser
> where suitable. Save a reproducible generator and settings with the output in
> a new `artifacts/...` folder. Include the exact generated file, a physical-size
> tool-sweep preview, a concise report with source/settings/output hashes,
> bounds, depth/pass data, coverage or omitted detail, and nominal runtime
> assumptions. Parse and check the exact emitted file. Keep this offline and
> review-only; do not load or start it.

### Improve an existing candidate

> Compare `[baseline path/hash]` with a candidate that changes only `[one
> variable]`. Keep the source art, tool, stock, origin, depth, and other settings
> fixed. Preserve and report the full-diameter cutter sweep, retained/omitted
> area; source, settings, baseline and output hashes; cut and rapid XY/Z
> distances; retract cycles; stay-down link count and length; and short-segment
> and junction distributions. State which path orders and directions changed,
> and verify that the exact rounded output retains baseline cutter-sweep coverage.
> Save the candidate separately with a generator and exact-file verification;
> do not overwrite or silently release the baseline.

### Independently review a candidate

> Independently review `[candidate path]` against `[source/settings/report]`.
> Recompute the cutter sweep from the emitted, rounded G-code and verify bounds,
> depth/pass limits, rapid clearance, supported commands, operation order, and
> source/settings/file hashes. Compare artwork coverage and all changed
> assumptions against the baseline. Report each check as pass, fail, or unknown;
> do not infer physical readiness from a parse or preview.

### Physical execution request

> I authorize `[specific machine interaction]` for `[specific file/hash]` in
> this request. First report the backend's fresh connection, Idle, spindle-off,
> and configured safety-gate state. Do not proceed if any required fact is
> unknown or fails. Do not broaden this authorization to an unlisted file,
> follow-on operation, GUI interaction, restart, or subsequent job.

## Preparation workflow

1. **Identify the actual path.** Read the relevant generator, parser, tests,
   current job/settings, and prior artifact report. Prefer existing geometry,
   compensation, parser, validation, and simulation code over a second pipeline.
2. **Freeze inputs.** Record units; source hash; stock dimensions/thickness and
   flatness; exact cutter geometry; XY origin/transform; work Z0; operation order;
   max depth/pass; feeds; spindle; and safe clearance. Mark each value as
   measured, user-reported, assumed for comparison, or unknown. Do not turn an
   unknown into a production value.
3. **Generate into a new run folder.** Keep the source or a stable reference,
   settings/project JSON, generator, output G-code, preview, report, and
   verifier together. Do not edit generated G-code by hand; update the generator
   or inputs and regenerate. Include hashes so the report identifies the exact
   reviewed bytes.
4. **Verify what will be emitted.** Parse the final rounded G-code with the
   shared parser in `src/ttc3018_control/gcode.py`. Check work bounds, rapid
   clearance, units/modes, depths and pass-down, command support, terminal
   spindle-off/program-end behavior, and expected operation order. Compute the
   cutter sweep at each relevant tool/depth, including V-bit width growth; a
   centerline preview alone is insufficient. Keep multi-tool jobs as separate
   files unless a supported, reviewed tool-change workflow exists.
5. **Compare candidates on fixed assumptions.** Show source, settings, baseline,
   and candidate hashes. For geometry changes, report swept-area containment and
   coverage/omission changes. For motion changes, report cut distance, rapid XY
   and Z distance, retract cycles, stay-down links and their length, short
   segment and junction distributions, plus what the time estimate includes
   and excludes. Check metrics against the exact parsed output. Do not describe
   commanded feed or nominal time as measured machine throughput. Treat short
   segments, sharp junctions, retracts, and planner starvation as runtime costs:
   GRBL's look-ahead is finite, so increasing programmed feed alone does not
   make a dense raster path run at that feed.
   For filled artwork, compare clearing strategies per connected compensated
   region, including alternating scanlines and concentric offsets. Evaluate the
   actual final surface left by the cutter, not merely the top-view footprint:
   a V-bit can cover a region in plan view while leaving deep ridges between
   paths. Compare residual material, finish, travel, retracts and short moves
   at the same tool geometry and depth. Choose per region based on the desired
   finish and measured tradeoffs, rather than assuming either pattern is best.
   Prefer completing a region before moving to another when doing so does not
   compromise coverage or finish; report any resulting travel tradeoff.
6. **Respect the requested boundary.** Follow the user's current instructions
   and applicable `AGENTS.md` rules for app, backend, and hardware interaction.
   An abort or a request to prepare without starting does not authorize a new
   cutting run; do not silently treat an offline candidate as physically tested.

## Repository example

For a compact, repeatable analysis of any supported G-code file, run
`.\.venv\Scripts\python.exe -m ttc3018_control.job_analysis path\to\job.nc`.
It reports the file hash, bounds, nominal feed-based time, cut and rapid XY/Z
distances, feed plunges, retracts, and short-segment/junction statistics. Its
time estimate excludes acceleration and corner slowdown; its centerline
statistics do not replace cutter-sweep verification. Ornament CAM reports also
bind settings and output hashes, compare planned metrics with the parsed output,
and count stay-down links from the verified path schedule.

### Performance metrics and calibration

When a job has a requested time target, add a nonblocking comparison to the
offline report:

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.job_analysis `
  path\to\candidate.nc `
  --target-minutes 45 `
  --machine-profile-key "3018-stockspindle-vbit30-0p1-plywood-raster-v1" `
  --calibration-json path\to\completed-run-calibration.json
```

The profile key must identify the machine/controller motion setup, tool, stock,
and CAM motion family. Reuse a calibration only when those conditions and the
candidate's segment/junction/retract complexity are reasonably comparable. A
key is a label, not an automatic similarity check: include the analyzed motion
metrics when reviewing the calibration set. Do not mix machines, tools,
materials, or materially different path families under one key.

This is a warning and estimate only; it never prevents loading or starting a
job. The profile key must reflect comparable machine/tool/material and motion
behavior. These checks reflect GRBL's own limits: its planner holds a finite number of
motion blocks, and the GRBL interface guide describes short-line starvation
under simple send/response streaming and recommends character-counting for
better throughput. Pine already uses character-counting; CAM geometry can still
keep the planner full while forcing low speeds at corners. GRBL's `$11` junction
deviation setting trades corner speed against lost-step/positioning risk, so
record the actual setting and validate it on the specific machine before using
it to justify a runtime claim. See the primary [GRBL streaming guide](https://github.com/gnea/grbl/blob/master/doc/markdown/interface.md#streaming-protocols)
and [GRBL settings reference](https://github.com/gnea/grbl/blob/master/doc/markdown/settings.md).

Calibration JSON has this shape:

```json
{
  "schema_version": 1,
  "machine_profile_key": "3018-stockspindle-vbit30-0p1-plywood-raster-v1",
  "completed_runs": [
    {
      "completed": true,
      "run_id": "engraving-run-2026-01",
      "program_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "nominal_seconds": 5391.1,
      "observed_seconds": 12780.0
    }
  ]
}
```

Only whole, completed physical runs count. Partial runs, accepted-command
counts, and controller queue counts are not physical progress. The report
multiplies candidate nominal time by the largest observed actual/nominal ratio
for the matching profile. It labels estimates based on fewer than three runs as
provisional and estimates based on three or more as established. A profile
mismatch or missing completed runs is reported plainly. The projected duration
remains empirical, not guaranteed; target comparisons never replace geometry,
safety, or operator review and never block execution.

Use `cut_segments_at_most_0_1mm_percent`,
`cut_segments_at_most_0_25mm_percent`,
`cut_junctions_at_least_90_degrees_percent`, and
`retracts_per_1000_commands` to see why a nominal estimate may be optimistic.
Compare these with completed-run reference jobs before relying on the projected
time. Optimize path count and safe stay-down connections first; change feeds,
acceleration, or junction settings only with the actual tool/material/machine
conditions known and separately verified.

For the standalone fixed-depth ornament exporter, see
[`ORNAMENT_CAM_PLAN.md`](ORNAMENT_CAM_PLAN.md) and
`src/ttc3018_control/ornament_cam.py`. It accepts a source image, a complete
settings JSON, and a new output directory:

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.ornament_cam `
  path\to\source.png path\to\settings.json artifacts\job\candidate-01
```

The exporter writes `engraving.nc`, `report.json`, and
`engraving-preview.svg`; it refuses an existing output directory. Its preview
is a top-surface cutter-footprint view, not a material-removal or floor-finish
simulation. The report's estimated time is nominal and does not establish
physical feeds or runtime. Check each export warning and the actual source,
tool, stock, and machine setup before considering any physical use.

For ornament candidates with custom vector or two-pass generators, follow the
same bundle pattern used by
[`C-058 controller-efficient candidate`](../artifacts/ornaments/hawkeye/two-bit/c043-runtime/c058-controller-efficient/README.md):
keep a reproducible preparation script, exact review file, geometry report,
verification evidence, and clear review-only status together.
