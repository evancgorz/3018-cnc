# C-084 Hawkeye broad-pass candidates

These are offline review candidates derived from the exact C-069 file. Both
keep its 100 mm ornament frame, 110 mm stock coordinates, 30° V-bit with a
0.1 mm tip, 1000 RPM spindle command, 675/120 mm/min cut/plunge feeds, and
three broad depths at −0.6, −1.2, and −1.625 mm. No hardware was contacted.

The 45 minute goal is an aspiration. The 3018 has no completed-run calibration
for these candidate paths, so the reusable runtime helper correctly reports
nominal-only estimates. Historical accepted-command pace is shown separately
as context; accepted commands do not prove completed machine motion or predict
these candidates' physical time.

## Candidate comparison

| Program | Chord tolerance | Commands | Nominal estimate | Historical command-pace projection | Full-depth artwork omitted | Increase vs C-069 | Sweep difference vs C-069 broad |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C-069 full detail baseline | 0.08 mm broad + fine residual | 107,517 | 89.85 min | Not calibrated | 23.60 mm² (0.98%) | — | — |
| C-084 higher fidelity broad-only | 0.08 mm | 19,744 | 33.06 min | 178–187 min | 697.48 mm² (28.95%) | 673.88 mm² | 0.96 mm² |
| C-084 fewer commands broad-only | 0.50 mm | 11,404 | 29.41 min | 103–108 min | 748.99 mm² (31.09%) | 725.39 mm² | 71.85 mm² |

The 0.08 mm version retains more of the broad geometry. The 0.50 mm version
uses 42% fewer commands than the 0.08 mm version and omits another 51.51 mm²
of approved black artwork; its broad sweep differs from C-069's broad sweep by
71.85 mm². The 0.08 mm version's broad sweep differs by only 0.96 mm². Both
omit the fine residual pass, which is why their coverage loss is much larger
than their chord simplification alone suggests.

Both variants schedule 349 simplified primitive strokes into 101 chains per
pass using 248 stay-down connectors per pass (744 total). Each connector is
included only when the full final-depth cutter disk remains inside approved
artwork. The longest included connector is 11.29 mm; the economic cap from the
configured nominal feeds and retract/plunge distances is 14.46 mm. This cuts
the retract count to 303 from C-069's 4,692, and the rapid distance to 4,086 mm
from 61,334 mm. The remaining path still contains many direction changes, so
the nominal feed estimate is not an actual runtime guarantee.

## Verification and reproduction

`prepare-c084-broad-only.py` regenerates both programs, previews, settings, and
the exact-hash report. It checks parsing, XY bounds, safe-Z rapid moves,
unchanged pass depths, identical broad geometry at every depth, and full-width
cutter-sweep containment after linking. The report also includes generic
`job_analysis` motion metrics and the reusable informational runtime estimate.

```powershell
.\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c084-runtime-45m\prepare-c084-broad-only.py
.\.venv\Scripts\python.exe -m ttc3018_control.job_analysis artifacts\ornaments\hawkeye\two-bit\c084-runtime-45m\01-detail-c084-broad-only-008-review-only.nc
.\.venv\Scripts\python.exe -m ttc3018_control.job_analysis artifacts\ornaments\hawkeye\two-bit\c084-runtime-45m\02-detail-c084-broad-only-050-review-only.nc
```

Review-only artifacts:

- [Higher fidelity G-code](01-detail-c084-broad-only-008-review-only.nc)
- [Fewer commands G-code](02-detail-c084-broad-only-050-review-only.nc)
- [Exact metrics and hashes](c084-runtime-report.json)
- [Settings and assumptions](c084-settings.json)
- [0.08 mm cutter-sweep preview](c084-broad-only-tolerance-008.svg)
- [0.50 mm cutter-sweep preview](c084-broad-only-tolerance-050.svg)

The previews are physical-scale 110 mm SVGs. Blue marks the emitted full-width
sweep; amber marks approved artwork left uncut. Neither artifact is authorized
or verified for cutting, and the 30° cutter condition remains unverified.
