# C095 background clearing comparison

This is an offline analysis of the broad raised-ripple water background in
C095. It compares C095-style concentric clearing, endpoint-optimized alternating
scanlines, and strict row-ordered alternating scanlines for the same region and
0.12 mm final stepover. All variants share C095's 0.27 mm concentric roughing
at Z-0.6 and Z-1.2, followed by the compared final clearing at Z-1.625. The
assumed cutter is the 30-degree included-angle, 0.1 mm flat-tip V-bit from C095.

`compare-clearing.py` reconstructs the C095 water region from its source mask,
plans both paths, checks each in-memory program with the repository parser, and
computes an analytic V-bit removal surface on a 0.0125 mm grid. It writes
`comparison.json`, `floor-comparison.png`, and `manifest.json`. No CNC file is
written. The preview shows modeled floor height; it does not predict grain,
runout, flex, chip recutting, or plywood color.

The strict variant schedules scanline spans in increasing row order and
alternates direction by row. Six boundary/counter rings run separately before
the raster fill. It links only successive spans on the same or immediately
adjacent row when the full cutter disk along the connector is contained in the
target region; 137 links passed, and 96 unsafe transitions retract. Every ring,
span, and linked connector is checked with the same inflated full-cutter sweep
used for the other variants. It does not reorder or reverse spans to shorten
travel; row order and span direction are reported separately in the JSON.

At the analyzed 0.12 mm spacing, the ideal straight-lane cusp is 0.0373 mm. In
the 495.4 mm² flat-core sample, strict row order had a 0.0263 mm P95 residual
above the target floor; all samples were within 0.05 mm, with a sampled maximum
of 0.0356 mm. Endpoint-optimized scanlines also had a 0.0263 mm P95 residual,
99.975% within 0.05 mm, and a 0.0543 mm sampled maximum. Concentric paths had a
0.0305 mm P95 residual, 98.411% within 0.05 mm, and a small localized region
at 0.311 mm residual.

Strict row order used 4,730 mm of final XY cut and took 16.01 nominal minutes
for the analyzed rough-plus-final moves. Endpoint-optimized scanlines used
4,795 mm and 14.96 minutes; concentric used 4,583 mm and 13.68 minutes. The
strict variant parsed to 6,590 commands, 123 retracts, and 1,826 mm rapid XY;
the optimized raster had 6,467 commands, 85 retracts, and 412 mm rapid XY.
Strict row order therefore preserves the requested back-and-forth sequence and
modeled floor uniformity at about 7% more nominal time than endpoint-optimized
scanlines in this region. These are feed-based estimates, not observed machine
times.

All nominal times include commanded feed, plunge, rapid, and dwell moves from
the parsed comparison programs, but exclude acceleration and junction slowing.

The remaining 0.557 mm² strict-scanline sweep gap is measured against the
conservative full-diameter top-surface footprint, not a missing flat floor.
The model assumes tool geometry and does not establish physical finish or
readiness.
