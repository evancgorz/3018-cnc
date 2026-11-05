"""Build a raster-resolution cutter-sweep study, not CNC job files."""

import base64
import hashlib
import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring, unary_union


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATE = Path(sys.argv[1]).resolve()
CHROME = Path(sys.argv[2])
SCALE = 10
PAD = 50
SIZE = 1300
FLAT_R = 3.175 / 2
V_TIP_R = 0.1 / 2
V_SLOPE = math.tan(math.radians(15))
ENGRAVE = 0.5
THROUGH = 3.35
TAB_DEPTH = 2.25
V_R = V_TIP_R + ENGRAVE * V_SLOPE


def rasterize():
    cmd = [
        str(CHROME), "--headless=new", "--disable-gpu",
        "--disable-background-networking", "--allow-file-access-from-files",
        f"--user-data-dir={STATE / 'preview-chrome'}",
        "--virtual-time-budget=5000", "--dump-dom",
        (HERE / "tool-aware-raster.html").as_uri(),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=True)
    if 'data-ready="true"' not in result.stdout:
        raise RuntimeError("Artwork rasterization failed: " + result.stdout[-1000:])
    images = []
    for name in ("engraving", "tab"):
        match = re.search(
            rf'<pre id="{name}">data:image/png;base64,([^<]+)</pre>',
            result.stdout,
        )
        if not match:
            raise RuntimeError(f"Missing raster: {name}")
        from io import BytesIO
        image = np.array(Image.open(BytesIO(base64.b64decode(match.group(1)))).convert("RGBA"))
        if image.shape != (1200, 1200, 4):
            raise RuntimeError(f"Unexpected {name} raster dimensions")
        images.append(np.pad(image, ((PAD, PAD), (PAD, PAD), (0, 0))))
    return images


def paths_for_mask(safe, spacing_px, safe_steps):
    centers = np.zeros(safe.shape, dtype=bool)
    paths = []
    for y in range(0, SIZE, spacing_px):
        indices = np.flatnonzero(safe[y])
        if not indices.size:
            continue
        breaks = np.flatnonzero(
            (np.diff(indices) > 1) | ~safe_steps[y, indices[:-1]]
        )
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, len(indices) - 1]
        for start, end in zip(starts, ends):
            a, b = int(indices[start]), int(indices[end])
            centers[y, a:b + 1] = True
            paths.append([[a / SCALE, y / SCALE], [b / SCALE, y / SCALE]])
    return centers, paths


def scanlines(region, radius_mm, spacing_px):
    clearance = distance_transform_edt(region)
    required = radius_mm * SCALE + math.sqrt(2) / 2 + 1e-8
    safe = clearance > required
    left, right = clearance[:, :-1], clearance[:, 1:]
    crossing = np.clip((left - right + 1) / 2, 0, 1)
    safe_steps = np.maximum(left - crossing, right - (1 - crossing)) > required
    return paths_for_mask(safe, spacing_px, safe_steps)


def distances_to_centers(centers):
    if not centers.any():
        raise RuntimeError("No tool centers generated for a proposed operation")
    return distance_transform_edt(~centers) / SCALE


def variable_depth_paths(depths):
    paths = []
    for y in range(SIZE):
        indices = np.flatnonzero(depths[y] >= 0.1)
        if not indices.size:
            continue
        breaks = np.flatnonzero(np.diff(indices) > 1)
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, len(indices) - 1]
        for start, end in zip(starts, ends):
            xs = indices[start:end + 1]
            zs = depths[y, xs]
            keep = np.r_[True, np.diff(zs, n=2) != 0, True] if len(xs) > 1 else np.array([True])
            paths.append([[int(x) / SCALE, y / SCALE, round(float(z), 3)] for x, z in zip(xs[keep], zs[keep])])
    return paths


def planar_path_length(paths):
    return sum(
        math.dist(a[:2], b[:2])
        for path in paths
        for a, b in zip(path, path[1:])
    )


def depth_passes(final_depth, max_stepdown):
    count = math.ceil(final_depth / max_stepdown)
    return [round(min(final_depth, (index + 1) * max_stepdown), 6) for index in range(count)]


