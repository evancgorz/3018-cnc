"""Offline comparison of C095's concentric and alternating-raster water clearing.

This writes only analysis evidence. It does not emit a loadable CNC program.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
from shapely.affinity import scale
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))

from ttc3018_control.ornament_cam import (
    OrnamentSettings,
    _lines,
    _component_scanline_paths,
    _polygons,
    _rounded_ring_paths,
    _schedule_engraving_paths,
    plan_adaptive_region_engraving,
    raster_region,
)
from ttc3018_control.gcode import (
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)
from ttc3018_control.job_analysis import analyze_program


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def background_region(root: Path):
    """Rebuild C095's exact raised-ripple water field from its generator."""
    c095_dir = root / "artifacts/ornaments/hawkeye/two-bit/c095-cutter-faithful-redesign"
    c091_dir = root / "artifacts/ornaments/hawkeye/two-bit/c091-approved-raised-plane"
    baseline = json.loads((c095_dir / "report.json").read_text())
    cfg = OrnamentSettings(**baseline["settings"])
    original, _ = raster_region(c091_dir / "approved-depth-mask.png", cfg)
    original = original.difference(Point(55, 100).buffer(3, quad_segs=128))
    inner = Point(55, 55).buffer(32.0, quad_segs=256)
    water_zone = inner.intersection(box(22, 24, 88, 41.5))
    ripples = []
    for x, y, length, height in (
        (47, 39, 22, 1.25), (66, 36.2, 14, 1.4), (42, 33.4, 17, 1.35),
        (61, 30.5, 18, 1.3), (48, 27.7, 12, 1.35),
    ):
        ripples.append(scale(Point(x, y).buffer(1, quad_segs=64),
                             xfact=length / 2, yfact=height / 2))
    raised_water = unary_union(ripples).intersection(water_zone)
    # C095 unions all of water_zone into the revised dark mask, then removes
    # its five raised ripples. Thus this polygon is the exact deep background.
    region = water_zone.difference(raised_water)
    return cfg, region, c095_dir, c091_dir


def scanline_paths(inset, cfg):
    """Use alternating scanlines within each compensated connected component."""
    remaining = list(_polygons(inset))
    current = Point(0, 0)
    paths = []
    details = []
    while remaining:
        index, component = min(
            enumerate(remaining),
            key=lambda item: (item[1].distance(current), item[1].bounds, item[0]),
        )
        del remaining[index]
        primitives = _component_scanline_paths(component, cfg)
        scheduled, metrics = _schedule_engraving_paths(primitives, component, cfg)
        paths.extend(scheduled)
        details.append(metrics)
        current = Point(scheduled[-1][-1])
    return tuple(paths), details


