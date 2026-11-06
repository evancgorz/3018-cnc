# C095 lettering rebuild

Offline design review only; no application, backend, or hardware interaction.

The C095 label arcs are rebuilt at radius 36.8 mm with the original wording. The old text band is cleared only from radii 32.3 to 40.5 mm. The sampled circular borders lie outside that band; the palm and sailboat windows have zero intersection with the cleared geometry.

`clean-design-mask.png` uses black for planned cut geometry and white for retained material. `clean-letter-mask.png` isolates the new letter footprint. `letter-centerlines.csv` contains the standalone XY strokes at Z-0.45 mm. `01-c095-lettering-review-only.nc` combines the unchanged C095 center artwork and preserved border geometry with the new lettering and all depth passes.

The preview is regenerated from rounded emitted G-code at every depth, using the analytic 30 degree / 0.1 mm flat-tip V-bit model. It is a depth model, not a plywood color or surface-finish guarantee. See `report.json` for hashes, cutter width, sweep containment, glyph clearance counts, exact motion metrics, and limitations.