def flat_link_is_safe(target, a, b):
    a = np.asarray(a) * SCALE
    b = np.asarray(b) * SCALE
    radius = FLAT_R * SCALE
    margin = math.ceil(radius + 1)
    lo = np.maximum(np.floor(np.minimum(a, b)).astype(int) - margin, 0)
    hi = np.minimum(np.ceil(np.maximum(a, b)).astype(int) + margin, SIZE - 1)
    rows, cols = np.where(~target[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1])
    cols, rows = cols + lo[0], rows + lo[1]
    cells = shapely.box(cols - 0.5, rows - 0.5, cols + 0.5, rows + 0.5)
    segment = LineString((a, b))
    return not len(cells) or np.min(shapely.distance(cells, segment)) > radius + 1e-8


def connect_paths(paths, spacing_px, max_dx, link_is_safe):
    endpoints = {}
    for index, path in enumerate(paths):
        for side, point in enumerate((path[0], path[-1])):
            x, y = point[:2]
            endpoints.setdefault((round(x * SCALE), round(y * SCALE)), []).append((index, side))
    edges = []
    for (x, y), entries in endpoints.items():
        for dx in range(-max_dx, max_dx + 1):
            for index, side in entries:
                for other, other_side in endpoints.get((x + dx, y + spacing_px), ()):
                    edges.append((math.hypot(dx, spacing_px), index, side, other, other_side))

    parent = list(range(len(paths)))
    links = {}

    def root(index):
        while parent[index] != index:
            index = parent[index]
        return index

    for _, index, side, other, other_side in sorted(edges):
        first, second = (index, side), (other, other_side)
        if first in links or second in links:
            continue
        root_a, root_b = root(index), root(other)
        a = paths[index][0 if side == 0 else -1]
        b = paths[other][0 if other_side == 0 else -1]
        if root_a == root_b or not link_is_safe(a, b):
            continue
        parent[root_a] = root_b
        links[first], links[second] = second, first

    routes = []
    visited = set()
    for index in range(len(paths)):
        if index in visited:
            continue
        # Find the free end of this chain before traversing it.
        current, entry = index, 0
        while (current, entry) in links:
            current, entry = links[(current, entry)]
            entry = 1 - entry
        route = {"points": [], "stroke_indices": [], "stroke_entry_sides": []}
        while True:
            if current in visited:
                raise RuntimeError("Cyclic or repeated flat-bit candidate route")
            visited.add(current)
            route["stroke_indices"].append(current)
            route["stroke_entry_sides"].append(entry)
            route["points"].extend(paths[current] if entry == 0 else reversed(paths[current]))
            next_link = links.get((current, 1 - entry))
            if next_link is None:
                break
            current, entry = next_link
        routes.append(route)
    if len(visited) != len(paths):
        raise RuntimeError("Flat-bit routing lost candidate strokes")
    return routes


def v_link_is_safe(clearance, a, b):
    a_xy, b_xy = np.asarray(a[:2]) * SCALE, np.asarray(b[:2]) * SCALE
    length = float(np.linalg.norm(b_xy - a_xy))
    if length <= 0:
        return False
    ax, ay = np.rint(a_xy).astype(int)
    bx, by = np.rint(b_xy).astype(int)
    da, db = clearance[ay, ax], clearance[by, bx]
    r0 = (V_TIP_R + a[2] * V_SLOPE) * SCALE
    r1 = (V_TIP_R + b[2] * V_SLOPE) * SCALE
    crossing = np.clip((da - db + length) / (2 * length), 0, 1)
    return all(
        max(da - t * length, db - (1 - t) * length) - math.sqrt(2) / 2
        > r0 + t * (r1 - r0) + 1e-8
        for t in (0, crossing, 1)
    )


def sampled_v_links(routes, paths):
    result = np.zeros((SIZE, SIZE), dtype=float)
    for route in routes:
        ids, sides = route["stroke_indices"], route["stroke_entry_sides"]
        for left, left_side, right, right_side in zip(ids, sides, ids[1:], sides[1:]):
            a = np.asarray(paths[left][-1 if left_side == 0 else 0], dtype=float)
            b = np.asarray(paths[right][0 if right_side == 0 else -1], dtype=float)
            steps = max(1, math.ceil(np.linalg.norm(b[:2] - a[:2]) / 0.025))
            for t in np.linspace(0, 1, steps + 1):
                x, y, depth = a + t * (b - a)
                radius = V_TIP_R + depth * V_SLOPE
                lo_x = max(0, math.floor((x - radius) * SCALE))
                hi_x = min(SIZE - 1, math.ceil((x + radius) * SCALE))
                lo_y = max(0, math.floor((y - radius) * SCALE))
                hi_y = min(SIZE - 1, math.ceil((y + radius) * SCALE))
                rows, cols = np.mgrid[lo_y:hi_y + 1, lo_x:hi_x + 1]
                distance = np.hypot(cols / SCALE - x, rows / SCALE - y)
                cut = np.clip(depth - np.maximum(0, distance - V_TIP_R) / V_SLOPE, 0, depth)
                view = result[lo_y:hi_y + 1, lo_x:hi_x + 1]
                np.maximum(view, cut, out=view)
    return result