def strict_row_scanline_paths(component, cfg, target_region, verification_radius):
    """Preserve increasing row order and alternate each row's travel direction.

    A stay-down link is allowed only to the next span in the same row or the
    immediately following row, and only when the complete cutter disk swept by
    the connector is contained in the target region. Unsafe transitions remain
    separate paths and become retract/rapid/plunge moves in the analysis G-code.
    """
    minx, miny, maxx, maxy = component.bounds
    rows = math.ceil((maxy - miny) / cfg.stepover)
    # Boundary and counter rings are a separate lead-in stage for edge
    # coverage. The scanline fill itself remains strictly row ordered.
    boundary_paths = _rounded_ring_paths(component)
    chains = [list(path) for path in boundary_paths]
    previous = None
    primitive_count = 0
    stay_down_links = 0
    unsafe_transitions = 0
    same_row_links = 0
    adjacent_row_links = 0
    forward_x_spans = 0
    reverse_x_spans = 0
    y_order = []
    for row in range(rows + 1):
        y = miny + row * cfg.stepover
        if y > maxy:
            break
        spans = sorted(
            _lines(component.intersection(LineString(((minx - 1, y), (maxx + 1, y))))),
            key=lambda line: line.bounds[0],
        )
        if row % 2:
            spans.reverse()
        for span in spans:
            coords = tuple((round(x, 4), round(yy, 4)) for x, yy in span.coords)
            if len(coords) < 2 or span.length < 0.0002:
                continue
            if row % 2:
                coords = coords[::-1]
                reverse_x_spans += 1
            else:
                forward_x_spans += 1
            primitive_count += 1
            y_order.append(row)
            start = coords[0]
            link_ok = False
            if previous is not None:
                old_row, old_end = previous
                row_gap = row - old_row
                if row_gap in (0, 1):
                    connector = LineString((old_end, start))
                    footprint = connector.buffer(verification_radius, quad_segs=32)
                    link_ok = target_region.covers(footprint)
                if link_ok:
                    stay_down_links += 1
                    if row_gap == 0:
                        same_row_links += 1
                    else:
                        adjacent_row_links += 1
                    if chains[-1][-1] == start:
                        chains[-1].extend(coords[1:])
                    else:
                        chains[-1].extend(coords)
                else:
                    unsafe_transitions += 1
                    chains.append(list(coords))
            else:
                chains.append(list(coords))
            previous = (row, coords[-1])
    if y_order != sorted(y_order):
        raise AssertionError("Strict scanline traversal left increasing row order")
    scheduled = tuple(tuple(chain) for chain in chains)
    return scheduled, {
        "primitive_scanline_spans": primitive_count,
        "scheduled_chains_per_pass": len(scheduled),
        "separate_boundary_rings": len(boundary_paths),
        "safe_stay_down_links": stay_down_links,
        "safe_same_row_links": same_row_links,
        "safe_adjacent_row_links": adjacent_row_links,
        "unsafe_transitions_retracted": unsafe_transitions,
        "rows_in_strict_increasing_order": True,
        "row_order_violations": 0,
        "scanline_direction_uses_row_parity": True,
        "scanline_spans_forward_x": forward_x_spans,
        "scanline_spans_reverse_x": reverse_x_spans,
        "scheduler_reversed_or_reordered_spans": False,
        "max_linked_row_gap": 1,
    }


def sweeps(paths, radius):
    return unary_union(
        [LineString(path).buffer(radius, quad_segs=32)
         for path in paths if len(path) >= 2]
    )


def floor_profile(paths, region, depth, angle_deg, tip_mm, grid_mm=0.0125):
    """Analytic continuous-segment V-bit removal on a regular grid."""
    minx, miny, maxx, maxy = region.bounds
    nx = math.ceil((maxx - minx) / grid_mm)
    ny = math.ceil((maxy - miny) / grid_mm)
    xs = minx + (np.arange(nx, dtype=np.float32) + 0.5) * grid_mm
    ys = miny + (np.arange(ny, dtype=np.float32) + 0.5) * grid_mm
    removal = np.zeros((ny, nx), dtype=np.float32)
    tangent = math.tan(math.radians(angle_deg / 2))
    radius = tip_mm / 2 + depth * tangent
    for path in paths:
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            left = max(0, int(math.floor((min(ax, bx) - radius - minx) / grid_mm)))
            right = min(nx, int(math.ceil((max(ax, bx) + radius - minx) / grid_mm)) + 1)
            bottom = max(0, int(math.floor((min(ay, by) - radius - miny) / grid_mm)))
            top = min(ny, int(math.ceil((max(ay, by) + radius - miny) / grid_mm)) + 1)
            if left >= right or bottom >= top:
                continue
            xx = xs[left:right]
            yy = ys[bottom:top]
            dx, dy = bx - ax, by - ay
            denominator = dx * dx + dy * dy
            if denominator:
                t = np.clip(((xx[None, :] - ax) * dx + (yy[:, None] - ay) * dy) / denominator, 0, 1)
                distance = np.sqrt((xx[None, :] - ax - t * dx) ** 2 + (yy[:, None] - ay - t * dy) ** 2)
            else:
                distance = np.sqrt((xx[None, :] - ax) ** 2 + (yy[:, None] - ay) ** 2)
            cut_depth = np.maximum(0, depth - np.maximum(0, distance - tip_mm / 2) / tangent)
            target = removal[bottom:top, left:right]
            np.maximum(target, cut_depth, out=target)

    # Exclude the intended sloped walls: floor roughness is evaluated only
    # where a full-depth, constant-Z V cutter can fit with margin.
    flat_core = region.buffer(-(tip_mm / 2 + depth * tangent + 0.1), join_style="mitre")
    image = Image.new("1", (nx, ny), 0)
    draw = ImageDraw.Draw(image)
    for polygon in _polygons(flat_core):
        for ring_index, ring in enumerate((polygon.exterior, *polygon.interiors)):
            points = [(round((x - minx) / grid_mm), round((maxy - y) / grid_mm))
                      for x, y in ring.coords]
            draw.polygon(points, fill=1 if ring_index == 0 else 0)
    inside = np.asarray(image, dtype=bool)[::-1]
    residual = depth - removal
    values = residual[inside]
    if not values.size:
        raise ValueError("No floor samples remain after excluding boundary walls")
    percentiles = np.percentile(values, [50, 90, 95, 99, 100])
    flat_residual = np.where(inside, residual, -1.0)
    max_row, max_column = np.unravel_index(np.argmax(flat_residual), flat_residual.shape)
    return {
        "grid_mm": grid_mm,
        "flat_core_sample_count": int(values.size),
        "flat_core_area_approx_mm2": float(values.size * grid_mm * grid_mm),
        "residual_above_target_depth_mm": {
            "mean": float(values.mean()), "median": float(percentiles[0]),
            "p90": float(percentiles[1]), "p95": float(percentiles[2]),
            "p99": float(percentiles[3]), "max": float(percentiles[4]),
        },
        "max_residual_location_mm": [float(xs[max_column]), float(ys[max_row])],
        "flat_core_within_0p05mm_percent": float(np.mean(values <= 0.05) * 100),
        "flat_core_within_0p075mm_percent": float(np.mean(values <= 0.075) * 100),
    }


