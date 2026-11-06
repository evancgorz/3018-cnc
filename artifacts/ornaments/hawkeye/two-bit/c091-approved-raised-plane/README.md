# Approved raised-aircraft concept: offline CAM

`prepare.py` converts the actual approved generated concept into a binary
negative-relief mask at luminance 130. It does not invent aircraft polygons.
White mask pixels retain the top ply; dark regions receive concentric local
clearing to 1.625 mm where the final-width V-bit fits. The residual fine artwork
receives a separate 0.04 mm pass. Hanger clearance is reserved around (55,100).

Inputs: 30° / 0.1 mm V-bit, 3.25 mm stock, 100 mm disc centered at (55,55),
110 mm stock coordinates; S1000; F675 cutting / F120 plunge; broad levels
−0.6, −1.2, −1.625 mm; 3 mm XY rapid clearance; 0.2 mm vertical approach.

The concept image is mapped at 99 mm across its padded square, leaving a wood
margin. That mapping differs from the earlier 90 mm art canvas, so existing
test cuts cannot be cosmetically repaired by this sequence. Primary operator
has explicit user permission to test on the existing cut piece.

`report.json` binds source/mask/G-code hashes, settings, concentric component
counts, exact parsed motion analysis and cutter-inaccessible area. The image
`exact-depth-preview.svg` is drawn from cutter sweeps: dark brown = deep area,
ochre = fine surface detail and red = inaccessible residual. This is a depth
preview, not a promise of plywood color or a material-removal simulation.

Broad clearing is entirely component-local, with nearest-next component order
and full-width-contained stay-down links. Both broad and fine paths use the
existing guarded chord simplifier to remove pixel stair steps. Parser checks
nonnegative XY and safe-Z rapids; every rounded path's full cutter footprint is
contained in the thresholded dark source geometry and outside hanger reserve.

Regenerate with `.venv/Scripts/python.exe artifacts/ornaments/hawkeye/two-bit/c091-approved-raised-plane/prepare.py`.
Primary owns independent review and all physical machine actions.