def sampled_flat_sweep(routes):
    swept = np.zeros((SIZE, SIZE), dtype=bool)
    radius = FLAT_R * SCALE
    for route in routes:
        points = np.asarray(route["points"]) * SCALE
        segments = list(zip(points, points[1:]))
        for a, b in segments:
            lo = np.maximum(np.floor(np.minimum(a, b) - radius).astype(int), 0)
            hi = np.minimum(np.ceil(np.maximum(a, b) + radius).astype(int), SIZE - 1)
            rows, cols = np.mgrid[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
            delta = b - a
            length_squared = np.dot(delta, delta)
            if length_squared:
                t = np.clip(((cols - a[0]) * delta[0] + (rows - a[1]) * delta[1]) / length_squared, 0, 1)
            else:
                t = 0
            distance_squared = (cols - a[0] - t * delta[0])**2 + (rows - a[1] - t * delta[1])**2
            swept[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1] |= distance_squared <= radius**2
    return swept


def unsafe_horizontal_steps(clearance, levels):
    left = clearance[:, :-1]
    right = clearance[:, 1:]
    left_levels = levels[:, :-1]
    right_levels = levels[:, 1:]
    active = (left_levels > 0) & (right_levels > 0)
    left_radius = (V_TIP_R + left_levels * 0.1 * V_SLOPE) * SCALE
    right_radius = (V_TIP_R + right_levels * 0.1 * V_SLOPE) * SCALE
    t = np.clip((left - right + 1) / 2, 0, 1)
    lower_bound = np.maximum(left - t, right - (1 - t)) - math.sqrt(2) / 2
    tool_radius = left_radius + t * (right_radius - left_radius)
    return active & (lower_bound <= tool_radius + 1e-8)


def conservative_v_depths(clearance, near_need):
    safe_radius = (clearance - math.sqrt(2) / 2 - 1e-8) / SCALE
    levels = np.clip(np.floor((safe_radius - V_TIP_R) / V_SLOPE * 10), 0, 5).astype(np.int8)
    levels[~near_need] = 0
    for _ in range(5):
        unsafe = unsafe_horizontal_steps(clearance, levels)
        if not unsafe.any():
            return levels.astype(float) / 10
        affected = np.zeros(levels.shape, dtype=bool)
        affected[:, :-1] |= unsafe
        affected[:, 1:] |= unsafe
        levels[affected] -= 1
    if unsafe_horizontal_steps(clearance, levels).any():
        raise RuntimeError("Unable to prove continuous V-bit clearance within the raster target")
    return levels.astype(float) / 10


def sampled_v_depth(selected_depth):
    v_depth = np.zeros(selected_depth.shape, dtype=float)
    for level in (0.5, 0.4, 0.3, 0.2, 0.1):
        seeds = np.isclose(selected_depth, level)
        if not seeds.any():
            continue
        distances = distances_to_centers(seeds)
        cut = np.clip(level - np.maximum(0, distances - V_TIP_R) / V_SLOPE, 0, level)
        v_depth = np.maximum(v_depth, cut)
    return v_depth


def vector_part():
    root = ET.parse(HERE / 'layers' / '07-hanging-tab.svg').getroot()
    if root.get('viewBox') != '0 0 1200 1200' or root.get('width') != '120mm':
        raise RuntimeError("Unexpected hanging-tab coordinate system")
    if any(e.get('transform') for e in root.iter()):
        raise RuntimeError("Transformed hanging-tab geometry is unsupported")
    elements = {e.get('id'): e for e in root.iter() if e.get('id')}
    edge = elements['tab-edge']
    if elements['tab-fill'].get('d') != edge.get('d') + ' Z':
        raise RuntimeError("Hanging-tab fill and edge no longer describe the same shape")
    if re.sub(r'[MLC]|[-+]?(?:\d*\.\d+|\d+)|[\s,]+', '', edge.get('d')):
        raise RuntimeError("Unsupported hanging-tab path command")
    tokens = re.findall(r'[MLC]|[-+]?(?:\d*\.\d+|\d+)', edge.get('d'))
    points = []
    current = None
    i = 0
    while i < len(tokens):
        command = tokens[i]
        count = {'M': 2, 'L': 2, 'C': 6}.get(command)
        if count is None or i + count >= len(tokens):
            raise RuntimeError("Unsupported hanging-tab path")
        values = [float(t) for t in tokens[i + 1:i + count + 1]]
        if command in ('M', 'L'):
            current = (values[0], values[1])
            points.append(current)
        else:
            if current is None:
                raise RuntimeError("Invalid hanging-tab path")
            p0 = np.array(current)
            p1, p2, p3 = (np.array(values[j:j + 2]) for j in (0, 2, 4))
            for t in np.linspace(0, 1, 81)[1:]:
                p = (1 - t)**3 * p0 + 3 * (1 - t)**2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3
                points.append(tuple(p))
            current = tuple(p3)
        i += count + 1
    points = [(x / 10 + 5, y / 10 + 5) for x, y in points]
    border = LineString(points).buffer(float(edge.get('stroke-width')) / 20, quad_segs=64)
    tab = Polygon(points).union(border)
    body = Point(65, 65).buffer(50, quad_segs=512)
    polygon = body.union(tab)
    if not polygon.is_valid or polygon.geom_type != 'Polygon':
        raise RuntimeError("Invalid or disconnected part silhouette")
    hole = elements['hanging-hole']
    hole_center = (float(hole.get('cx')) / 10 + 5, float(hole.get('cy')) / 10 + 5)
    hole_diameter = float(hole.get('r')) / 5
    if hole_diameter <= 2 * FLAT_R:
        raise RuntimeError("Hanging hole must be wider than the flat cutter")
    return polygon, hole_center, hole_diameter


def profile_paths():
    polygon, hole_center, hole_diameter = vector_part()
    offset = polygon.buffer(FLAT_R, quad_segs=128)
    line = LineString(offset.exterior.coords)
    # Centers of four 4 mm finished bridges, away from the hanging tab.
    tab_centers = []
    for angle in (45, 135, 225, 315):
        a = math.radians(angle)
        tab_centers.append(line.project(Point(65 + 50 * math.cos(a), 65 + 50 * math.sin(a))))
    shallow = Image.new("1", (SIZE, SIZE))
    deep = Image.new("1", (SIZE, SIZE))
    shallow_draw, deep_draw = ImageDraw.Draw(shallow), ImageDraw.Draw(deep)
    sections = []
    half_tab_centerline = (4 + 2 * FLAT_R) / 2
    bounds = sorted({0.0, line.length, *[
        (t + sign * half_tab_centerline) % line.length
        for t in tab_centers for sign in (-1, 1)
    ]})
    through_segments = []
    for start, end in zip(bounds, bounds[1:]):
        mid = (start + end) / 2
        distance = min(min(abs(mid - t), line.length - abs(mid - t)) for t in tab_centers)
        is_tab = distance <= half_tab_centerline
        segment = substring(line, start, end)
        coords = list(segment.coords)
        p = [(round(x * SCALE), round(y * SCALE)) for x, y in coords]
        shallow_draw.line(p, fill=1, width=1)
        if not is_tab:
            deep_draw.line(p, fill=1, width=1)
            through_segments.append(segment)
        depth = TAB_DEPTH if is_tab else THROUGH
        sections.append({"depth": depth, "points": [[round(x, 6), round(y, 6)] for x, y in coords]})
    vector_overlap = unary_union([s.buffer(FLAT_R, quad_segs=128) for s in through_segments]).intersection(polygon).area
    if vector_overlap > 0.01:
        raise RuntimeError(f"Through-profile vector sweep gouges {vector_overlap:.4f} mm²")
    deep_swept = unary_union(through_segments).buffer(FLAT_R, quad_segs=128)
    bridge_lengths = [
        LineString(section['points']).difference(deep_swept).length
        for section in sections if section['depth'] == TAB_DEPTH
    ]
    if len(bridge_lengths) != 4 or any(abs(length - 4) > 0.02 for length in bridge_lengths):
        raise RuntimeError(f"Holding bridge lengths differ from 4 mm: {bridge_lengths}")
    tab_points = [[line.interpolate(t).x, line.interpolate(t).y] for t in tab_centers]
    return (
        np.array(shallow, dtype=bool), np.array(deep, dtype=bool), sections,
        polygon, tab_centers, tab_points, vector_overlap, bridge_lengths,
        hole_center, hole_diameter,
    )


def hole_centers(center, diameter):
    result = Image.new("1", (SIZE, SIZE))
    draw = ImageDraw.Draw(result)
    radius = (diameter - 2 * FLAT_R) / 2
    points = [
        [center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)]
        for a in np.linspace(0, 2 * math.pi, 721)
    ]
    sweep = LineString(points).buffer(FLAT_R, quad_segs=128)
    target = Point(center).buffer(diameter / 2, quad_segs=128)
    error = sweep.symmetric_difference(target).area
    if error > 0.01:
        raise RuntimeError(f"Hanging-hole sweep differs from target by {error:.4f} mm²")
    draw.line([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=1, width=1)
    return np.array(result, dtype=bool), points, error


def paint_depth(depth):
    wood = np.array([239, 218, 180], dtype=float)
    engraved = np.array([134, 83, 47], dtype=float)
    through = np.array([42, 48, 56], dtype=float)
    first = np.clip(depth / ENGRAVE, 0, 1)[..., None]
    second = np.clip((depth - ENGRAVE) / (THROUGH - ENGRAVE), 0, 1)[..., None]
    color = wood * (1 - first) + engraved * first
    color = color * (1 - second) + through * second
    return Image.fromarray(np.uint8(np.clip(color, 0, 255)))


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    engraving, tab = rasterize()
    target = (engraving[:, :, 3] > 127) & (engraving[:, :, :3].max(axis=2) < 128)
    y, x = np.indices((SIZE, SIZE))
    part = ((x - 650) ** 2 + (y - 650) ** 2 <= 500 ** 2) | (tab[:, :, 3] > 127)
    target &= part
    _, flat_paths = scanlines(target, FLAT_R, 7)
    flat_routes = connect_paths(flat_paths, 7, 24, lambda a, b: flat_link_is_safe(target, a, b))
    flat_path_length = planar_path_length(flat_paths)
    flat_single_points = sum(path[0] == path[-1] for path in flat_paths)
    flat_isolated_points = sum(
        len(route["stroke_indices"]) == 1 and route["points"][0] == route["points"][-1]
        for route in flat_routes
    )
    flat_route_length = planar_path_length([route["points"] for route in flat_routes])
    flat_depth = np.where(sampled_flat_sweep(flat_routes), ENGRAVE, 0)
    clearance = distance_transform_edt(target)
    needs_cut = target & (flat_depth < ENGRAVE - 0.01)
    near_need = distance_transform_edt(~needs_cut) <= V_R * SCALE + math.sqrt(2) / 2
    selected_depth = conservative_v_depths(clearance, near_need)
    v_paths = variable_depth_paths(selected_depth)
    v_routes = connect_paths(v_paths, 1, 3, lambda a, b: v_link_is_safe(clearance, a, b))
    v_path_length = planar_path_length(v_paths)
    v_route_length = planar_path_length([route["points"] for route in v_routes])
    v_single_points = sum(len(path) == 1 for path in v_paths)
    v_isolated_points = sum(len(route["points"]) == 1 for route in v_routes)
    v_depth = np.maximum(sampled_v_depth(selected_depth), sampled_v_links(v_routes, v_paths))
    engraving_depth = np.maximum(flat_depth, v_depth)
    outside = int(np.count_nonzero((engraving_depth > 1e-8) & ~target))
    if outside:
        raise RuntimeError(f"Raster simulation removes {outside} pixels outside the engraving target")
    (shallow, deep, profile, polygon, tab_centers, tab_points, vector_overlap,
     bridge_lengths, hole_center, hole_diameter) = profile_paths()
    if not polygon.covers(Point(hole_center).buffer(hole_diameter / 2)):
        raise RuntimeError("The hanging hole extends outside the modeled part")
    if sum(section["depth"] == TAB_DEPTH for section in profile) != 4:
        raise RuntimeError("Expected four holding-tab sections")
    hole, hole_path, hole_error = hole_centers(hole_center, hole_diameter)
    depth = engraving_depth.copy()
    shallow_sweep = distances_to_centers(shallow) <= FLAT_R
    depth[shallow_sweep] = np.maximum(depth[shallow_sweep], TAB_DEPTH)
    deep_sweep = distances_to_centers(deep) <= FLAT_R
    hole_sweep = distances_to_centers(hole) <= FLAT_R
    profile_overlap = int(np.count_nonzero(deep_sweep & part))
    inner_overlap = int(np.count_nonzero(deep_sweep & (distance_transform_edt(part) > 1)))
    depth[deep_sweep | hole_sweep] = THROUGH
    full_floor = int(np.count_nonzero((engraving_depth >= ENGRAVE - 0.01) & target))
    target_pixels = int(np.count_nonzero(target))
    partial = int(np.count_nonzero((engraving_depth > 0) & target))
    coarse_depths = selected_depth.copy()
    coarse_depths[1::2] = 0
    coarse_paths = variable_depth_paths(coarse_depths)
    coarse_sweep = np.maximum(flat_depth, sampled_v_depth(coarse_depths))
    coarse_full_floor = int(np.count_nonzero((coarse_sweep >= ENGRAVE - 0.01) & target))
    coarse_partial = int(np.count_nonzero((coarse_sweep > 0) & target))
    coarse_length = planar_path_length(coarse_paths)
    # Historical prototype and community figures are comparison inputs only.
    # They are not verified for this cutter, machine, or physical setup.
    profile_passes = depth_passes(THROUGH, 0.75)
    v_passes = depth_passes(ENGRAVE, 0.2)
    v_pass_estimates = []
    previous_depth = 0
    for pass_depth in v_passes:
        active_routes = [
            route for route in v_routes
            if max(point[2] for point in route["points"]) > previous_depth + 1e-8
        ]
        length = planar_path_length([route["points"] for route in active_routes])
        v_pass_estimates.append({
            "depth_cap_mm": pass_depth,
            "route_count": len(active_routes),
            "cutting_length_mm": length,
        })
        previous_depth = pass_depth
    v_reference_minutes = sum(item["cutting_length_mm"] for item in v_pass_estimates) / 50
    image = paint_depth(depth)
    draw = ImageDraw.Draw(image)
    for tx, ty in tab_points:
        cx, cy = round(tx * SCALE), round(ty * SCALE)
        draw.ellipse((cx - 17, cy - 17, cx + 17, cy + 17), outline="#00b6f5", width=4)
    image.save(HERE / 'tool-aware-depth-study.png')
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE / 'layers').glob('*.svg')}
    plan = {
        "status": "PREVIEW ONLY - not a CNC job",
        "study_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "artwork_rasterizer_sha256": hashlib.sha256((HERE / 'tool-aware-raster.html').read_bytes()).hexdigest(),
        "resolution_mm": 1 / SCALE,
        "coordinate_frame": "130 mm raster; top-left image origin, not machine work zero",
        "stock_mm": [152.4, 203.2, 3.25],
        "engraving_depth_mm": ENGRAVE,
        "through_depth_mm": THROUGH,
        "flat_diameter_mm": FLAT_R * 2,
        "v_angle_degrees": 30,
        "v_tip_diameter_mm": V_TIP_R * 2,
        "v_width_at_depth_mm": V_R * 2,
        "flat_spacing_mm": 0.7,
        "flat_candidate_cutting_length_mm": flat_path_length,
        "flat_single_point_strokes": flat_single_points,
        "flat_isolated_point_routes": flat_isolated_points,
        "flat_connected_candidate_length_mm": flat_route_length,
        "v_spacing_mm": 0.1,
        "v_candidate_cutting_length_mm": v_path_length,
        "v_connected_candidate_length_mm": v_route_length,
        "v_single_point_strokes": v_single_points,
        "v_isolated_point_routes": v_isolated_points,
        "coarse_v_comparison_only": {
            "spacing_mm": 0.2,
            "stroke_count": len(coarse_paths),
            "cutting_length_mm": coarse_length,
            "full_depth_area_mm2": coarse_full_floor / SCALE**2,
            "any_depth_area_mm2": coarse_partial / SCALE**2,
        },
        "unverified_pass_study": {
            "flat_engraving_depths_mm": [ENGRAVE],
            "flat_profile_and_hole_depths_mm": profile_passes,
            "flat_profile_tab_depth_cap_mm": TAB_DEPTH,
            "v_depth_passes": v_pass_estimates,
            "flat_cut_feed_reference_mm_min": 300,
            "flat_plunge_feed_reference_mm_min": 100,
            "v_cut_feed_reference_mm_min": 50,
            "v_plunge_feed_reference_mm_min": 30,
            "v_cutting_time_lower_bound_min_at_reference_feed": v_reference_minutes,
            "spindle_observed_by_operator_rpm": 1000,
            "safe_z_mm": None,
            "status": "UNVERIFIED COMPARISON ONLY - not an approved or machine-ready plan",
        },
        "holding_tab_finished_length_mm": 4,
        "holding_tab_remaining_thickness_mm": 1,
        "hanging_hole_diameter_mm": hole_diameter,
        "hanging_hole_center_mm": hole_center,
        "hanging_hole_sweep_area_error_mm2": hole_error,
        "source_sha256": digests,
        "flat_engraving_centerlines": flat_paths,
        "flat_connected_candidate_routes": flat_routes,
        "v_engraving_centerlines_xyz_positive_depth": v_paths,
        "v_connected_candidate_routes": v_routes,
        "hanging_hole_centerline": hole_path,
        "outer_profile_sections": profile,
        "profile_length_mm": round(polygon.exterior.length, 3),
        "tab_center_stations_mm": tab_centers,
        "tab_marker_centers_mm": tab_points,
        "holding_tab_protected_centerline_lengths_mm": bridge_lengths,
        "target_area_mm2": target_pixels / SCALE**2,
        "full_depth_area_mm2": full_floor / SCALE**2,
        "any_depth_area_mm2": partial / SCALE**2,
        "outside_target_pixels": outside,
        "profile_through_sweep_inside_rasterized_part_mm2": profile_overlap / SCALE**2,
        "profile_through_sweep_over_0_1mm_inside_part_mm2": inner_overlap / SCALE**2,
        "profile_vector_sweep_overlap_mm2": vector_overlap,
    }
    (HERE / 'tool-aware-preview-only.json').write_text(json.dumps(plan, separators=(',', ':')), encoding='utf-8')
    pct = full_floor / target_pixels * 100
    any_pct = partial / target_pixels * 100
    page = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Dome Riders cutter-sweep study</title>
