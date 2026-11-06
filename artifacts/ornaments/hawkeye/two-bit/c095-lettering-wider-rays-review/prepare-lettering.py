"""Rebuild C095 ring lettering with an emitted V-bit-safe design.

Offline only. This creates review artifacts and a review-only G-code file; it
does not access the CNC application, backend, or machine.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import math
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from shapely.affinity import scale as geom_scale
from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))
RAY_HELPER_DIR = ROOT / "artifacts/ornaments/hawkeye/two-bit/c095-ray-width-review"
sys.path.insert(0, str(RAY_HELPER_DIR))
from tapered_rays import make_tapered_ray_layout, clip_rays_to_sky
from ttc3018_control.ornament_cam import (
    OrnamentSettings,
    _polygons,
    plan_adaptive_region_engraving,
    raster_region,
)
from ttc3018_control.gcode import (
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)
from ttc3018_control.job_analysis import analyze_program

SOURCE_DIR = HERE.parent / "c091-approved-raised-plane"
BASE_DIR = HERE.parent / "c095-cutter-faithful-redesign"
BASE_PROGRAM = BASE_DIR / "01-c095-review-only.nc"
BASE_REPORT = BASE_DIR / "report.json"
GRID = 0.025
FRAME_MM = 110.0
PIXELS_PER_MM = round(1 / GRID)
IMAGE_SIZE = round(FRAME_MM / GRID)
LETTER_DEPTH = 0.45
LETTER_PASS_DEPTHS = (0.45,) if LETTER_DEPTH <= 0.45 else (0.45, LETTER_DEPTH)
LETTER_RADIUS_MM = 36.8
FONT_PATH = Path(r"C:\Windows\Fonts\arialbd.ttf")
FONT_SIZE_MM = 6.4
TRACKING_MM = 0.60
GLYPH_EXPANSION_MM = 0.03
TOP_SPREAD_DEG = 104.0
BOTTOM_SPREAD_DEG = 128.0
LETTER_TEXTS = (("DOME RIDERS", 90.0, TOP_SPREAD_DEG, False),
                ("VAW-120 Key West", 270.0, BOTTOM_SPREAD_DEG, True))
CLEAR_INNER_RADIUS_MM = 32.3
CLEAR_OUTER_RADIUS_MM = 40.5
CLEAR_ANGLE_RANGES = ((26.0, 154.0), (200.0, 340.0))
SCANLINE_STEP_PX = 2  # 0.05 mm; smaller than the 0.1 mm flat tip.
MIN_RUN_PX = 3
SWEEP_GUARD_PX = 9  # 0.225 mm square guard; cutter radius is 0.171 mm.
SEAM_OVERLAP_MM = 0.6
RAY_ANGLES_DEG = (30, 45, 60, 75, 90, 105, 120, 135, 150)
RAY_CENTER_MM = (55.0, 62.0)
RAY_RADII_MM = (11.0, 27.0)
RAY_WIDTHS_MM = (0.8, 3.3)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sector(center_x, center_y, radius, start_deg, end_deg):
    angles = np.linspace(start_deg, end_deg, 256)
    pts = [(center_x, center_y)] + [
        (center_x + radius * math.cos(math.radians(a)),
         center_y + radius * math.sin(math.radians(a))) for a in angles
    ] + [(center_x, center_y)]
    return Polygon(pts)


def annular_clear_zone():
    center = Point(55, 55)
    annulus = center.buffer(CLEAR_OUTER_RADIUS_MM, quad_segs=256).difference(
        center.buffer(CLEAR_INNER_RADIUS_MM, quad_segs=256))
    arcs = [sector(55, 55, CLEAR_OUTER_RADIUS_MM + 0.1, start, end)
            for start, end in CLEAR_ANGLE_RANGES]
    return annulus.intersection(unary_union(arcs))


def draw_curved_text():
    """Supersample upright glyphs around the ring; return masks and metadata."""
    scale_px = PIXELS_PER_MM
    ss = 2
    canvas = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
    font = ImageFont.truetype(str(FONT_PATH), round(FONT_SIZE_MM * scale_px * ss))
    tile_px = round(12 * scale_px * ss)
    tile_small = tile_px // ss
    glyphs = []
    for phrase_index, (text, center_angle, spread, bottom) in enumerate(LETTER_TEXTS):
        widths = [font.getlength(char) for char in text]
        visible = [i for i, char in enumerate(text) if char != " "]
        total = sum(widths) + TRACKING_MM * scale_px * ss * max(0, len(visible) - 1)
        cursor = 0.0
        for index, (char, width) in enumerate(zip(text, widths)):
            fraction = (cursor + width / 2) / total - 0.5
            direction = 1 if bottom else -1
            angle = center_angle + direction * spread * fraction
            cursor += width
            if char == " ":
                glyphs.append({"phrase_index": phrase_index, "index": index,
                               "char": char, "angle_deg": angle, "mask": None,
                               "left_px": None, "top_px": None})
                continue
            cursor += TRACKING_MM * scale_px * ss
            tile = Image.new("L", (tile_px, tile_px), 0)
            ImageDraw.Draw(tile).text((tile_px / 2, tile_px / 2), char,
                                      font=font, fill=255, anchor="mm")
            rotation = angle - (270 if bottom else 90)
            tile = tile.rotate(rotation, resample=Image.Resampling.BICUBIC,
                               expand=False)
            expansion_px = round(GLYPH_EXPANSION_MM * scale_px * ss)
            tile = tile.filter(ImageFilter.MaxFilter(2 * expansion_px + 1))
            tile = tile.resize((tile_small, tile_small), Image.Resampling.LANCZOS)
            x_mm = 55 + LETTER_RADIUS_MM * math.cos(math.radians(angle))
            y_mm = 55 + LETTER_RADIUS_MM * math.sin(math.radians(angle))
            x_px = round(x_mm * scale_px)
            y_px = round((FRAME_MM - y_mm) * scale_px)
            left = x_px - tile_small // 2
            top = y_px - tile_small // 2
            if left < 0 or top < 0 or left + tile_small > IMAGE_SIZE or top + tile_small > IMAGE_SIZE:
                raise ValueError(f"Glyph {char!r} leaves the 110 mm canvas")
            current = canvas.crop((left, top, left + tile_small, top + tile_small))
            canvas.paste(ImageChops.lighter(current, tile), (left, top))
            glyphs.append({"phrase_index": phrase_index, "index": index,
                           "char": char, "angle_deg": angle, "mask": tile,
                           "left_px": left, "top_px": top})
    return canvas, glyphs


def run_intervals(row):
    edges = np.diff(np.r_[False, row, False].astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return zip(starts, ends)


def make_letter_paths(letter_mask, glyphs):
    """Inset each glyph by a guarded tool radius and emit exact XY scanlines."""
    paths = []
    csv_rows = []
    glyph_stats = []
    centerline_full = Image.new("L", letter_mask.size, 0)
    draw_full = ImageDraw.Draw(centerline_full)
    sweep_guard = ImageFilter.MaxFilter(2 * SWEEP_GUARD_PX + 1)
    inset_filter = ImageFilter.MinFilter(2 * SWEEP_GUARD_PX + 1)
    for glyph in glyphs:
        if glyph["mask"] is None:
            continue
        mask = glyph["mask"].point(lambda v: 255 if v >= 128 else 0)
        inset = mask.filter(inset_filter)
        arr = np.asarray(inset) > 0
        glyph_paths = []
        local_draw = ImageDraw.Draw(Image.new("L", (1, 1), 0))
        del local_draw
        for row_index in range(glyph["mask"].height):
            if row_index % SCANLINE_STEP_PX != glyph["index"] % SCANLINE_STEP_PX:
                continue
            for start, end in run_intervals(arr[row_index]):
                if end - start < MIN_RUN_PX:
                    continue
                x0_px = glyph["left_px"] + start + 0.5
                x1_px = glyph["left_px"] + end - 0.5
                y_px = glyph["top_px"] + row_index + 0.5
                path = (((x0_px / PIXELS_PER_MM),
                         (FRAME_MM - y_px / PIXELS_PER_MM)),
                        ((x1_px / PIXELS_PER_MM),
                         (FRAME_MM - y_px / PIXELS_PER_MM)))
                paths.append(path)
                glyph_paths.append(path)
                draw_full.line((x0_px - 0.5, y_px - 0.5,
                                x1_px - 0.5, y_px - 0.5), fill=255, width=1)
                csv_rows.append((len(paths), glyph["phrase_index"], glyph["index"],
                                 glyph["char"], *path[0], *path[1], -LETTER_DEPTH))
        raw_components = count_components(np.asarray(mask) > 0)
        inset_components = count_components(arr)
        glyph_stats.append({"phrase_index": glyph["phrase_index"],
                            "character_index": glyph["index"],
                            "character": glyph["char"],
                            "raw_components": raw_components,
                            "inset_components": inset_components,
                            "scanlines": len(glyph_paths),
                            "components_lost_to_tool_clearance": max(0, raw_components - inset_components)})
    return paths, csv_rows, glyph_stats, centerline_full, sweep_guard


def count_components(binary):
    """Count 8-connected components using runs instead of per-pixel floods."""
    parent = []

    def root(label):
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    def merge(left, right):
        a, b = root(left), root(right)
        if a != b:
            parent[b] = a

    previous = []
    for row in binary:
        current = []
        for start, end in run_intervals(row):
            matches = [label for pstart, pend, label in previous
                       if start <= pend and end >= pstart]
            if not matches:
                label = len(parent)
                parent.append(label)
            else:
                label = root(matches[0])
                for other in matches[1:]:
                    merge(label, other)
            current.append((start, end, label))
        previous = current
    return len({root(label) for label in range(len(parent))})


def build_base_geometry(cfg):
    source, _ = raster_region(SOURCE_DIR / "approved-depth-mask.png", cfg)
    keepout = Point(55, 100).buffer(3, quad_segs=128)
    original = source.difference(keepout)
    inner = Point(55, 55).buffer(32.0, quad_segs=256)
    raised_aircraft = unary_union([
        p for p in _polygons(inner.difference(original))
        if p.area > 15 and p.intersects(box(30, 44, 80, 66))
    ])
    sky_zone = inner.intersection(box(20, 66, 90, 91)).difference(raised_aircraft.buffer(.15))
    water_zone = inner.intersection(box(22, 24, 88, 41.5))
    ray_layout = make_tapered_ray_layout(
        center=RAY_CENTER_MM, angles_deg=RAY_ANGLES_DEG,
        start_radius_mm=RAY_RADII_MM[0], end_radius_mm=RAY_RADII_MM[1],
        inner_width_mm=RAY_WIDTHS_MM[0], outer_width_mm=RAY_WIDTHS_MM[1],
    )
    ray_clip_zone = sky_zone.intersection(inner.buffer(-1.2))
    raised_rays = clip_rays_to_sky(ray_layout, ray_clip_zone)
    ripples = []
    for x, y, length, height in ((47, 39, 22, 1.25), (66, 36.2, 14, 1.4),
                                 (42, 33.4, 17, 1.35), (61, 30.5, 18, 1.3),
                                 (48, 27.7, 12, 1.35)):
        ripples.append(geom_scale(Point(x, y).buffer(1, quad_segs=64),
                                  xfact=length / 2, yfact=height / 2))
    raised_water = unary_union(ripples).intersection(water_zone)
    revised = original.union(sky_zone).difference(raised_rays).union(water_zone).difference(raised_water)
    assert revised.symmetric_difference(original).difference(sky_zone.union(water_zone)).area < 1e-8
    return revised, inner, original


def gcode_paths(text):
    groups = {}
    path = None
    depth = None
    def close():
        if path is not None and depth is not None and len(path) >= 2:
            groups.setdefault(depth, []).append(tuple(path))
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        words = line.split()
        if not words:
            continue
        values = {word[0]: float(word[1:]) for word in words[1:] if len(word) > 1}
        if words[0] == "G0" and values.get("Z") == 3.0:
            close(); path = None; depth = None
        elif words[0] == "G0" and "X" in values and "Y" in values:
            path = [(values["X"], values["Y"])]
        elif words[0] == "G1" and "Z" in values:
            depth = values["Z"]
        elif words[0] == "G1" and "X" in values and "Y" in values:
            if path is None:
                raise ValueError("Emitted XY move has no preceding rapid start")
            path.append((values["X"], values["Y"]))
    close()
    return groups


def cutter_sweep(paths, diameter):
    guard = diameter / 2 / math.cos(math.pi / 128)
    return unary_union([LineString(path).buffer(guard, quad_segs=32) for path in paths])


def remove_surface(depth_map, paths, depth):
    tangent = math.tan(math.radians(15))
    radius = 0.05 + depth * tangent
    count = depth_map.shape[0]
    for path in paths:
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            left = max(0, int(math.floor((min(ax, bx) - radius) / GRID)))
            right = min(count, int(math.ceil((max(ax, bx) + radius) / GRID)) + 1)
            bottom = max(0, int(math.floor((min(ay, by) - radius) / GRID)))
            top = min(count, int(math.ceil((max(ay, by) + radius) / GRID)) + 1)
            xx = (np.arange(left, right, dtype=np.float32) + .5) * GRID
            yy = (np.arange(bottom, top, dtype=np.float32) + .5) * GRID
            dx, dy = bx - ax, by - ay
            denominator = dx * dx + dy * dy
            if denominator:
                t = np.clip(((xx[None, :] - ax) * dx + (yy[:, None] - ay) * dy) / denominator, 0, 1)
                r = np.sqrt((xx[None, :] - ax - t * dx) ** 2 + (yy[:, None] - ay - t * dy) ** 2)
            else:
                r = np.sqrt((xx[None, :] - ax) ** 2 + (yy[:, None] - ay) ** 2)
            removal = np.maximum(0, depth - np.maximum(0, r - .05) / tangent)
            target = depth_map[bottom:top, left:right]
            np.maximum(target, removal, out=target)


def render_depth(depth_map, path):
    fraction = np.clip(depth_map / 1.625, 0, 1)
    light = np.array([236, 208, 160], dtype=np.float32)
    dark = np.array([104, 57, 31], dtype=np.float32)
    pixels = light[None, None, :] + fraction[:, :, None] * (dark - light)[None, None, :]
    gy, gx = np.gradient(-depth_map, GRID)
    illumination = .90 + .25 * (-.45 * gx + .55 * gy + 1) / np.sqrt(gx * gx + gy * gy + 1)
    pixels *= np.clip(illumination, .62, 1.15)[:, :, None]
    coord = (np.arange(depth_map.shape[0], dtype=np.float32) + .5) * GRID
    disc = (coord[None, :] - 55) ** 2 + (coord[:, None] - 55) ** 2 <= 50 ** 2
    hole = (coord[None, :] - 55) ** 2 + (coord[:, None] - 100) ** 2 <= 2 ** 2
    pixels[~disc | hole] = 255
    Image.fromarray(np.uint8(np.clip(pixels, 0, 255)[::-1])).resize(
        (1800, 1800), Image.Resampling.LANCZOS).save(path)


def raster_geometry_mask(geometry):
    image = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
    draw = ImageDraw.Draw(image)
    for polygon in _polygons(geometry):
        draw.polygon([(x / FRAME_MM * IMAGE_SIZE,
                       (FRAME_MM - y) / FRAME_MM * IMAGE_SIZE)
                      for x, y in polygon.exterior.coords], fill=255)
        for ring in polygon.interiors:
            draw.polygon([(x / FRAME_MM * IMAGE_SIZE,
                           (FRAME_MM - y) / FRAME_MM * IMAGE_SIZE)
                          for x, y in ring.coords], fill=0)
    return image


def main():
    HERE.mkdir(exist_ok=True)
    base_report = json.loads(BASE_REPORT.read_text())
    cfg = OrnamentSettings(**base_report["settings"])
    letters_only = "--letters-only" in sys.argv

    letter_mask, glyphs = draw_curved_text()
    letter_mask.save(HERE / "clean-letter-mask.png")
    letter_paths, csv_rows, glyph_stats, centerline_mask, sweep_guard = make_letter_paths(letter_mask, glyphs)
    if not letter_paths:
        raise ValueError("No cutter-centerline paths survived the V-bit clearance")
    with (HERE / "letter-centerlines.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("stroke_id", "phrase_index", "character_index", "character",
                         "x_start_mm", "y_start_mm", "x_end_mm", "y_end_mm", "z_mm"))
        writer.writerows(csv_rows)

    # Make the high-resolution standalone letter cutter envelope check. The
    # 0.225 mm square guard is larger than the 0.171 mm true cutter radius.
    conservative_sweep = centerline_mask.filter(sweep_guard)
    target_binary = letter_mask.point(lambda v: 255 if v >= 128 else 0)
    outside = ImageChops.subtract(conservative_sweep, target_binary)
    sweep_outside_pixels = int(np.count_nonzero(np.asarray(outside)))
    if sweep_outside_pixels:
        raise ValueError(f"Letter cutter envelope escapes the mask by {sweep_outside_pixels} pixels")

    if letters_only:
        depth_map = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
        for path in letter_paths:
            remove_surface(depth_map, (path,), LETTER_DEPTH)
        preview = HERE / "letter-strokes-preview.png"
        render_depth(depth_map, preview)
        study = {"status": "offline lettering study; no base CAM or machine interaction",
                 "font": {"file": str(FONT_PATH), "sha256": sha(FONT_PATH),
                          "face": "Arial Bold", "size_mm": FONT_SIZE_MM,
                          "bold_expansion_mm_each_side": GLYPH_EXPANSION_MM},
                 "phrases": [item[0] for item in LETTER_TEXTS],
                 "letter_depth_mm": LETTER_DEPTH,
                 "maximum_cutter_width_mm": 0.1 + 2 * LETTER_DEPTH * math.tan(math.radians(15)),
                 "sweep_guard_mm": 2 * SWEEP_GUARD_PX * GRID,
                 "line_spacing_mm": SCANLINE_STEP_PX * GRID,
                 "centerline_paths": len(letter_paths),
                 "conservative_sweep_pixels_outside_mask": sweep_outside_pixels,
                 "glyphs_without_paths": sum(1 for item in glyph_stats if item["scanlines"] == 0),
                 "letter_components_lost_to_tool_clearance": sum(item["components_lost_to_tool_clearance"] for item in glyph_stats),
                 "per_glyph": glyph_stats,
                 "mask_sha256": sha(HERE / "clean-letter-mask.png"),
                 "preview_sha256": sha(preview)}
        (HERE / "lettering-study-report.json").write_text(json.dumps(study, indent=2), encoding="utf-8")
        print(json.dumps({"mode": "letters-only", "paths": len(letter_paths),
                          "sweep_outside_pixels": sweep_outside_pixels,
                          "glyphs_without_paths": study["glyphs_without_paths"],
                          "components_lost": study["letter_components_lost_to_tool_clearance"],
                          "preview": str(preview)}, indent=2), flush=True)
        return

    revised, inner, original = build_base_geometry(cfg)
    clear_zone = annular_clear_zone()
    # Keep the legacy border radii outside the replacement band. The text is
    # cleared only where the original label arcs occupy the ring.
    clean_base = revised.difference(clear_zone)

    # Preserve exact C095 center art, palm/boat, and border construction. Only
    # the C095 lettering annulus is removed; the new paths are added separately.
    helpers = load_module(ROOT / "artifacts/ornaments/hawkeye/two-bit/c069-flow/prepare-c069-flow.py", "c095_letter_helpers")
    clearing = load_module(ROOT / "artifacts/ornaments/hawkeye/two-bit/c095-clearing-comparison/compare-clearing.py", "c095_strict_water_clearing")
    roughcfg = replace(cfg, stepover=.27)
    finishcfg = replace(cfg, stepover=.12)
    _, water_source, _, _ = clearing.background_region(ROOT)
    water_core = water_source.intersection(clean_base)
    # Both strategies extend 0.6 mm into the shared target, so their full
    # cutter envelopes overlap across the partition instead of leaving a seam.
    water_region = water_core.buffer(SEAM_OVERLAP_MM, quad_segs=64).intersection(clean_base)
    non_water_region = clean_base.difference(water_core.buffer(-SEAM_OVERLAP_MM, quad_segs=64))
    if not clean_base.covers(water_region.union(non_water_region)):
        raise ValueError("Water/non-water planning regions leave a target gap")
    seam_overlap_area = water_region.intersection(non_water_region).area
    print("Planning C095 lettering rebuild and strict-row water finish", flush=True)
    raw, _, finish_meta = plan_adaptive_region_engraving(non_water_region, finishcfg)
    broad = helpers.simplify_paths(raw, .04, non_water_region, finishcfg.effective_diameter)
    _, water_inset, water_finish_meta = plan_adaptive_region_engraving(water_region, finishcfg)
    strict_water = []
    strict_schedule = []
    verification_radius = finishcfg.effective_diameter / 2 / math.cos(math.pi / 128)
    for component in _polygons(water_inset):
        paths, metrics = clearing.strict_row_scanline_paths(
            component, finishcfg, water_region, verification_radius)
        strict_water.extend(paths)
        strict_schedule.append(metrics)
    strict_water = helpers.simplify_paths(strict_water, .04, water_region,
                                          finishcfg.effective_diameter)
    rough_raw, _, rough_meta = plan_adaptive_region_engraving(clean_base, roughcfg)
    rough = helpers.simplify_paths(rough_raw, .04, clean_base, roughcfg.effective_diameter)
    broad_sweep = cutter_sweep(broad, finishcfg.effective_diameter).union(
        cutter_sweep(strict_water, finishcfg.effective_diameter))
    residual = clean_base.difference(broad_sweep).buffer(.07).intersection(clean_base)
    finecfg = replace(cfg, engraving_depth=.04, max_stepdown=.04, stepover=.09)
    fine_raw, _, fine_meta = plan_adaptive_region_engraving(residual, finecfg)
    fine = helpers.simplify_paths(fine_raw, .04, clean_base, finecfg.effective_diameter)
    rough_sweep = cutter_sweep(rough, roughcfg.effective_diameter)
    fine_sweep = cutter_sweep(fine, finecfg.effective_diameter)
    if not clean_base.covers(rough_sweep):
        raise ValueError("Rounded rough cutter sweep leaves the clean base design")
    if not clean_base.covers(broad_sweep):
        raise ValueError("Rounded deep cutter sweep leaves the clean base design")
    if not clean_base.covers(fine_sweep):
        raise ValueError("Rounded fine cutter sweep leaves the clean base design")

    lines = ["; C095 LETTERING REBUILD; offline review only; not released",
             "G21 G17 G90 G94 G54", "G0 Z3.0000", "M3 S1000", "G4 P2"]
    for depth, paths in ((-.6, rough), (-1.2, rough), (-1.625, broad)):
        lines.append(f"; PASS Z{depth:.4f}: unchanged C095 geometry with old text removed")
        for path in paths:
            helpers.emit_path(lines, path, depth, 3, .2)
    lines.append("; WATER FINAL CLEARING Z-1.6250: strict row-order, alternating X direction")
    for path in strict_water:
        helpers.emit_path(lines, path, -1.625, 3, .2)
    for depth in LETTER_PASS_DEPTHS:
        lines.append(f"; LETTERING PASS Z{-depth:.4f}: standalone guarded centerlines")
        for path in letter_paths:
            helpers.emit_path(lines, path, -depth, 3, .2)
    lines.append("; FINE DETAIL PASS Z-0.0400")
    for path in fine:
        helpers.emit_path(lines, path, -.04, 3, .2)
    lines += ["G0 Z3.0000", "M5", "M2"]
    output = HERE / "01-c095-lettering-review-only.nc"
    text = "\n".join(lines) + "\n"
    output.write_text(text, encoding="ascii", newline="\n")
    program = parse_gcode(text, output)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, 3)

    # The preview is reconstructed from the rounded emitted G-code, all depth
    # levels included. It does not repaint the source mask or synthesize relief.
    groups = gcode_paths(text)
    expected = {-.6, -1.2, -1.625, -.04, *(-depth for depth in LETTER_PASS_DEPTHS)}
    if set(groups) != expected:
        raise ValueError(f"Unexpected emitted depth groups: {sorted(groups)}")
    rounded_sweeps = {
        "rough_z_0p6": cutter_sweep(groups[-.6], roughcfg.effective_diameter),
        "rough_z_1p2": cutter_sweep(groups[-1.2], roughcfg.effective_diameter),
        "deep_z_1p625": cutter_sweep(groups[-1.625], finishcfg.effective_diameter),
        "fine_z_0p04": cutter_sweep(groups[-.04], finecfg.effective_diameter),
    }
    for label, sweep in rounded_sweeps.items():
        if not clean_base.covers(sweep):
            raise ValueError(f"Rounded emitted {label} cutter sweep escapes the clean base")
    emitted_letter_mask = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
    emitted_draw = ImageDraw.Draw(emitted_letter_mask)
    for path in groups[-LETTER_DEPTH]:
        points = [(round(x * PIXELS_PER_MM - .5),
                   round((FRAME_MM - y) * PIXELS_PER_MM - .5)) for x, y in path]
        emitted_draw.line(points, fill=255, width=1)
    emitted_letter_sweep = emitted_letter_mask.filter(ImageFilter.MaxFilter(2 * SWEEP_GUARD_PX + 1))
    emitted_letter_outside = int(np.count_nonzero(np.asarray(
        ImageChops.subtract(emitted_letter_sweep, target_binary))))
    if emitted_letter_outside:
        raise ValueError(f"Rounded emitted lettering sweep escapes the mask by {emitted_letter_outside} pixels")
    depth_map = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
    for z, paths in groups.items():
        for path in paths:
            remove_surface(depth_map, (path,), -z)
    np.save(HERE / "modeled-removal-depth-mm.npy", depth_map)
    preview = HERE / "c095-lettering-preview.png"
    render_depth(depth_map, preview)
    non_water_core = clean_base.difference(water_core)
    shared_seam = water_core.boundary.intersection(non_water_core.boundary)
    seam_band = clean_base.intersection(shared_seam.buffer(SEAM_OVERLAP_MM, quad_segs=64))
    # The only shared target interface is the y=41.5 water-zone clip edge.
    # It lies immediately beside the clean-base exterior and is within the
    # V-bit's natural outer-wall taper; its floor residual cannot assess a
    # strategy seam, so report the measurements without calling them a pass.
    seam_mask = np.asarray(raster_geometry_mask(seam_band))[::-1] > 0
    seam_residual = 1.625 - depth_map[seam_mask]
    seam_x_samples = np.linspace(shared_seam.bounds[0], shared_seam.bounds[2], 12)
    seam_y_samples = np.full(12, shared_seam.bounds[1])
    seam_exterior_distances = [Point(float(x), float(y)).distance(clean_base.boundary)
                                for x, y in zip(seam_x_samples, seam_y_samples)]
    seam_floor = {"sample_count": int(seam_residual.size),
                  "shared_interface_length_mm": float(shared_seam.length),
                  "overlap_band_each_side_mm": SEAM_OVERLAP_MM,
                  "p50_residual_mm": float(np.percentile(seam_residual, 50)) if seam_residual.size else None,
                  "p95_residual_mm": float(np.percentile(seam_residual, 95)) if seam_residual.size else None,
                  "p99_residual_mm": float(np.percentile(seam_residual, 99)) if seam_residual.size else None,
                  "max_residual_mm": float(np.max(seam_residual)) if seam_residual.size else None,
                  "area": "shared water/non-water target interface at the y=41.5 mm water-zone clip edge",
                  "status": "not_assessable_external_taper",
                  "minimum_distance_to_clean_base_exterior_mm": float(shared_seam.distance(clean_base.boundary)),
                  "sampled_interface_distance_to_clean_base_exterior_mm": {
                      "p05": float(np.percentile(seam_exterior_distances, 5)),
                      "p50": float(np.percentile(seam_exterior_distances, 50)),
                      "p95": float(np.percentile(seam_exterior_distances, 95)),
                  },
                  "assessment": "Not a pass metric: the full shared interface lies within 0.35 mm of the clean-base exterior, inside the 0.486 mm maximum-depth cutter radius."}

    # Full design mask: black is the planned removed area; white remains raised.
    def raster_base(geometry, size=2200):
        image = Image.new("L", (size, size), 255)
        draw = ImageDraw.Draw(image)
        for polygon in _polygons(geometry):
            draw.polygon([(x / FRAME_MM * size, (FRAME_MM - y) / FRAME_MM * size)
                          for x, y in polygon.exterior.coords], fill=0)
            for ring in polygon.interiors:
                draw.polygon([(x / FRAME_MM * size, (FRAME_MM - y) / FRAME_MM * size)
                              for x, y in ring.coords], fill=255)
        return image
    design_mask = raster_base(clean_base)
    letter_small = letter_mask.resize(design_mask.size, Image.Resampling.LANCZOS)
    design_mask.paste(0, mask=letter_small)
    design_mask.save(HERE / "clean-design-mask.png")

    # Build a paired enlarged crop of both label arcs for legibility review.
    source_preview = Image.open(preview).convert("RGB")
    crop_width = round(78 / FRAME_MM * source_preview.width)
    crop_height = round(23 / FRAME_MM * source_preview.height)
    cx = source_preview.width // 2
    top_cy = round((FRAME_MM - (55 + LETTER_RADIUS_MM)) / FRAME_MM * source_preview.height)
    bottom_cy = round((FRAME_MM - (55 - LETTER_RADIUS_MM)) / FRAME_MM * source_preview.height)
    top_crop = source_preview.crop((cx - crop_width // 2, top_cy - crop_height // 2,
                                    cx + crop_width // 2, top_cy + crop_height // 2))
    bottom_crop = source_preview.crop((cx - crop_width // 2, bottom_cy - crop_height // 2,
                                       cx + crop_width // 2, bottom_cy + crop_height // 2))
    detail = Image.new("RGB", (max(top_crop.width, bottom_crop.width), top_crop.height + bottom_crop.height + 36), "white")
    detail.paste(top_crop, (0, 0)); detail.paste(bottom_crop, (0, top_crop.height + 36))
    d = ImageDraw.Draw(detail)
    d.text((8, top_crop.height + 8), "lower arc", fill="#333")
    detail.save(HERE / "letter-arcs-detail.png")

    # Explicit geometry checks against the protected motifs and border bands.
    raised_art = inner.difference(original)
    palm = unary_union([p for p in _polygons(raised_art) if p.intersects(box(9, 42, 28, 68))])
    boat = unary_union([p for p in _polygons(raised_art) if p.intersects(box(86, 42, 101, 68))])
    protected_overlap = clear_zone.intersection(palm.union(boat)).area
    border_guard = Point(55, 55).buffer(43.4, quad_segs=256).difference(Point(55, 55).buffer(41.3, quad_segs=256))
    border_overlap = clear_zone.intersection(border_guard).area
    inner_border_guard = Point(55, 55).buffer(32.15, quad_segs=256).difference(Point(55, 55).buffer(31.95, quad_segs=256))
    inner_border_overlap = clear_zone.intersection(inner_border_guard).area
    target_arr = np.asarray(target_binary) >= 128
    palm_pixels = np.asarray(raster_geometry_mask(palm)) > 0
    boat_pixels = np.asarray(raster_geometry_mask(boat)) > 0
    border_pixels = np.asarray(raster_geometry_mask(border_guard.union(inner_border_guard))) > 0
    letter_palm_overlap_pixels = int(np.count_nonzero(target_arr & palm_pixels))
    letter_boat_overlap_pixels = int(np.count_nonzero(target_arr & boat_pixels))
    letter_border_overlap_pixels = int(np.count_nonzero(target_arr & border_pixels))
    del palm_pixels, boat_pixels, border_pixels, target_arr
    glyph_area = int(np.count_nonzero(np.asarray(target_binary))) * GRID * GRID
    cutter_radius = finishcfg.tip_diameter / 2 + LETTER_DEPTH * math.tan(math.radians(15))
    lost_components = sum(item["components_lost_to_tool_clearance"] for item in glyph_stats)
    missing_glyphs = [item for item in glyph_stats if item["scanlines"] == 0]
    if protected_overlap > 1e-8 or border_overlap > 1e-8:
        raise ValueError(f"Typography clear zone intersects protected geometry: motifs={protected_overlap}, border={border_overlap}")
    if letter_palm_overlap_pixels or letter_boat_overlap_pixels or letter_border_overlap_pixels or inner_border_overlap > 1e-8:
        raise ValueError("Letter mask intersects a protected palm/boat or circular border region")
    if missing_glyphs:
        raise ValueError("No cutter paths for glyph(s): " + ", ".join(x["character"] for x in missing_glyphs))

    report = {
        "status": "offline review only; not loaded, released, or physically tested",
        "source_artifact": "C095 revised geometry from C091 approved raised-plane mask",
        "ray_geometry": {"method": "straight-sided tapered wedge polygons clipped to C095 sky and aircraft exclusion",
                         "center_mm": list(RAY_CENTER_MM),
                         "angles_deg": list(RAY_ANGLES_DEG),
                         "radii_mm": list(RAY_RADII_MM),
                         "full_widths_mm_inner_to_outer": list(RAY_WIDTHS_MM),
                         "clip": "sky_zone intersected with inner circle inset by 1.2 mm",
                         "editable_helper": str(RAY_HELPER_DIR / "tapered_rays.py")},
        "source_mask_sha256": sha(SOURCE_DIR / "approved-depth-mask.png"),
        "baseline_program_sha256": sha(BASE_PROGRAM),
        "baseline_report_sha256": sha(BASE_REPORT),
        "output_program_sha256": sha(output),
        "design_mask_sha256": sha(HERE / "clean-design-mask.png"),
        "letter_mask_sha256": sha(HERE / "clean-letter-mask.png"),
        "letter_centerlines_sha256": sha(HERE / "letter-centerlines.csv"),
        "font": {"file": str(FONT_PATH), "sha256": sha(FONT_PATH),
                 "face": "Arial Bold", "size_mm": FONT_SIZE_MM,
                 "bold_expansion_mm_each_side": GLYPH_EXPANSION_MM},
        "typography": {"top": LETTER_TEXTS[0][0], "bottom": LETTER_TEXTS[1][0],
                       "centerline_radius_mm": LETTER_RADIUS_MM,
                       "top_spread_deg": TOP_SPREAD_DEG,
                       "bottom_spread_deg": BOTTOM_SPREAD_DEG,
                       "tracking_mm": TRACKING_MM,
                       "clear_annulus_mm": [CLEAR_INNER_RADIUS_MM, CLEAR_OUTER_RADIUS_MM],
                       "clear_angle_ranges_deg": CLEAR_ANGLE_RANGES},
        "letter_tool": {"angle_deg": 30, "tip_mm": 0.1, "depth_mm": LETTER_DEPTH,
                        "pass_depths_mm": list(LETTER_PASS_DEPTHS),
                        "maximum_stepdown_mm": max(LETTER_PASS_DEPTHS),
                        "maximum_cut_width_mm": 0.1 + 2 * LETTER_DEPTH * math.tan(math.radians(15)),
                        "conservative_square_guard_mm": 2 * SWEEP_GUARD_PX * GRID,
                        "line_spacing_mm": SCANLINE_STEP_PX * GRID,
                        "target_mask_area_mm2": glyph_area,
                        "centerline_paths": len(letter_paths),
                        "glyphs_without_paths": len(missing_glyphs),
                        "letter_components_lost_to_tool_clearance": lost_components,
                        "initial_conservative_sweep_pixels_outside_mask": sweep_outside_pixels,
                        "rounded_emitted_sweep_pixels_outside_mask": emitted_letter_outside,
                        "per_glyph": glyph_stats},
        "protected_geometry": {"palm_and_boat_intersection_with_clear_zone_mm2": protected_overlap,
                               "letter_mask_overlap_pixels": {"palm": letter_palm_overlap_pixels,
                                                               "sailboat": letter_boat_overlap_pixels,
                                                               "inner_and_outer_borders": letter_border_overlap_pixels},
                               "outer_border_guard_r_41p3_to_43p4_clear_zone_intersection_mm2": border_overlap,
                               "inner_border_guard_r_31p95_to_32p15_clear_zone_intersection_mm2": inner_border_overlap,
                               "remaining_base_cut_area_inside_cleared_letter_band_mm2": clean_base.intersection(clear_zone).area,
                               "inner_border_nominal_radius_mm": 32.0,
                               "outer_border_nominal_radius_mm": 42.35},
        "planning": {"finish_non_water": finish_meta, "rough": rough_meta, "fine": fine_meta,
                     "strict_water_finish": water_finish_meta,
                     "strict_water_schedule": strict_schedule,
                     "water_nonwater_overlap_guard_mm": SEAM_OVERLAP_MM,
                     "water_nonwater_overlap_area_mm2": seam_overlap_area,
                     "rounded_emitted_sweep_containment": {"rough_z_0p6": True,
                                                           "rough_z_1p2": True,
                                                           "deep_z_1p625": True,
                                                           "fine_z_0p04": True},
                     "shared_water_nonwater_seam_floor_residual": seam_floor},
        "emitted_motion": analyze_program(program),
        "preview": {"depth_grid_mm": GRID,
                    "model": f"analytic nearest-distance flat-tip V-bit envelope reconstructed from rounded emitted G-code at all {len(expected)} Z levels",
                    "file_sha256": sha(preview)},
        "limitations": [
            "Mask conversion and letter raster use 0.025 mm pixels; emitted letter endpoints are rounded to 0.0001 mm.",
            "Letter sweep containment is checked with a 0.225 mm square guard, larger than the true 0.171 mm cutter radius.",
            "Color describes modeled depth and is not a prediction of plywood veneer color or finish.",
            "The review-only program has no physical machine validation and is not a cutting release."
        ]
    }
    (HERE / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    readme = f"""# C095 lettering and wider-ray review candidate\n\nOffline design review only; no application, backend, or hardware interaction. The ray revision is not a cutting release.\n\nThe C095 label arcs are rebuilt at radius {LETTER_RADIUS_MM:.1f} mm with the original wording. At {LETTER_DEPTH:.2f} mm depth, the 30 degree / 0.1 mm flat-tip V-bit cuts a maximum {0.1 + 2 * LETTER_DEPTH * math.tan(math.radians(15)):.3f} mm width. The 0.225 mm square sweep guard leaves the letter counters open. The old text band is cleared only from radii {CLEAR_INNER_RADIUS_MM:.1f} to {CLEAR_OUTER_RADIUS_MM:.1f} mm. The circular border guards, palm, and sailboat have zero overlap with the cleared geometry or letter mask.\n\nThe nine sun rays retain C095's centerline directions and radii, with straight-sided wedge widths increasing from 0.8 mm to 3.3 mm, clipped to the existing sky and aircraft keepout. Their editable geometry is in `tapered_rays.py` referenced in `report.json`.\n\n`clean-design-mask.png` uses black for planned cut geometry and white for retained material. `clean-letter-mask.png` isolates the new letter footprint. `letter-centerlines.csv` contains the standalone XY strokes at Z-{LETTER_DEPTH:.2f} mm. `01-c095-lettering-review-only.nc` combines the preserved C095 geometry with the new lettering, wider rays, and all depth passes. It retains concentric clearing except for a strict row-ordered, alternating-direction finish over the water background, where adjacent strategies overlap by {SEAM_OVERLAP_MM:.1f} mm.\n\nThe preview is regenerated from rounded emitted G-code at every depth, using the analytic V-bit model. The water/non-water interface residual is marked not assessable because it lies inside the adjacent exterior-edge taper; see `verification.json`. The image is a depth model, not a plywood color or surface-finish guarantee. See `report.json` for hashes, sweep containment, glyph clearance counts, seam overlap, exact motion metrics, and limits.\n"""
    (HERE / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps({"output": str(output), "output_sha256": sha(output),
                      "letter_paths": len(letter_paths), "depths": sorted(groups),
                      "protected_overlap_mm2": protected_overlap,
                      "border_overlap_mm2": border_overlap,
                      "letter_sweep_outside_pixels": sweep_outside_pixels,
                      "commands": len(program.commands)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
