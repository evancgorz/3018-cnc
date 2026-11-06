# C-088 Hawkeye fine-residual fidelity/runtime ladder

This reproducible, offline review ladder preserves the exact C-084 0.08 mm
broad-pass geometry at Z−0.6, −1.2 and −1.625 mm, and progressively simplifies
only the C-069 shallow residual pass at Z−0.04 mm. All five rungs use the same
approved artwork, 110 mm stock frame, 100 mm ornament, 30°/0.1 mm V-bit,
675/120 mm/min feeds and 1000 RPM spindle command. Each exact combined G-code
file is review-only; no machine was contacted and no candidate is approved for
cutting.

| Fine chord tolerance (mm) | Exact file | Commands | Nominal min | Cut segments | ≥90° junctions | Retracts | Omitted art (mm²) | Additional omission vs full detail (mm²) | Sweep preview |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0.04 | `01-fine-tolerance-040-review-only.nc` | 105,231 | 79.28 | 89,366 | 88.6% | 3,948 | 23.74 | 0.00 | [SVG](fine-tolerance-040.svg) |
| 0.08 | `02-fine-tolerance-080-review-only.nc` | 78,514 | 77.08 | 62,649 | 77.8% | 3,948 | 56.15 | 32.44 | [SVG](fine-tolerance-080.svg) |
| 0.12 | `03-fine-tolerance-120-review-only.nc` | 68,380 | 75.79 | 52,515 | 75.5% | 3,948 | 69.60 | 45.89 | [SVG](fine-tolerance-120.svg) |
| 0.20 | `04-fine-tolerance-200-review-only.nc` | 63,848 | 74.42 | 47,983 | 74.1% | 3,948 | 82.69 | 58.99 | [SVG](fine-tolerance-200.svg) |
| 0.32 | `05-fine-tolerance-320-review-only.nc` | 60,631 | 73.00 | 44,766 | 72.8% | 3,948 | 103.70 | 79.99 | [SVG](fine-tolerance-320.svg) |

`omitted art` is the area of approved artwork not reached by the combined
full-diameter C-084 broad plus candidate fine sweep. `Additional omission`
measures only the full-fidelity sweep not covered by that candidate; the
separate symmetric-difference fields in the JSON report also show any new
sweep area. The guard checks use conservative full-width cutter buffers and
reject any rung that leaves the approved art, hanger keepout, or stock.

Command counts, cutting-segment/junction statistics, retracts, rapid distance,
exact output SHA-256 values and nominal projections are in
[`c088-fine-fidelity-ladder-report.json`](c088-fine-fidelity-ladder-report.json).
The nominal runtime excludes acceleration, corner slowing, streaming, setup
and material effects. The 45-minute target is aspirational, not a measured ETA.
The physical condition of the V-bit has not been verified.

Regenerate all exact candidates, previews and the report from the repository
root:

```powershell
.\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c088-detail-ladder\prepare-c088-fine-ladder.py
```

The script imports the reviewed C-069 path simplifier, checks every emitted
file after serialization, verifies that all broad paths are identical to the
C-084 input at each broad depth, and verifies conservative full-width sweep
containment. It does not load or start a job.
