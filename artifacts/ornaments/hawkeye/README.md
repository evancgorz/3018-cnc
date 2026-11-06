# Hawkeye ornament preparation

`approved-artwork-reference.png` is the approved generated black/white illustration,
retained unchanged. It is a tracing reference, not an engineering drawing.

The ornament outside diameter is 100 mm. The example maps the entire square
image canvas to 90 mm inside that disc; white image margins mean the ink itself
is slightly smaller. Work XY origin is lower-left of a hypothetical 110 mm
square stock blank, with the disc centered at X55 Y55. Z0 is the stock face.
All dimensions are metric. This is not an instruction to establish machine zero.

## Offline generation

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m ttc3018_control.ornament_cam `
  artifacts/ornaments/hawkeye/approved-artwork-reference.png `
  artifacts/ornaments/hawkeye/illustrative-settings.json `
  artifacts/ornaments/hawkeye/new-review-export
```

The output folder must not already exist. It contains shallow engraving G-code,
a cutter-footprint SVG preview and a JSON report. The code only prepares files;
it does not use the backend, discover a controller or run the machine.

`draft-review-v2/` is the initial checked baseline. Its report and
`verification.json` record source/output hashes and parser/clearance checks.
The rendered `engraving-preview.png` shows that many fine aircraft contours
disappear at the illustrative cutter width. About 9.34% of black area is
unreachable, with eight components omitted completely. At nominal feeds the
retract-heavy two-pass baseline estimates 626 minutes. **This example fails the
artwork-fidelity and practical-runtime goals and is not a released cutting
file.** The exporter makes this measurable; C-019/C-020 address those gaps.

`illustrative-settings.json` is deliberately **not a production tool preset**.
Only 100 mm ornament size and the reported 60-degree angle are established.
Nominal 3 mm thickness, 0.10 mm tip, 0.25 mm engraving depth, 0.15 mm stepover,
0.125 mm stepdown, 3 mm clearance and 300/80 mm/min feeds are explicit example
assumptions for checking the software. Replace these with verified measurements
and suitable tested cutting parameters. `spindle_rpm: null` emits M5 but no M3;
the example is therefore not a runnable cutting recommendation. Do not simply
start the example with the spindle off.

Black areas are shallow recesses; white areas remain wood. Fixed-depth clearing
can lose fine lines smaller than the V-bit footprint. Review the report's lost
area and swept preview; the preview does not predict plywood veneer damage,
depth uniformity, floor scallops or real machine readiness.

This exporter does **not** generate the hanging hole or outside cut. Those need
an aligned profile export using the existing compensated/tabbed profile engine,
after actual cutter diameter, thickness, hold-down, hanger reserve and common XY
placement are confirmed. No through-cut file is released in this package.

## Runtime correction

`runtime-optimized-v1/` records the intermediate scheduling-only comparison
(238.67 minutes with unchanged depth/feeds/clearances). `runtime-approach-v1/`
uses `approach-illustrative-settings.json`: identical cutting settings plus an
explicit **0.2 mm vertical approach** after XY travel at 3 mm. Its nominal
engraving estimate is 146.94 minutes. Reduced approach is an assumption requiring
measured stock flatness/clearance, not a verified physical setting.

`runtime-approach-v1/runtime-comparison.json` also records a 75.74-minute
single-pass timing projection. That projection assumes max stepdown 0.25 rather
than 0.125 mm; it was computed in memory and is not exported as a cutting
recommendation. All times exclude cutout, tool changes and acceleration.
Fine-detail losses remain. The backlog now prioritizes changing the engraving
strategy before production, rather than accepting the raster cycle time.

Recompute comparison after generating the named packages:

```powershell
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/compare_runtime.py
```

The optional `optimize_paths` flag defaults to true; false reproduces the old
ordering. `approach_z` defaults to null, retaining full-clearance feed approach.

See [the implementation backlog](../../../docs/ORNAMENT_CAM_PLAN.md) for the
next steps. Physical testing requires separate authorization.
