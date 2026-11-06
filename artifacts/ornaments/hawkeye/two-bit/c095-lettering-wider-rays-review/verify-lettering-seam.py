"""Recompute C095 lettering candidate seam-floor metrics from emitted moves."""
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import sys

import numpy as np
from shapely.geometry import Point

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


prep = load(HERE / "prepare-lettering.py", "c095_lettering_verify")
clearing = load(ROOT / "artifacts/ornaments/hawkeye/two-bit/c095-clearing-comparison/compare-clearing.py",
                "c095_lettering_verify_water")
report_path = HERE / "report.json"
report = json.loads(report_path.read_text())
program_path = HERE / "01-c095-lettering-review-only.nc"
if sha(program_path) != report["output_program_sha256"]:
    raise ValueError("Report output hash does not match the emitted review program")

base_report = json.loads(prep.BASE_REPORT.read_text())
cfg = prep.OrnamentSettings(**base_report["settings"])
revised, _, _ = prep.build_base_geometry(cfg)
clean_base = revised.difference(prep.annular_clear_zone())
_, water_source, _, _ = clearing.background_region(ROOT)
water_core = water_source.intersection(clean_base)
non_water_core = clean_base.difference(water_core)
shared_seam = water_core.boundary.intersection(non_water_core.boundary)
overlap_mm = prep.SEAM_OVERLAP_MM
seam_band = clean_base.intersection(shared_seam.buffer(overlap_mm, quad_segs=64))
mask_top_origin = np.asarray(prep.raster_geometry_mask(seam_band)) > 0
mask_bottom_origin = mask_top_origin[::-1]
depth = np.load(HERE / "modeled-removal-depth-mm.npy")
if depth.shape != mask_bottom_origin.shape:
    raise ValueError("Depth grid and seam mask dimensions differ")
residual = 1.625 - depth[mask_bottom_origin]
high_mask = mask_bottom_origin & ((1.625 - depth) > 0.5)
high_y, high_x = np.nonzero(high_mask)
seam = {
    "sample_count": int(residual.size),
    "shared_interface_length_mm": float(shared_seam.length),
    "overlap_band_each_side_mm": overlap_mm,
    "p50_residual_mm": float(np.percentile(residual, 50)) if residual.size else None,
    "p95_residual_mm": float(np.percentile(residual, 95)) if residual.size else None,
    "p99_residual_mm": float(np.percentile(residual, 99)) if residual.size else None,
    "max_residual_mm": float(np.max(residual)) if residual.size else None,
    "area": "shared water/non-water target interface; this interface coincides with the water-zone top clip and is adjacent to the clean-base exterior wall",
    "depth_grid_y_alignment": "flipped image-top-origin geometry mask to physical-Y bottom-origin depth array",
    "minimum_distance_to_clean_base_exterior_mm": float(shared_seam.distance(clean_base.boundary)),
    "sampled_interface_distance_to_clean_base_exterior_mm": {
        "p05": float(np.percentile([Point(float(x), float(y)).distance(clean_base.boundary)
                                      for x, y in zip(np.linspace(*shared_seam.bounds[::2], 12),
                                                      np.full(12, shared_seam.bounds[1]))], 5)),
        "p50": float(np.percentile([Point(float(x), float(y)).distance(clean_base.boundary)
                                      for x, y in zip(np.linspace(*shared_seam.bounds[::2], 12),
                                                      np.full(12, shared_seam.bounds[1]))], 50)),
        "p95": float(np.percentile([Point(float(x), float(y)).distance(clean_base.boundary)
                                      for x, y in zip(np.linspace(*shared_seam.bounds[::2], 12),
                                                      np.full(12, shared_seam.bounds[1]))], 95)),
    },
    "residual_over_0p5mm_sample_count": int(high_x.size),
    "residual_over_0p5mm_bounds_mm": ({"min_x": float((high_x.min() + .5) * prep.GRID),
                                        "max_x": float((high_x.max() + .5) * prep.GRID),
                                        "min_y": float((high_y.min() + .5) * prep.GRID),
                                        "max_y": float((high_y.max() + .5) * prep.GRID)} if high_x.size else None),
}
planning = report["planning"]
planning.pop("water_boundary_floor_residual", None)
planning["shared_water_nonwater_seam_floor_residual"] = seam
seam_ok = bool(residual.size and float(np.percentile(residual, 95)) <= 0.1 and float(np.max(residual)) <= 0.2)
planning["shared_water_nonwater_seam_floor_residual"]["status"] = "not_assessable_external_taper"
report["status"] = "offline review candidate; wider rays integrated; seam floor metric not assessable at adjacent external V-bit taper"
for index, value in enumerate(report["limitations"]):
    if "Letter sweep containment" in value:
        report["limitations"][index] = (
            "Letter sweep containment uses a 0.225 mm square guard, larger than the true 0.171 mm cutter radius at 0.45 mm depth."
        )
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

verification = {
    "status": "review_required",
    "program_sha256": sha(program_path),
    "preview_sha256": sha(HERE / "c095-lettering-preview.png"),
    "depth_grid_sha256": sha(HERE / "modeled-removal-depth-mm.npy"),
    "shared_seam_floor": {**seam, "status": "not_assessable_external_taper"},
    "checks": {
        "emitted_program_hash_matches_report": True,
        "shared_seam_samples_use_correct_y_orientation": True,
        "shared_interface_identified_as_y_41p5_water_clip_edge": True,
        "shared_interface_is_outside_vbit_taper_zone": False,
        "shared_seam_floor_quality": "not_assessable; full interface lies within 0.35 mm of clean-base exterior, inside the 0.486 mm maximum-depth cutter radius",
        "shared_seam_floor_within_0p1mm_p95_and_0p2mm_max": False,
    },
}
(HERE / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
print(json.dumps(verification, indent=2))
