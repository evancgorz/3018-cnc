# C-087 hybrid pocket feasibility review

**Result: the 1/8 in endmill cannot safely deep-pocket this artwork as drawn.**
No endmill motion file was emitted. Forcing a 3.175 mm cutter into the source
shapes would cross into retained white areas and alter lettering, counters, and
fine borders. This review does not reduce artwork coverage just to approach the
aspirational 45-minute goal.

## General multi-tool decision rule

For any raster-to-multi-tool job, erode the approved material-removal region by
the round cutter's conservative radius and output-rounding guard. The remaining
region is where that tool's center can travel while its full-diameter sweep stays
inside approved artwork. Use a large flat endmill for broad regions only when
that center region is substantial. Subtract the emitted endmill sweep from the
approved region, then plan the smaller V-bit only on the residual; keep these as
separate single-tool programs with explicit tool identity and a manual tool
change. Verify sweeps from the rounded emitted files, and report deep pocket
coverage separately from shallow detail coverage. C-075's path scheduler is
applicable only when every stay-down connector remains inside the corresponding
eroded region.

## Hawkeye measurement

The unchanged 1254 × 1254 source maps to the existing 90 mm artwork canvas in a
110 × 110 mm frame, with the 100 mm ornament centered at work X55 Y55. The
approved-black work region after the existing 3 mm hanger keepout is
2409.2226 mm². The user-reported 3.25 mm stock and 1.625 mm target depth remain
the evaluation inputs.

The assumed 3.175 mm endmill requires a centerline inset of at least 1.5875 mm;
the conservative rounded sweep inset was empty. The study found only
0.1312 mm² of center-accessible art at a 3.0 mm cutter, 25.5825 mm² at 2.0 mm,
and 215.4249 mm² at 1.5 mm. These are center-accessible areas, not total swept
coverage. A smaller cutter would be a different tool and still leaves most of
the image inaccessible to broad pocketing. No candidate feeds, depths, or
runtime were assigned to the infeasible 3.175 mm option.

## Retained comparison file

The unchanged V-bit-only C-069 full profile is included as a comparison, not a
new release recommendation: [NC file](../c069-flow/01-detail-c069-flow-675-120-review-only.nc),
[report](../c069-flow/c069-flow-report.json), and
[verification](../c069-flow/c069-flow-verification.json). Its exact file parses
to 107,517 commands and 89.85 nominal minutes, with bounds X0–98.9343,
Y0–98.1448, Z−1.625–3.0. Its prior exact-file sweep verification reports full
diameter containment and 23.6029 mm² of approved black area omitted (about
0.98% of the work region). Parser time excludes acceleration, junction
slowdown, and any manual tool change; physical runtime is not established.

The comparison analysis used C-075's exact-file motion metrics. Path ordering
could reduce moves only if it preserves the same artwork-contained geometry;
it cannot make the 3.175 mm endmill fit into shapes narrower than the cutter.
This case therefore rejects the hybrid tool assignment while preserving a
generalizable full-sweep feasibility gate for other artwork and smaller tools.

## Unknowns and limits

- Actual endmill cutting diameter, runout, flute count and flute length are not
  measured. The 3.175 mm value is an assumption based on “1/8 in.”
- Endmill and V-bit feeds, RPM, chip load, stepdown, and stock flatness were not
  validated by a coupon.
- The contrasting-ply boundary is unknown; the 1.625 mm depth may not land at
  the intended visual layer.
- No machine, backend, GUI, or hardware was contacted. Nothing in this bundle is
  a physical readiness approval.
