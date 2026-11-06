# Hawkeye: two separate tool jobs

**Tool update:** The user identified the engraving bit as a Two Trees solid
carbide flat-bottom V-bit, 1/8 in (3.175 mm) shank, 30 degrees / 0.1 mm tip.
The detail files and previews below were generated for a 60-degree, 0.05 mm
tip and do not represent this tool. Regenerate and verify the detail toolpath
and its cutter sweep for the actual bit before any machining. Interpret the
30 degrees as the included angle and 0.1 mm as the flat-tip diameter, subject
to confirmation against the specific packaging or product drawing. The
separate endmill hole/profile draft is unaffected by the V-bit geometry.

This restores the approved detailed artwork. The user withdrew the coarser
single-endmill version. These are **offline review drafts, not cutting releases**.
Both programs deliberately start/finish with spindle stop and contain no spindle
startup. Do not run them by manually starting the spindle first: the initial M5
would stop it. Verified RPM and cutting settings must be added for a cutting
release after reviewing the physical setup.

| Order | File | Tool and work | Nominal motion estimate |
| --- | --- | --- | ---: |
| 1 | `01-detail-review.nc` | Assumed 60-degree V-bit with 0.05 mm tip; broad shallow clearing to 0.45 mm and fine residual artwork to 0.08 mm | 182.62 minutes |
| 2 | `02-cutout-review.nc` | Assumed 3.175 mm endmill; 4 mm hanging hole, then 100 mm outside profile with four tabs | 8.71 minutes |

Estimates parse the actual combined programs, assume 3,000 mm/min rapid moves,
and omit acceleration, controller throughput, spindle startup and tool changes.
The detail draft has about 258,000 lines and remains too slow for a practical
production workflow; vector/centerline and redundant-path optimization remain
planned work. The 7 MB detail draft has not been loaded into Pine.

## Coordinates and material

- Both use millimeters, absolute work coordinates and the same lower-left
  origin for a hypothetical 110 x 110 mm stock/work area.
- Part center: X55 Y55. Outside diameter: 100 mm. Artwork canvas: 90 mm.
- Hanging hole: X55 Y100, diameter 4 mm, nominal 3 mm rim web. The detail file
  reserves a 3 mm radius around it, trimming the top outer engraved ring.
- Nominal plywood thickness: 3 mm. Profile ends at Z-3.15 with seven 0.45 mm
  depth passes; tab re-entry descents are split to no more than 0.5 mm.
- Four tabs: 4 mm nominal width, 0.8 mm retained height. All hole passes finish
  before any outside-profile pass.
- Z0 means material top. All rapid XY transfers use Z+3. The detail program
  additionally assumes a +0.2 mm vertical approach clearance, requiring verified
  stock flatness and clear start points.

## Manual operation sequence, once released

Home the machine and establish the shared stock XY origin and material-top Z0.
Run the reviewed detail job with the V-bit. Raise the tool far enough to change
bits and place the puck; change to the endmill while preserving the stock and XY
work zero. Probe only Z using the known puck and its measured thickness, remove
the puck/clip, and complete the probe dialog. Review the second file and then run
the hole/profile job. There is no automatic tool change or automatic second-job
start. These instructions do not authorize machine motion by the agent.

## Review evidence and unresolved inputs

`detail-preview.svg`/`.png` show actual top-surface cutter sweeps: blue broad
clearing, amber finer detail. About 1% of available black artwork remains uncut;
the hanger reserve removes another 4.37 mm² near the top outer ring. These
previews do not predict floor scalloping, plywood veneer tear-out or real Z error.
`cutout-preview.svg`/`.png` show the separate profile/hole geometry.

Reports record source and artifact hashes, programmed depths, source coverage,
same-coordinate placement, parser acceptance, rapid clearance, cutter bounds,
profile stepdown and nominal timing. Rebuild with `prepare-detail.py` and
`prepare-cutout.py`; the latter reuses analytic geometry helpers from the retained
single-bit experiment, not that experiment's artwork.

Before a cutting release, confirm the V-bit tip/angle and runout, endmill cutting
diameter/flute length, measured material thickness/flatness, spindle RPM, feeds,
pass depths, fixturing/spoilboard clearance, and coupon results. No physical cut,
probe or jog was performed to validate these files.