def render_floor(path_groups, region, depth, angle, tip, grid_mm, output_path):
    """Save one modeled floor-depth panel for each toolpath strategy."""
    minx, miny, maxx, maxy = region.bounds
    nx = max(1, math.ceil((maxx - minx) / grid_mm))
    ny = max(1, math.ceil((maxy - miny) / grid_mm))
    images = []
    for candidate, label in path_groups:
        xs = minx + (np.arange(nx, dtype=np.float32) + 0.5) * grid_mm
        ys = miny + (np.arange(ny, dtype=np.float32) + 0.5) * grid_mm
        removal = np.zeros((ny, nx), dtype=np.float32)
        tangent = math.tan(math.radians(angle / 2))
        radius = tip / 2 + depth * tangent
        for path in candidate:
            for (ax, ay), (bx, by) in zip(path, path[1:]):
                left = max(0, int(math.floor((min(ax, bx) - radius - minx) / grid_mm)))
                right = min(nx, int(math.ceil((max(ax, bx) + radius - minx) / grid_mm)) + 1)
                bottom = max(0, int(math.floor((min(ay, by) - radius - miny) / grid_mm)))
                top = min(ny, int(math.ceil((max(ay, by) + radius - miny) / grid_mm)) + 1)
                if left >= right or bottom >= top:
                    continue
                xx, yy = xs[left:right], ys[bottom:top]
                dx, dy = bx - ax, by - ay
                denominator = dx * dx + dy * dy
                if denominator:
                    t = np.clip(((xx[None, :] - ax) * dx + (yy[:, None] - ay) * dy) / denominator, 0, 1)
                    dist = np.sqrt((xx[None, :] - ax - t * dx) ** 2 + (yy[:, None] - ay - t * dy) ** 2)
                else:
                    dist = np.sqrt((xx[None, :] - ax) ** 2 + (yy[:, None] - ay) ** 2)
                cut_depth = np.maximum(0, depth - np.maximum(0, dist - tip / 2) / tangent)
                np.maximum(removal[bottom:top, left:right], cut_depth,
                           out=removal[bottom:top, left:right])
        # Pale means near the untouched top; dark means near target floor.
        fraction = np.clip(removal / depth, 0, 1)
        pixels = (255 - fraction * 180).astype(np.uint8)
        image = Image.fromarray(pixels[::-1]).convert("L").resize((1200, 350), Image.Resampling.LANCZOS)
        images.append((image, label))
    combined = Image.new("RGB", (1200, 350 * len(images)), "white")
    draw = ImageDraw.Draw(combined)
    for index, (image, label) in enumerate(images):
        top = 350 * index
        combined.paste(image.convert("RGB"), (0, top))
        draw.text((12, top + 10), label, fill="red")
    combined.save(output_path)


