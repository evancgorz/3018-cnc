# C095 lettering and wider-ray review candidate

Offline design review only; no application, backend, or hardware interaction. The ray revision is not a cutting release.

The C095 label arcs are rebuilt at radius 36.8 mm with the original wording. At 0.45 mm depth, the 30 degree / 0.1 mm flat-tip V-bit cuts a maximum 0.341 mm width. The 0.225 mm square sweep guard leaves the letter counters open. The old text band is cleared only from radii 32.3 to 40.5 mm. The circular border guards, palm, and sailboat have zero overlap with the cleared geometry or letter mask.

The nine sun rays retain C095's centerline directions and radii, with straight-sided wedge widths increasing from 0.8 mm to 3.3 mm, clipped to the existing sky and aircraft keepout. Their editable geometry is in `tapered_rays.py` referenced in `report.json`.

`clean-design-mask.png` uses black for planned cut geometry and white for retained material. `clean-letter-mask.png` isolates the new letter footprint. `letter-centerlines.csv` contains the standalone XY strokes at Z-0.45 mm. `01-c095-lettering-review-only.nc` combines the preserved C095 geometry with the new lettering, wider rays, and all depth passes. It retains concentric clearing except for a strict row-ordered, alternating-direction finish over the water background, where adjacent strategies overlap by 0.6 mm.

The preview is regenerated from rounded emitted G-code at every depth, using the analytic V-bit model. The water/non-water interface residual is marked not assessable because it lies inside the adjacent exterior-edge taper; see `verification.json`. The image is a depth model, not a plywood color or surface-finish guarantee. See `report.json` for hashes, sweep containment, glyph clearance counts, seam overlap, exact motion metrics, and limits.
