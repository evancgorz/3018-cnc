# C-043 Hawkeye 30° V-bit runtime candidate

Offline review only. This work used the approved artwork and reported 30° /
0.1 mm V-bit; it did not interact with the controller or a running application.
The source image, 90 mm artwork placement, 100 mm disc, 110 mm stock frame,
hanger reserve, final depths, feed assumptions, and measured cutter-sweep checks
are unchanged from the C-039 v4 reference.

## Candidate

Use the files in `v4-single-pass-1000rpm` for review:

- `01-detail-review-vbit30-1000rpm.nc`
- `detail-report-vbit30-1000rpm.json`
- `detail-preview-vbit30-1000rpm.svg` and `.png`
- `independent-verification.json`

The broad stage uses one pass to Z−0.45 mm. This removes the previous complete
Z−0.25 mm raster pass; it does not change the broad stage's final tool sweep.
Broad and fine raster stepovers are 0.27 mm and 0.097 mm, each within the
exporter's 80% effective-diameter limit. The residual-only fine pass remains at
Z−0.04 mm. The explicit spindle command is `M3 S1000`, followed at safe Z by
`G4 P2.000`; 1000 RPM was previously successful per the user, while the two
second dwell is an unverified assumption.

| Review candidate | Estimated engraving time | Lines | Available approved black omitted |
| --- | ---: | ---: | ---: |
| C-039 v4 shallow-fine | 189.197 min | 178,947 | 1.7065% |
| C-043 single-pass, wide-step, 1000 RPM | 122.818 min | 131,973 | 1.7064% |

The estimate saves 66.379 minutes (35.1%) under the same 300 mm/min cut and
80 mm/min plunge assumptions. It comes from the wider legal raster spacing and
one broad pass to final depth. It is a linear feed-distance estimate plus the
two-second dwell, not observed cycle time.

The single 0.45 mm broad-stage stepdown has not been validated for the actual
bit, machine, material, or workholding. This NC is not authorized for cutting.
The dwell duration is also not validated. The file remains a review candidate;
actual tool runout, stock flatness/Z0, feeds, depth limits, fixturing, and coupon
behavior still require operator review.

## Verification

From the repository root:

```powershell
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v4-single-pass-1000rpm/prepare-detail-vbit30-1000rpm.py
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v4-single-pass-1000rpm/render-preview.py
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v4-single-pass-1000rpm/verify-review.py
```

Verification passed for G-code parse, nonnegative work XY, 3 mm XY rapid
clearance, exact final-program estimate, source/G-code/preview hashes, one
`M3 S1000`, one parsed dwell, two `M5`, no `M6`, one `M2`, containment of the
conservative quantized sweeps in the approved black art and stock, and the
hanger keepout. The rendered SVG was visually inspected against the approved
artwork.

## Experiments

`v1-wide-step` tests wider raster spacing alone: 177.438 min and 1.7064% omitted.
`v2-simplified` tests 0.02 mm compensated-path simplification: 177.817 min and
1.924% omitted, so it is not the recommended candidate. The final `v4` bundle
retains its own reproducible generator and validation scripts.