def emit_program(helpers, rough, finish, cfg):
    lines = ["; OFFLINE COMPARISON ONLY; not a candidate for machine use",
             "G21 G17 G90 G94 G54", "G0 Z3.0000", "M3 S1000", "G4 P2"]
    for depth in (-0.6, -1.2):
        lines.append(f"; common roughing Z{depth:.4f}")
        for path in rough:
            helpers.emit_path(lines, path, depth, 3, 0.2)
    lines.append("; compared final clearing Z-1.6250")
    for path in finish:
        helpers.emit_path(lines, path, -1.625, 3, 0.2)
    lines.extend(["G0 Z3.0000", "M5", "M2"])
    return "\n".join(lines) + "\n"


def main():
    cfg, region, c095_dir, c091_dir = background_region(ROOT)
    depth, angle, tip = cfg.engraving_depth, cfg.v_angle, cfg.tip_diameter
    finish_cfg = replace(cfg, stepover=0.12)
    rough_cfg = replace(cfg, stepover=0.27)
    print("Planning common roughing and both finish strategies", flush=True)
    concentric_raw, inset, concentric_meta = plan_adaptive_region_engraving(region, finish_cfg)
    helper = load_module(ROOT / "artifacts/ornaments/hawkeye/two-bit/c069-flow/prepare-c069-flow.py",
                         "c095_clearing_helpers")
    concentric = helper.simplify_paths(concentric_raw, 0.04, region, finish_cfg.effective_diameter)
    raster, raster_schedule = scanline_paths(inset, finish_cfg)
    raster = helper.simplify_paths(raster, 0.04, region, finish_cfg.effective_diameter)
    strict, strict_schedule = [], []
    strict_components = list(_polygons(inset))
    for component in strict_components:
        component_paths, component_metrics = strict_row_scanline_paths(
            component, finish_cfg, region,
            finish_cfg.effective_diameter / 2 / math.cos(math.pi / 128),
        )
        strict.extend(component_paths)
        strict_schedule.append(component_metrics)
    strict = helper.simplify_paths(strict, 0.04, region, finish_cfg.effective_diameter)
    rough_raw, rough_inset, rough_meta = plan_adaptive_region_engraving(region, rough_cfg)
    rough = helper.simplify_paths(rough_raw, 0.04, region, rough_cfg.effective_diameter)

    # Both methods use the same C095 0.27 mm concentric upper passes. Only the
    # final 1.625 mm clearing path changes, at identical 0.12 mm spacing.
    candidates = {"concentric": concentric,
                  "optimized_alternating_scanline": raster,
                  "strict_row_alternating_scanline": strict}
    verification_radius = finish_cfg.effective_diameter / 2 / math.cos(math.pi / 128)
    candidate_metrics = {}
    for name, paths in candidates.items():
        sweep = sweeps(paths, verification_radius)
        if not region.covers(sweep):
            raise ValueError(f"{name} full-cutter sweep leaves the raised-water background")
        missed_area = region.difference(sweep).area
        program = emit_program(helper, rough, paths, cfg)
        parsed = parse_gcode(program)
        validate_nonnegative_work_xy(parsed)
        validate_rapid_xy_clearance(parsed, cfg.safe_z)
        motion = analyze_program(parsed)
        floor = floor_profile(paths, region, depth, angle, tip, 0.0125)
        candidate_metrics[name] = {
            "final_path_count": len(paths),
            "final_primitive_segments": sum(max(0, len(path) - 1) for path in paths),
            "final_xy_cut_distance_mm": sum(math.dist(a, b) for path in paths for a, b in zip(path, path[1:])),
            "final_swept_area_mm2": sweep.intersection(region).area,
            "uncovered_area_mm2_conservative_sweep": missed_area,
            "uncovered_area_percent": missed_area / region.area * 100,
            "floor": floor,
            "motion_common_roughing_plus_compared_final": motion,
            "parsed_check": {"xy_nonnegative": True, "rapid_clearance_z_mm": cfg.safe_z,
                             "full_cutter_sweep_contained_in_target": True,
                             "commands": len(parsed.commands)},
        }

    report = {
        "status": "offline strategy comparison only; no machine program emitted",
        "generator_sha256": sha(Path(__file__)),
        "source_c095_report_sha256": sha(c095_dir / "report.json"),
        "source_c095_program_sha256": sha(c095_dir / "01-c095-review-only.nc"),
        "source_c091_mask_sha256": sha(c091_dir / "approved-depth-mask.png"),
        "settings": {"tool": "assumed 30-degree included-angle V-bit, 0.1 mm flat tip",
                     "target_depth_mm": depth, "effective_diameter_mm": cfg.effective_diameter,
                     "stock_thickness_mm": cfg.stock_thickness, "cut_feed_mm_min": cfg.cut_feed,
                     "plunge_feed_mm_min": cfg.plunge_feed, "safe_z_mm": cfg.safe_z,
                     "approach_z_mm": cfg.approach_clearance, "spindle_rpm_assumed": cfg.spindle_rpm,
                     "upper_roughing_stepover_mm": rough_cfg.stepover,
                     "final_clearing_stepover_mm": finish_cfg.stepover,
                     "common_depth_levels_mm": [-0.6, -1.2, -1.625]},
        "tool": {"included_angle_deg": angle, "flat_tip_mm_assumed": tip,
                 "depth_mm": depth, "effective_diameter_mm": cfg.effective_diameter},
        "region": {"description": "C095 raised-ripple water background: its entire water_zone with five ripple islands removed",
                   "bounds_mm": list(region.bounds), "area_mm2": region.area,
                   "connected_components": len(list(_polygons(region)))},
        "spacing_mm": {"common_upper_roughing": rough_cfg.stepover,
                       "compared_final_clearing": finish_cfg.stepover},
        "ideal_parallel_lane_cusp_mm_at_0p12": max(0, (0.12 - tip) / (2 * math.tan(math.radians(angle / 2)))),
        "planning": {"concentric": concentric_meta, "common_roughing": rough_meta,
                     "optimized_alternating_scanline_schedules": raster_schedule,
                     "strict_row_alternating_scanline_schedules": strict_schedule},
        "candidates": candidate_metrics,
        "model": "Continuous line-segment distance with flat-tip V-bit profile; highest material removal over every traversed path; floor sampled on a 0.0125 mm grid, excluding intentional walls within one cutter radius plus 0.1 mm.",
        "limits": ["Assumes 30-degree included angle and 0.1 mm flat tip; actual tool/runout are unverified.",
                   "A geometric floor model predicts ideal cutter scallops, not wood grain, runout, flex, chip recutting, or ply color.",
                   "Motion is parsed feed-based time at C095 settings, not measured controller throughput; it excludes acceleration and corner slowdown.",
                   "Comparison region is the C095 smooth water background only; lettering, sky, aircraft, raised rays, and fine residual are excluded.",
                   "Both programs retain identical 0.27 mm concentric roughing at Z-0.6 and -1.2; only the 0.12 mm final-depth strategy changes."],
    }
    render_floor([
        (concentric, "C095 concentric final pass"),
        (raster, "Optimized alternating scanline"),
        (strict, "Strict row-order alternating scanline"),
    ], region, depth, angle, tip, 0.05, HERE / "floor-comparison.png")
    report["preview_sha256"] = sha(HERE / "floor-comparison.png")
    comparison_path = HERE / "comparison.json"
    comparison_path.write_text(json.dumps(report, indent=2) + "\n")
    manifest = {
        "status": "offline comparison artifact manifest",
        "generator_sha256": sha(Path(__file__)),
        "comparison_json_sha256": sha(comparison_path),
        "preview_png_sha256": sha(HERE / "floor-comparison.png"),
        "source_c095_report_sha256": report["source_c095_report_sha256"],
        "source_c095_program_sha256": report["source_c095_program_sha256"],
        "source_c091_mask_sha256": report["source_c091_mask_sha256"],
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: {"paths": v["final_path_count"],
                          "final_xy_mm": round(v["final_xy_cut_distance_mm"], 2),
                          "residual_p95_mm": round(v["floor"]["residual_above_target_depth_mm"]["p95"], 4),
                          "residual_max_mm": round(v["floor"]["residual_above_target_depth_mm"]["max"], 4),
                          "job_minutes": round(v["motion_common_roughing_plus_compared_final"]["feed_based_seconds"] / 60, 2),
                          "missed_area_mm2": round(v["uncovered_area_mm2_conservative_sweep"], 7)}
                     for k, v in candidate_metrics.items()}, indent=2), flush=True)


if __name__ == "__main__":
    HERE.mkdir(parents=True, exist_ok=True)
    main()