<style>body{{font:16px Segoe UI,sans-serif;background:#f2f4f6;color:#17212b;margin:1.2rem}}
main{{max-width:1050px;margin:auto}}img{{width:min(100%,780px);display:block;background:white}}
.warning{{background:#fff1cf;padding:1rem;border-left:5px solid #aa6700}}li{{margin:.4rem 0}}
code{{font-size:.9em}}</style><main><h1>Cutter-sweep study</h1>
<p class="warning"><b>Provisional preview, not a CNC job.</b> This raster study depicts candidate
cutter sweeps, not a validated machining plan. Do not cut from it or approve it as machine-ready.</p>
<img src="tool-aware-depth-study.png" alt="Top view of simulated depth from cutter sweeps">
<p>Light wood = uncut; brown = up to 0.5 mm engraving; dark = deeper removal,
including the hole and cutout. Blue circles mark the four holding-tab locations.
The view is a 130 mm square, not the entire stock.</p>
<ul><li>100 mm body, rounded hanging tab and {hole_diameter:g} mm hole; 152.4 × 203.2 × 3.25 mm plywood.</li>
<li>Sequence: flat-bit engraving, V-bit detail, then flat-bit hole and cutout.
Use separate tool setups with a common XY origin and re-zero Z after each change.</li>
<li>Black artwork is the engraving target. Flat 3.175 mm bit, then 30° V-bit
(0.1 mm tip), at up to 0.5 mm depth. V-bit width at 0.5 mm: {V_R * 2:.3f} mm;
the candidate V-bit strokes use shallower depths where the raster feature is too narrow.</li>
<li>Flat-bit hole and outside profile: 3.35 mm depth, including 0.1 mm breakthrough;
four 4 mm holding tabs leave 1 mm stock thickness.</li>
<li>0.1 mm pixel resolution; conservative raster scanline centers at 0.7 mm for the
flat bit and 0.1 mm for the V-bit. Sampled center-point sweeps estimate that
{pct:.1f}% of the raster engraving target reaches within 0.01 mm of full depth;
{any_pct:.1f}% sees any cut. This display does not show the exact continuous sweep.
Tiny retained gaps and
partial-depth V-bit edges require review. The study contains {len(v_paths):,}
separate original V-bit strokes, including {v_single_points} single-point strokes,
joined into {len(v_routes):,} routes spanning {v_route_length / 1000:.1f} m before
retractions or additional passes; {v_isolated_points} are isolated points.
The flat-bit candidate joins {len(flat_paths):,} original strokes
({flat_single_points} single-point strokes) into {len(flat_routes):,} connected
routes spanning {flat_route_length / 1000:.2f} m, including {flat_isolated_points}
isolated points. Raster-cell geometry bounds these joins, but entry, retracts
and passes remain unplanned; isolated cuts are not production-ready plunges.
Continuous engraving clearance is bounded against the raster target; the raster
is not an exact vector or physical safety check.
Entry, retraction, tool changes and the full pass-by-pass motion are not planned.</li></ul>
<h2>Pass schedule for discussion only</h2>
<p class="warning"><b>Not verified or approved.</b> This is a proposed pass
structure for review, not a CNC program or a recommendation to start the machine.
Feeds, stepdowns, safe Z, clamp and holder clearances, stock placement and
the machine's measured envelope still need operator confirmation.</p>
<ul><li>Flat engraving: one 0.5 mm pass. Flat-bit hole and profile: depth caps
{", ".join(f"{depth:g}" for depth in profile_passes)} mm, with the four holding
tabs capped at {TAB_DEPTH:g} mm.</li>
<li>V-bit engraving: depth caps {", ".join(f"{depth:g}" for depth in v_passes)}
mm; shallower features retain their individual target depth. This comparison
repeats only routes with remaining depth on later passes.</li>
<li>Historical ornament prototype reference: 300 mm/min cut and 100 mm/min
plunge for the flat bit; a <a href="https://github.com/m-anish/cnc3018-settings/blob/main/cnc_feed_rates_table.md">community 3018 softwood/MDF table</a> lists 50 mm/min
cut, 30 mm/min plunge and 0.2 mm depth for a 0.1 mm V-bit tip at a different,
unverified spindle setting. Neither reference is validated for this plywood
or the operator-reported 1,000 RPM spindle.</li>
<li>At 50 mm/min the proposed V-bit passes alone would require at least
{v_reference_minutes / 60:.1f} hours of cutting movement. Retractions, plunges,
acceleration, tool changes and the flat-bit work would add time.</li>
<li>Work XY zero was reported at the lower-left stock corner, with the 8-inch side
along X; Z0 was set at the stock top with the V-bit installed. Preserve XY and
re-establish Z after each tool change. Position within the stock is not yet fixed.</li></ul>
<p>For comparison only, doubling V-bit row spacing to 0.2 mm reduces the candidate
cutting length to {coarse_length / 1000:.1f} m, but sampled near-full-depth coverage
falls to {coarse_full_floor / target_pixels * 100:.1f}% and any-depth coverage to
{coarse_partial / target_pixels * 100:.1f}%. This alternative is not shown in the
image or selected for machining.</p>
<p class="warning"><b>Not yet validated:</b> the 99 mm artwork rim versus 100 mm
cutout leaves approximately 0.5 mm outside the engraved rim. The palm-to-ring gaps
are about 0.24 mm. The cutout, hole, tabs, all tool sweeps, thin plywood flex,
fixture clearance, cut order, tool reach, and edge strength require independent CAM
verification. Feeds, spindle speed, pass depths, safe Z, stock placement and
machine envelope remain unconfirmed. The vector profile sweep intersects the
modeled part by {vector_overlap:.4f} mm². The display's rasterized sweep overlaps
{profile_overlap / SCALE**2:.2f} mm² at pixel edges (overlap more than 0.1 mm
inside: {inner_overlap / SCALE**2:.2f} mm²); both remain approximations.
Placement and work zero are not specified.
This image is not a guarantee of surface finish, workholding, or safety.</p>
<p>The operator reports the plywood will be clamped and suspended 4 mm above the
workbed. Actual clamp, cutter and workbed clearances, stock support and material
flex remain to be checked. Work zero will be set by the operator in the GUI.</p>
<p>The hole and outer tab outline are cut features, not engraving targets.
The JSON is candidate centerline data for inspection only, not G-code. Regenerate
this study if the artwork changes.</p></main></html>"""
    (HERE / 'tool-aware-preview.html').write_text(page, encoding='utf-8')
    print(f"Preview built: full depth {pct:.1f}%, any cut {any_pct:.1f}%, outside target {outside} px")
    print(f"Flat scanlines: {len(flat_paths)}, V-bit scanlines: {len(v_paths)}, profile sections: {len(profile)}")


if __name__ == '__main__':
    main()
