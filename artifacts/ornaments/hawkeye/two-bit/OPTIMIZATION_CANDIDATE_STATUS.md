# Detail optimization candidate status

The public `01-detail-review.nc`, `detail-report.json`, `detail-preview.svg` and
`detail-preview.png` remain the C-031 offline review bundle. The candidate files
are separate and are not approved for use.

## Candidate method

`prepare-detail-optimized-candidate.py` keeps the C-031 broad V-bit fill and
replaces its 11,716 residual raster chains with medial-axis paths. It thins the
residual at twice the source image resolution, maps the assumed 60-degree
V-bit depth from exact distance to the original approved-black boundary, and
limits each depth step to 0.25 mm. A conservative sweep of the emitted variable
XY/Z moves must stay inside the approved black artwork and outside the hanger
keepout before the NC file is written.

The generated `01-detail-review-optimized-candidate.nc` passed that geometric
containment gate. The script then failed while saving its SVG preview with a
Windows `OSError: [Errno 22] Invalid argument`; the script has since been
isolated to write candidate-specific output names. Its report and preview have
not been generated, and the candidate's full source-coverage percentage has not
been measured. Keep the C-031 bundle as the active review artifact until those
checks are complete.

## Remaining verification

1. Rebuild with `prepare-detail-optimized-candidate.py`; confirm it creates only
   candidate-named outputs and that the preview write succeeds.
2. Parse the candidate NC and verify nonnegative XY, XY rapid clearance at Z3,
   initial/final M5, no M3/M4/M6, one M2, and exact artifact hashes.
3. Recompute combined broad-plus-detail cutter sweep against the approved source
   and hanger keepout. Compare omitted black area against C-031's 0.9993%; review
   any material loss before considering promotion.
4. Inspect the candidate preview visually and review runtime assumptions. The
   300 mm/min feed, 80 mm/min plunge, 3,000 mm/min rapid, 0.05 mm tip and stock
   assumptions remain unverified. No machine, GUI, or hardware work is included.
