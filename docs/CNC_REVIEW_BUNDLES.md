# CNC projects and review bundles

A project keeps the design brief, editable spec, source geometry, and
project-specific generator if needed. Use a named directory under
`projects/` for shared work or the same layout outside the checkout.
Reference source files relative to the spec. Keep generated drafts in
`artifacts/<project>/<run>/`. Use a new run directory for each candidate.

A single-job Pine CAM v1 bundle contains:

| File | Purpose |
| --- | --- |
| `report.json` | Entry point. Integer `schema_version: 1`, `status: "review-only"`, CAM kind, origin, stock dimensions, tool evidence, emitted depth levels, motion metrics, and SHA-256 map. |
| `candidate-review-only.nc` | Exact bytes to parse, preview, and review. |
| `design.json` | Rebuild spec, including its relative source reference when applicable. |
| `cutter-sweep.svg` | Review illustration generated from emitted motion. |
| `source.<extension>` | Copied source for raster and STEP candidates. |

The SHA-256 map names regular files at the same directory level. Existing
C-096 bundles use the same names and can omit the newer structured tool
description. Their design settings still describe the intended tool.
Pine uses the G-code parser for the actual motion preview. The bundle's
illustration and reported assumptions are evidence for the reviewer.

Try the [plaque example](../examples/agent-cam/plaque.json) from the repo root.

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.agent_cam examples\agent-cam\plaque.json artifacts\plaque-first-review
```

Rebuild from the emitted `design.json` into a new directory. A changed input
requires a new candidate and review of its exact G-code digest. When approving
or running a candidate, retain the exact bytes, report, source/spec, and review
decision together in the project's retained records or equivalent durable
storage. Preserve the existing Hawkeye paths referenced in past handoffs.

For raster artwork, compare stepover candidates from one fixed bundle and set a
maximum fraction of source art that may remain unreachable by the final cutter
sweep. Every candidate changes stepover alone. Its comparison parses the exact
emitted G-code and recomputes the final-depth surface sweep against the source
mask. Candidates outside the requested omission limit remain available for
inspection and are marked as failing that limit. Example:

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.cam_ladder ladder `
  artifacts\pine-cross-baseline\report.json `
  artifacts\pine-cross-ladder `
  --stepover-mm 0.16 0.20 `
  --max-omission-fraction 0.01
```

Each output subdirectory contains a complete review bundle. The sibling
`comparisons/` directory reports exact G-code hashes, sweep omission and excess,
command, cut and rapid distances, retract counts, short-segment and junction
rates, plus feed-based time deltas. The ladder is reproducible from its
baseline bundle and settings. Time deltas do not predict physical completion
time. This comparison currently handles fixed-depth raster engraving only.

Selecting a bundle is a job load. The report's stock, tool, and work-origin
values describe the intended setup. Current machine conditions and permission
to start remain part of the ordinary Pine preflight and authorization flow.


## Ordered engraving and cutout

Build the two pass bundles in separate subdirectories of a new run. The
example uses a centered cross, a tabbed STEP profile and a common lower-left
stock datum. It uses demo settings and leaves spindle startup unspecified.

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.agent_cam examples\agent-cam\sequence-engraving.json artifacts\plate-review\engraving
.\.venv\Scripts\python.exe -m ttc3018_control.agent_cam examples\agent-cam\step-profile.json artifacts\plate-review\cutout
.\.venv\Scripts\python.exe -m ttc3018_control.cam_sequence create artifacts\plate-review\sequence.json --frame "Plate fixture, lower-left of stock" engraving/report.json cutout/report.json
.\.venv\Scripts\python.exe -m ttc3018_control.cam_sequence inspect artifacts\plate-review\sequence.json
```

Inspect the two cutter sweeps against the same fixture before review.
The sequence binds the order and exact pass reports. Open each pass's
`report.json` in Pine when the operator is ready for that pass. At a tool
change, preserve the shared XY datum, establish Z for the installed tool,
and complete the usual review and physical preflight for the newly loaded
file. Loading and starting each pass are explicit actions.
