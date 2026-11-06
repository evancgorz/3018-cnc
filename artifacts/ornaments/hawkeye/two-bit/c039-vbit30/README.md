# C-039: actual V-bit detail review

Offline review only. No CNC, backend, GUI, spindle, or motion was used.

The approved black-and-white artwork remains the only geometry source. The
reported cutter is a 30-degree included-angle V-bit with a 0.1 mm flat tip.
The angle and tip are treated as user-reported inputs; packaging, runout, and
condition were not independently measured. The cutout remains the separate
endmill operation in the parent `two-bit` folder.

## Coverage-focused candidate

Use [the shallow-fine NC draft](v4-shallow-fine/01-detail-review-vbit30-shallowfine.nc)
with its [JSON report](v4-shallow-fine/detail-report-vbit30-shallowfine.json),
[SVG sweep preview](v4-shallow-fine/detail-preview-vbit30-shallowfine.svg), and
[rendered preview](v4-shallow-fine/detail-preview-vbit30-shallowfine.png).
Blue is the broad fill, amber is the shallow fine pass, and red marks the
hanger-hole reserve. [Independent offline verification](v4-shallow-fine/independent-verification.json)
records the parser, command, coordinate, timing, and hash checks.

The cutter sweep is measured against the thresholded approved black artwork,
not a redraw. The 3 mm hanger reserve removes 4.367 mm². Of the remaining
2,409.223 mm², the two emitted stages sweep 2,368.109 mm² and leave 41.114 mm²
(1.707%) unreachable or intentionally uncut. All emitted cutter envelopes are
inside available approved black, outside the hanger reserve, and inside the
110 × 110 mm stock. The report records exact hashes and parser checks.

The candidate estimates 189.20 minutes with 178,947 G-code lines. It assumes
300 mm/min cutting, 80 mm/min plunging, Z+3 mm XY clearance, a Z+0.2 mm approach,
0.45 mm broad engraving in two passes, and a 0.04 mm fine pass. These settings
are illustrative; the estimate is a straight distance/feed model, not observed
cycle time. Spindle start and tool change are omitted; M5 is present at both
ends.

## Same-tool tradeoff

| Candidate | Fine method | Estimate | Available black omitted |
| --- | --- | ---: | ---: |
| [Residual raster](v3-raster-residual/01-detail-review-vbit30-raster.nc) | 0.08 mm raster residual | 130.74 min | 3.236% |
| [Shallow fine](v4-shallow-fine/01-detail-review-vbit30-shallowfine.nc) | 0.04 mm raster residual | 189.20 min | 1.707% |

The faster same-tool candidate leaves another 36.85 mm² of approved black
uncut. The earlier 182.62-minute draft used a 60-degree / 0.05 mm cutter, so it
is not an apples-to-apples runtime baseline. This run did not find a candidate
that improved both runtime and coverage over the corrected-tool alternatives.

## Rebuild and verification

From the repository root:

```powershell
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c039-vbit30/v4-shallow-fine/prepare-detail-vbit30-shallowfine.py
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c039-vbit30/v4-shallow-fine/render-preview.py
.\.venv\Scripts\python.exe artifacts/ornaments/hawkeye/two-bit/c039-vbit30/v4-shallow-fine/verify-review.py
```

The generator parses the final NC, checks nonnegative XY and Z+3 mm rapid
clearance, verifies initial/final M5 and one M2 with no M3/M6, and checks the
conservative quantized cutter sweep against stock, approved black, and the
hanger reserve. The report marks this as offline review only, not cutting
approval. Actual tool/runout, stock flatness and Z0, feeds/RPM, cutter depth,
fixturing, coupon behavior, and visual detail acceptance remain unverified.
