# Hawkeye ornament project — offline review only

This reproducible project retains `artifacts/ornaments/hawkeye/approved-artwork-reference.png` as its source. It rasterizes the approved black artwork at threshold 128, maps that image to a 90 mm field centered inside an analytic 100 mm disc, and records the exact source/setup/output SHA-256 values in `ornament-project.json` and `review-report.json`.

The engraving uses the existing fixed-depth raster V-bit generator. The disc/hole program uses the existing STEP profile compensation and tabbed-profile simulation. Both files share a lower-left 110 × 110 mm candidate stock frame. The actual supplied setup records describe 100 × 100 mm stock, so this candidate blank is explicitly unverified and is **not** a silent change to either setup record.

## Rebuild

From the repository root, offline:

```powershell
.\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c018-reproducible-project\prepare.py
```

The script writes the vectorized artwork reference, engraving and profile NC files, separate engraving/profile cutter-sweep previews and hashes/review report in this folder. It only uses the repository Python CAM/parser/simulation code. It does not connect to Pine, a backend, a GUI, or hardware.

## Geometry and review

- The artwork is a thresholded raster conversion, not newly authored vector art. Keep the approved PNG unchanged; the SVG is a derived geometry record.
- The 100 mm part is centered at stock XY (55, 55). The 90 mm artwork field maps to XY [10, 100] in both axes. Both files explicitly select the named setup's G54 P1 slot; the physical work zero remains unverified.
- The 4 mm hanger hole is centered at (55, 100); a 3 mm radial engraving keepout is reserved around it. The theoretical part-edge wood ligament from hole edge to disc edge is 3 mm.
- The report sweeps exact emitted engraving/profile XY moves with their respective cutter radii, checks nonnegative work XY and rapid-Z clearance, checks the hanger keepout and stock bounds, and records profile simulation, operation order and tab dimensions. Unengraved black source area is quantified, not hidden.
- The feature report measures raster-vector black-component maximum-inscribed diameters, minimum separation between disconnected black components, and enclosed-counter maximum-inscribed diameters. These are geometric proxies; the exact emitted sweep and residual-area figures remain the definitive cutter-accessibility check. Counters below the cutter diameter are counted explicitly.
- Review-only illustrative values include engraving depth/stepover/stepdown, feed/plunge rates, safe Z, breakthrough and tabs. Spindle start is omitted. Do not copy these values into a production job without measurement and separate review.

## Compatibility and unresolved release blockers

Uses `ornament_cam.generate_engraving`, `gcode.parse_gcode` and its work-boundary/rapid validators, plus `step_engraver.generate_step_gcode` and the existing profile simulation. No M6 or unsupported tool-change path is used; the programs are separate.

The 100 × 100 mm setup blank cannot contain a 100 mm finished disc with outside-cutter clearance. The candidate uses a distinct 110 × 110 mm blank that is not measured or recorded by either setup. Actual fixture/clamp clearance, safe Z, endmill flute/usable length and holder clearance, feeds/RPM/material response, breakthrough/tab retention and stock flatness remain unknown. The outputs are therefore not production-released and must not be loaded or started on a machine.
