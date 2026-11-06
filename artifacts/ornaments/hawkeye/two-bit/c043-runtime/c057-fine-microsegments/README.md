# C-057 fine-pass microsegment candidate

Offline review artifact derived from the C-043 v6 detail program and its
450/120 mm/min speed candidate. It changes only the fine-pass XY centerlines;
the broad paths, depth passes, spindle commands, and feeds are retained.

The fine pass uses the modeled full effective cutter diameter of 0.1214359354
mm at Z−0.04 mm. The emitted full-diameter sweep was compared against the speed
candidate's sweep. The fine sweep symmetric difference is 0.619905 mm² (0.079%
of its 785.398 mm² baseline sweep), and the combined approved-black omitted
area changes by 0.0000065 mm². Every conservative full-diameter sweep remains
inside the approved artwork, outside the hanger keepout, and within stock.

| Fine-pass XY moves | Reduction | NC estimate |
| ---: | ---: | ---: |
| 179,945 → 105,457 | 41.4% | 118.181 → 118.179 min |

The parser estimate is based on path distance and programmed feed, so it does
not estimate the possible throughput effect of fewer short segments. It is not
an observed machine cycle time. This file is for offline review only and is
not verified or authorized for cutting.

Rebuild and rerun the geometry checks from the repository root:

```powershell
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/c057-fine-microsegments/optimize-fine-pass.py
```

The exact candidate NC hash, source hashes, sweep comparison, parsed bounds,
feeds, and machine commands are recorded in the adjacent JSON report and
verification files.
