# C-045: Hawkeye hole and profile review for 3.25 mm plywood

This is a separate offline review artifact for the endmill leg of the Hawkeye
two-job project. It uses the user-reported measured stock thickness of 3.25 mm.
The earlier two-bit cutout draft and the detail engraving files are unchanged.

## Result

- G-code: [`02-cutout-review.nc`](02-cutout-review.nc)
- Full machine-readable report: [`cutout-report.json`](cutout-report.json)
- Parsed cutter-sweep preview: [`cutout-preview.svg`](cutout-preview.svg)
- Independent offline check: [`independent-verification.json`](independent-verification.json)
- Rebuild source: [`prepare-cutout.py`](prepare-cutout.py)
- Separate spindle-enabled candidate: [`02-cutout-candidate-1000rpm.nc`](02-cutout-candidate-1000rpm.nc)
- Candidate assumptions/report: [`cutout-candidate-report.json`](cutout-candidate-report.json)

The shared work frame remains 110 × 110 mm with lower-left `X0 Y0`, part center
`X55 Y55`, and hanger-hole center `X55 Y100`. The hole completes before the
outside profile starts. The profile retains four 4 mm tabs, each 0.8 mm high;
their floor is `Z-2.45` for 3.25 mm stock. The through-cut target is `Z-3.40`,
including a provisional 0.15 mm breakthrough below the measured sheet. Seven
depth levels are no more than 0.5 mm apart. The parsed linear-feed estimate is
8.73 minutes.

The G-code has no spindle start and does not specify RPM. The endmill's actual
cutting diameter and flute length, machine/material feed settings, local stock
flatness, spoilboard clearance, and tab behavior have not been verified. This
file is for offline review and is not a cutting release. No application,
backend, machine, or hardware was accessed to prepare it.

The separate candidate starts the spindle with `M3 S1000` and places `M5`
immediately before the final `M2`. The 1000 RPM
value is the user-confirmed saved setting that was successful on a prior job.
It adds `G4 P2` for a 2 second startup dwell; the project parser accepts this,
and [standard GRBL v1.1 lists `G4` as supported](https://github.com/gnea/grbl/blob/master/README.md?plain=1), but the controller's installed firmware
version was not checked. The dwell duration is an assumption, and the candidate
still requires review of the listed tool, feed, fixture, and material conditions
before any cut.

Regenerate it from the repository root with:

```powershell
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/prepare-cutout.py
```
