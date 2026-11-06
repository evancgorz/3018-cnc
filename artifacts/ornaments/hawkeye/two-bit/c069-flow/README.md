# C-069: F675 controller-flow candidate

Status: offline review only. No file was loaded or sent to the machine.

## Recommended candidate

`01-detail-c069-flow-675-120-review-only.nc` changes C-058's cutting feed from
F450 to F675 and leaves plunge at F120. Its XY path, Z levels, and operation
sequence match C-058 exactly; the only text differences are the cutting-feed
words and a descriptive comment. This was checked against the C-058 file.

- SHA-256: `f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b`
- Generator: `prepare-c069-flow.py`
- Generator command: `\.venv\Scripts\python.exe artifacts\ornaments\hawkeye\two-bit\c069-flow\prepare-c069-flow.py`
- Report and verification: `c069-flow-report.json`, `c069-flow-verification.json`

The parsed program retains the three broad passes at Z-0.6, Z-1.2, and
Z-1.625 mm, plus fine detail at Z-0.04 mm. Safe Z remains 3.0 mm and vertical
approach remains 0.2 mm. Spindle command remains S1000; terminal commands are
M5/M2, with no tool change. All coordinates and sweeps are within the 110 mm
stock, and the hanger keepout remains excluded.

## Geometry and motion comparison

| Candidate | XY segments | Median segment | Junctions >=90 degrees | Approved artwork omitted | Nominal estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| C-057 F450 source | 158,857 | 0.0718 mm | 121,605 | 16.4264 mm² | — |
| C-058 geometry, F450 | 88,676 | 0.1435 mm | 75,136 | 23.6029 mm² | 115.04 min |
| C-069 same geometry, F675 | 88,676 | 0.1435 mm | 75,136 | 23.6029 mm² | 89.85 min |
| Broad tolerance 0.15 mm, F675 | 86,075 | 0.1435 mm | 74,680 | 26.6328 mm² | 89.71 min |

The recommended candidate preserves C-058's full-diameter cutter sweep and
omission exactly while increasing commanded cutting feed by 50%. Its parser-based
estimate is 21.9% shorter than the C-058 F450 estimate, because plunges,
rapids, and other time do not scale with cutting feed. These are nominal
feed-based estimates; acceleration, corner slowdown, and real machine throughput
are not modeled.

A separate 0.15 mm broad-chord trial kept the fine tolerance at 0.04 mm and
also passed the parser, depth, and full-diameter containment checks. It removed
only 2,601 more XY segments (2.9% relative to C-058), did not improve the median
segment length, and omitted another 3.0299 mm² of approved artwork. Its
verification marks it review-required because total added omission exceeds the
previous 10 mm² limit. It is retained only to document the tradeoff.

Both geometry candidates use the same modeled 30-degree included-angle V-bit
with 0.1 mm tip, 110 mm stock frame, and artwork/keepout inputs as C-058. Those
are nominal assumptions; actual cutter/runout and ply boundary are unverified.
The geometry verification establishes containment in the model, not physical
readiness.

## Reproduction and evidence

Run the selected candidate generator from the repository root. Each generator writes its own
G-code, JSON report, and verification file. The emitted G-code is parsed and
checked for nonnegative work XY, safe-Z rapid travel, expected depths and broad
passes, and one M3 followed by M5/M2 with no M6.
The sweep uses the source artwork region with the hanger keepout removed and a
conservative radius slightly larger than half the modeled full cutter diameter.

Reference C-058 artifact:
`../c043-runtime/c058-controller-efficient/01-detail-controller-efficient-450-120-review-only.nc`

## Targeted opening-boundary smoothing experiment

The same F675 candidate was also generated with a guarded local smoothing pass on
only the first broad path. Each vertex moved toward its neighboring midpoint
only when both adjacent full-diameter cutter sweeps stayed inside the approved
artwork; endpoints remain fixed. A 0.02 mm guarded RDP pass then simplified the
rounded path. The other 348 broad paths and every fine-detail path remain the
same as C-058.

- Candidate: `01-detail-c069-first-boundary-675-120-review-only.nc`
- SHA-256: `bef0b50e8b65cd1008854b701d500b508b5ae7334267454786f6aae31372b9a8`
- Generator/report/verification: `prepare-c069-first-boundary.py`,
  `c069-first-boundary-report.json`, `c069-first-boundary-verification.json`,
  `c069-first-boundary-comparison.json`
- Opening path: 665 to 463 XY segments; >=90 degree turns 138 to 54.
- Whole file: 88,676 to 88,070 XY segments; >=90 degree junctions 75,136 to
  74,884. Median remains 0.1435 mm.
- Approved-black omission: 24.5153 mm², which is 0.9124 mm² more than C-058 and
  8.0889 mm² more than C-057. Full-diameter containment, stock bounds, hanger
  keepout, depths, and safe rapid clearance pass.
- Nominal estimate: 89.61 minutes, excluding acceleration and corner slowdown.

This option reduces motion specifically on the opening boundary that caused
operator-visible hesitation, while retaining nearly all of C-058's coverage.
It remains review-only until the primary agent reviews the file and current
physical-operation request.

## Rejected geometry trials

The 0.15 mm broad-tolerance candidate is retained with a review-required
verification: it saves only 2.9% of C-058's XY segments, does not change median
segment length, and adds 3.0299 mm² of omitted artwork versus C-058.

The all-broad local-smoothing experiment reduced >=90 degree junctions by
11.3% and safely contained every modeled cutter disk, but omitted 60.4610 mm²
more than C-057 (53.2845 mm² more than C-058). It is not recommended. Its
separate file is retained as `01-detail-c069-smoothed-675-120-review-only.nc`
for review of why smoothing all paths loses coverage; summary evidence is in
`c069-smoothed-rejection.json`.
