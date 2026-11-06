# C-089 Hawkeye localized adaptive candidate

This is an offline, review-only broad-pass alternative to C-084's 0.08 mm linked raster candidate. It does not contact Pine and must not be treated as loaded or approved for cutting.

For each of the 92 reachable, compensated artwork components, the generator finishes that component before choosing the next nearest component. It uses inward concentric offset rings when their full final-depth V-bit envelope is contained in approved artwork. If that proof cannot be made, the general planner falls back to boundary-plus-connected-scanline clearing for that one component. It never silently skips a component.

The actual Hawkeye result used concentric offsets for all 92 components, with five proven, component-local stay-down links. Every rounded emitted path was checked against the full 0.971 mm final-depth cutter diameter, the hanger keepout, stock bounds, depth sequence, and safe-Z rapid rule.

| Metric | C-084 linked broad raster | C-089 localized adaptive | Change |
| --- | ---: | ---: | ---: |
| Commands | 19,744 | 7,669 | −61.2% |
| Nominal feed-based time | 33.06 min | 13.62 min | −58.8% |
| Cut distance | 19,085.0 mm | 5,993.8 mm | −68.6% |
| Rapid XY distance | 1,979.7 mm | 1,725.9 mm | −12.8% |
| ≥90° cut junctions | 68.9% | 23.4% | lower |
| Omitted approved broad artwork | 697.48 mm² | 768.23 mm² | +70.75 mm² |

The candidate has materially less geometry and fewer sharp corners, which should reduce the controller's small-segment slowdown. Its shorter nominal time is not a physical ETA: it excludes acceleration, planner behavior, connection delays, setup, and wood cutting behavior. It also remains **broad-only**; the shallow fine residual engraving is not included, so it is not a replacement for a full-detail final ornament job.

Recreate and verify the exact bundle:

```powershell
.\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c089-adaptive-regions\prepare-c089-adaptive-regions.py
.\.venv\Scripts\python.exe -m ttc3018_control.job_analysis artifacts\ornaments\hawkeye\two-bit\c089-adaptive-regions\01-detail-c089-adaptive-regions-review-only.nc
```

Artifacts:

- `01-detail-c089-adaptive-regions-review-only.nc` — SHA-256 `31c2773cf30017b15b62a66a2c54cffe5944c644823d37d2b8702210218f9f1a`
- `c089-adaptive-regions-preview.svg` — full-diameter cutter-sweep preview
- `c089-adaptive-regions-report.json` — source/settings/output hashes, parsed comparison, and checks
- `prepare-c089-adaptive-regions.py` — reproducible offline generator
