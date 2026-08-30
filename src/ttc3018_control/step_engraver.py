"""Planar STEP-to-G-code generation for bounded 2.5D machining."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from .step_geometry import Point2D, PlanarLoop, PlanarSurfacePatch, StepPlanarModel
from .step_verification import StepVerification, verify_flat_clearing_paths
from .text_engraver import Stroke, _fmt


STEP_MODES = ("Engraving", "Detected feature", "Planar surface", "Profile cutout", "Outside contour", "Inside contour", "Pocket", "Hole")
STEP_ORIENTATIONS = ("Top (XY)", "Top (YX)")
STEP_ZERO_LOCATIONS = ("Lower-left", "Center")


@dataclass(frozen=True)
class StepMachining:
    gcode: str
    mode: str
    width: float
    height: float
    stock_width: float
    stock_height: float
    tool_diameter: float
    depth: float
    passes: int
    stroke_count: int
    strokes: tuple[Stroke, ...]
    model_strokes: tuple[Stroke, ...] = ()
    stock_thickness: float | None = None
    breakthrough: float = 0.0
    tab_count: int = 0
    tab_width: float = 0.0
    tab_height: float = 0.0
    feature_summary: str = ""
    placement_offset_x: float = 0.0
    placement_offset_y: float = 0.0
    surface_paths: tuple[tuple[tuple[float, float, float], ...], ...] = ()
    cutting_distance: float = 0.0
    rapid_xy_distance: float = 0.0
    retract_count: int = 0
    verification: StepVerification | None = None


def generate_step_gcode(
    model: StepPlanarModel,
    *,
    mode: str = "Engraving",
    orientation: str = "Top (XY)",
    stock_width: float | None = None,
    stock_height: float | None = None,
    zero_location: str = "Lower-left",
    tool_diameter: float = 3.175,
    depth: float = -0.5,
    passes: int = 1,
    safe_z: float = 3.0,
    cut_feed: float = 300.0,
    plunge_feed: float = 100.0,
    spindle_rpm: int | None = None,
    stock_thickness: float | None = None,
    breakthrough: float = 0.2,
    tab_count: int = 4,
    tab_width: float = 4.0,
    tab_height: float = 0.8,
) -> StepMachining:
    resolved_thickness = float(stock_thickness) if stock_thickness is not None else float(model.thickness)
    if mode == "Profile cutout":
        depth = -(resolved_thickness + breakthrough)
    elif mode == "Detected feature":
        if not model.features:
            raise ValueError("No raised boss or recessed feature was detected on the selected machining face")
        depth = -max(feature.depth for feature in model.features)
    _validate_settings(
        model, mode, orientation, zero_location, tool_diameter, depth, passes,
        safe_z, cut_feed, plunge_feed, spindle_rpm,
        resolved_thickness, breakthrough, tab_count, tab_width, tab_height,
    )
    loops = tuple(_transform_loop(loop, orientation) for loop in model.loops)
    loop_bounds = _loop_bounds(loops)
    model_width, model_height = loop_bounds[4], loop_bounds[5]
    resolved_stock_width = float(stock_width) if stock_width is not None else model_width + tool_diameter
    resolved_stock_height = float(stock_height) if stock_height is not None else model_height + tool_diameter
    if resolved_stock_width <= 0 or resolved_stock_height <= 0:
        raise ValueError("Stock width and height must be greater than zero")
    if resolved_stock_width < model_width - 0.001 or resolved_stock_height < model_height - 0.001:
        raise ValueError("Stock must be at least as large as the imported top-face geometry")

    offset_x = 0.0 if zero_location == "Lower-left" else (resolved_stock_width - model_width) / 2
    offset_y = 0.0 if zero_location == "Lower-left" else (resolved_stock_height - model_height) / 2
    loops = tuple(_translate_loop(loop, offset_x, offset_y) for loop in loops)
    region = _even_odd_region(loops)
    surface_paths: tuple[tuple[tuple[float, float, float], ...], ...] = ()
    if mode == "Planar surface":
        surface_paths, depth = _planar_surface_paths(
            model.surface_patches, orientation, region, tool_diameter, offset_x, offset_y
        )
        if not surface_paths:
            raise ValueError("No accessible planar surface path could be generated from the imported geometry")
        if not -20 <= depth < 0:
            raise ValueError("The imported planar surface exceeds the supported 20 mm machining depth")
    profile_paths = _profile_cutout_paths(region, tool_diameter) if mode == "Profile cutout" else []
    depth_paths: list[float] = []
    if mode == "Detected feature":
        detected_paths = _detected_feature_paths(model, loops, region, tool_diameter)
        strokes = [stroke for stroke, _depth in detected_paths]
        depth_paths = [-feature_depth for _stroke, feature_depth in detected_paths]
    elif mode == "Planar surface":
        strokes = [tuple((x, y) for x, y, _z in path) for path in surface_paths]
    else:
        strokes = [stroke for stroke, _is_outer in profile_paths] if profile_paths else _toolpaths(model, loops, region, mode, tool_diameter)
    if not strokes:
        raise ValueError(f"No usable {mode.lower()} toolpath could be generated from the imported geometry")
    placement_offset_x, placement_offset_y = _cutout_placement_offset(
        strokes, mode, zero_location
    )
    if placement_offset_x or placement_offset_y:
        strokes = [_translate_stroke(stroke, placement_offset_x, placement_offset_y) for stroke in strokes]
        depth_paths = list(depth_paths)
        profile_paths = [
            (_translate_stroke(stroke, placement_offset_x, placement_offset_y), is_outer)
            for stroke, is_outer in profile_paths
        ]
    if mode == "Detected feature":
        scheduled = _schedule_depth_paths(tuple(zip(strokes, depth_paths)))
        strokes = [stroke for stroke, _depth in scheduled]
        depth_paths = [depth for _stroke, depth in scheduled]
    elif mode == "Profile cutout":
        profile_paths = _schedule_profile_paths(profile_paths)
        strokes = [stroke for stroke, _is_outer in profile_paths]
    elif mode != "Planar surface":
        strokes = _schedule_strokes(strokes)
    _validate_strokes_inside_stock(strokes, resolved_stock_width, resolved_stock_height)
    verification = None
    if mode in {"Pocket", "Planar surface"}:
        verification = verify_flat_clearing_paths(strokes, region, tool_diameter / 2)
    cutting_distance, rapid_xy_distance, retract_count = _path_metrics(strokes, passes)

    commands = [
        "; Generated by TTC 3018 STEP 2.5D Machining",
        f"; Mode {mode}, tool {tool_diameter:g} mm, depth {depth:g} mm, passes {passes}",
        f"; Stock {resolved_stock_width:g} x {resolved_stock_height:g} mm, zero {zero_location}",
        "G21", "G17", "G90", "G94",
    ]
    if spindle_rpm is not None:
        commands.append(f"M3 S{spindle_rpm}")
    commands.append(f"G0 Z{safe_z:g}")
    if mode == "Profile cutout":
        commands.append(
            f"; Through cut: stock {resolved_thickness:g} mm + breakthrough {breakthrough:g} mm; "
            f"outer tabs {tab_count} x {tab_width:g} mm, height {tab_height:g} mm"
        )
    for pass_index in range(1, passes + 1):
        pass_depth = depth * pass_index / passes
        if mode == "Planar surface":
            for surface_path in surface_paths:
                first_x, first_y, first_z = surface_path[0]
                commands.extend((f"G0 X{_fmt(first_x)} Y{_fmt(first_y)}", f"G1 Z{_fmt(max(first_z, pass_depth))} F{plunge_feed:g}"))
                commands.extend(
                    f"G1 X{_fmt(x)} Y{_fmt(y)} Z{_fmt(max(z, pass_depth))} F{cut_feed:g}"
                    for x, y, z in surface_path[1:]
                )
                commands.append(f"G0 Z{safe_z:g}")
            continue
        paths = profile_paths if mode == "Profile cutout" else [(stroke, False) for stroke in strokes]
        for path_index, (stroke, is_outer) in enumerate(paths):
            target_depth = depth_paths[path_index] if mode == "Detected feature" else depth
            path_pass_depth = target_depth * pass_index / passes
            first = stroke[0]
            commands.extend((f"G0 X{_fmt(first[0])} Y{_fmt(first[1])}", f"G1 Z{_fmt(path_pass_depth)} F{plunge_feed:g}"))
            if is_outer and tab_count:
                tab_floor = -(resolved_thickness - tab_height)
                commands.extend(_tabbed_profile_commands(stroke, path_pass_depth, tab_floor, tab_count, tab_width, cut_feed, plunge_feed))
            else:
                commands.extend(f"G1 X{_fmt(x)} Y{_fmt(y)} F{cut_feed:g}" for x, y in stroke[1:])
            commands.append(f"G0 Z{safe_z:g}")
    commands.extend((f"G0 Z{safe_z:g}", "G0 X0 Y0", "M5", "M2"))
    return StepMachining(
        "\n".join(commands) + "\n",
        mode,
        model_width,
        model_height,
        resolved_stock_width,
        resolved_stock_height,
        tool_diameter,
        depth,
        passes,
        len(strokes),
        tuple(strokes),
        tuple(
            _loop_stroke(_translate_loop(loop, placement_offset_x, placement_offset_y))
            for loop in loops
        ),
        resolved_thickness if mode == "Profile cutout" else None,
        breakthrough if mode == "Profile cutout" else 0.0,
        tab_count if mode == "Profile cutout" else 0,
        tab_width if mode == "Profile cutout" else 0.0,
        tab_height if mode == "Profile cutout" else 0.0,
        ", ".join(f"{feature.kind} {feature.depth:.2f} mm" for feature in model.features)
        if mode == "Detected feature" else "",
        placement_offset_x,
        placement_offset_y,
        surface_paths,
        cutting_distance,
        rapid_xy_distance,
        retract_count,
        verification,
    )


def _validate_settings(
    model: StepPlanarModel,
    mode: str,
    orientation: str,
    zero_location: str,
    tool_diameter: float,
    depth: float,
    passes: int,
    safe_z: float,
    cut_feed: float,
    plunge_feed: float,
    spindle_rpm: int | None,
    stock_thickness: float,
    breakthrough: float,
    tab_count: int,
    tab_width: float,
    tab_height: float,
) -> None:
    if not model.loops:
        raise ValueError("The imported model contains no planar loops")
    for loop in model.loops:
        if len(loop.points) < 3:
            raise ValueError("Each imported planar loop must contain at least three points")
        if not all(math.isfinite(point.x) and math.isfinite(point.y) for point in loop.points):
            raise ValueError("Imported planar geometry contains a non-finite coordinate")
        if loop.area <= 1e-7:
            raise ValueError("Imported planar geometry contains a zero-area loop")
    if mode not in STEP_MODES:
        raise ValueError("Unknown STEP machining mode")
    if orientation not in STEP_ORIENTATIONS:
        raise ValueError("Unknown STEP orientation")
    if zero_location not in STEP_ZERO_LOCATIONS:
        raise ValueError("Unknown work-zero location")
    if not 0.1 <= tool_diameter <= 20:
        raise ValueError("Tool diameter must be between 0.1 and 20 mm")
    if not -20 <= depth < 0:
        raise ValueError("Machining depth must be below work Z0 and no deeper than 20 mm")
    if not isinstance(passes, int) or not 1 <= passes <= 100:
        raise ValueError("Depth passes must be a whole number from 1 to 100")
    if not 0.1 <= safe_z <= 100:
        raise ValueError("Safe Z must be between 0.1 and 100 mm")
    if not 1 <= cut_feed <= 3000 or not 1 <= plunge_feed <= 1000:
        raise ValueError("Cut feed must be 1–3000 and plunge feed 1–1000 mm/min")
    if spindle_rpm is not None and not 1 <= spindle_rpm <= 24000:
        raise ValueError("Spindle RPM must be between 1 and 24000")
    if mode == "Profile cutout":
        if not 0.1 <= stock_thickness <= 20:
            raise ValueError("Stock thickness must be between 0.1 and 20 mm")
        if not 0 <= breakthrough <= 2:
            raise ValueError("Breakthrough must be between 0 and 2 mm")
        if not isinstance(tab_count, int) or not 0 <= tab_count <= 12:
            raise ValueError("Tab count must be a whole number from 0 to 12")
        if tab_count and not 0.5 <= tab_width <= 20:
            raise ValueError("Tab width must be between 0.5 and 20 mm")
        if tab_count and not 0.1 <= tab_height < stock_thickness:
            raise ValueError("Tab height must be at least 0.1 mm and less than stock thickness")


def _transform_loop(loop: PlanarLoop, orientation: str) -> PlanarLoop:
    if orientation == "Top (XY)":
        return loop
    return PlanarLoop(tuple(Point2D(point.y, point.x) for point in loop.points))


def _transform_surface_patch(patch: PlanarSurfacePatch, orientation: str) -> PlanarSurfacePatch:
    if orientation == "Top (XY)":
        return patch
    return PlanarSurfacePatch(
        tuple(_transform_loop(loop, orientation) for loop in patch.loops),
        patch.b,
        patch.a,
        patch.c,
    )


def _translate_loop(loop: PlanarLoop, offset_x: float, offset_y: float) -> PlanarLoop:
    return PlanarLoop(tuple(Point2D(point.x + offset_x, point.y + offset_y) for point in loop.points))


def _translate_stroke(stroke: Stroke, offset_x: float, offset_y: float) -> Stroke:
    return tuple((x + offset_x, y + offset_y) for x, y in stroke)


def _translate_surface_patch(
    patch: PlanarSurfacePatch, offset_x: float, offset_y: float
) -> PlanarSurfacePatch:
    return PlanarSurfacePatch(
        tuple(_translate_loop(loop, offset_x, offset_y) for loop in patch.loops),
        patch.a,
        patch.b,
        patch.c - patch.a * offset_x - patch.b * offset_y,
    )


def _schedule_profile_paths(
    paths: Iterable[tuple[Stroke, bool]],
) -> list[tuple[Stroke, bool]]:
    tagged = tuple(paths)
    inner = [(stroke, False) for stroke, is_outer in tagged if not is_outer]
    outer = [(stroke, True) for stroke, is_outer in tagged if is_outer]
    return _schedule_tagged_strokes(inner) + _schedule_tagged_strokes(outer)


def _schedule_tagged_strokes(paths: Iterable[tuple[Stroke, bool]]) -> list[tuple[Stroke, bool]]:
    remaining = list(paths)
    result: list[tuple[Stroke, bool]] = []
    current = (0.0, 0.0)
    while remaining:
        choices = [
            (_best_stroke_orientation(stroke, current), index, is_outer)
            for index, (stroke, is_outer) in enumerate(remaining)
        ]
        oriented, index, is_outer = min(choices, key=lambda item: (math.dist(current, item[0][0]), item[1]))
        result.append((oriented, is_outer))
        current = oriented[-1]
        remaining.pop(index)
    if len(result) > 2 and len(result) <= 120:
        result = _improve_tagged_order(result)
    return result


def _improve_tagged_order(
    paths: list[tuple[Stroke, bool]],
) -> list[tuple[Stroke, bool]]:
    """Apply deterministic bounded 2-opt to reduce inter-path rapids."""
    best = list(paths)
    best_cost = _scheduled_path_cost(best)
    improved = True
    while improved:
        improved = False
        for start in range(1, len(best) - 1):
            for end in range(start + 1, len(best)):
                candidate = best[:start] + list(reversed(best[start:end + 1])) + best[end + 1:]
                cost = _scheduled_path_cost(candidate)
                if cost + 1e-7 < best_cost:
                    best, best_cost = candidate, cost
                    improved = True
                    break
            if improved:
                break
    return best


def _scheduled_path_cost(paths: Iterable[tuple[Stroke, bool]]) -> float:
    current = (0.0, 0.0)
    cost = 0.0
    for stroke, _is_outer in paths:
        oriented = _best_stroke_orientation(stroke, current)
        cost += math.dist(current, oriented[0])
        current = oriented[-1]
    return cost


def _schedule_strokes(strokes: Iterable[Stroke]) -> list[Stroke]:
    return [stroke for stroke, _is_outer in _schedule_tagged_strokes((stroke, False) for stroke in strokes)]


def _schedule_depth_paths(
    paths: Iterable[tuple[Stroke, float]],
) -> list[tuple[Stroke, float]]:
    remaining = list(paths)
    result: list[tuple[Stroke, float]] = []
    current = (0.0, 0.0)
    while remaining:
        choices = [
            (_best_stroke_orientation(stroke, current), index, depth)
            for index, (stroke, depth) in enumerate(remaining)
        ]
        oriented, index, depth = min(choices, key=lambda item: (math.dist(current, item[0][0]), item[1]))
        result.append((oriented, depth))
        current = oriented[-1]
        remaining.pop(index)
    return result


def _best_stroke_orientation(stroke: Stroke, current: tuple[float, float]) -> Stroke:
    if len(stroke) < 3:
        candidates = (stroke, tuple(reversed(stroke)))
    elif math.dist(stroke[0], stroke[-1]) <= 1e-7:
        body = stroke[:-1]
        candidates = tuple(
            tuple(direction[index:] + direction[:index] + (direction[index],))
            for direction in (body, tuple(reversed(body)))
            for index in range(len(body))
        )
    else:
        candidates = (stroke, tuple(reversed(stroke)))
    return min(candidates, key=lambda candidate: math.dist(current, candidate[0]))


def _cutout_placement_offset(
    strokes: Iterable[Stroke], mode: str, zero_location: str
) -> tuple[float, float]:
    """Anchor compensated outside-cut paths at the nonnegative work origin.

    The raw STEP loops are normalized independently from cutter compensation.
    For an outer contour/profile, compensation expands the cutter-center path
    outside the part, so a part starting at (0, 0) would otherwise generate
    negative XY coordinates.  The physical work-zero convention for these
    operations is the lower-left of the completed compensated envelope.  Other
    modes retain their existing part-relative placement because their cutter
    paths are inside the raw geometry and shifting them would move the part
    outside the declared stock.
    """
    if zero_location != "Lower-left" or mode not in {"Outside contour", "Profile cutout"}:
        return 0.0, 0.0
    points = [point for stroke in strokes for point in stroke]
    if not points:
        return 0.0, 0.0
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    return max(0.0, -min_x), max(0.0, -min_y)


def _loop_bounds(loops: Iterable[PlanarLoop]) -> tuple[float, float, float, float, float, float]:
    points = [point for loop in loops for point in loop.points]
    min_x = min(point.x for point in points)
    min_y = min(point.y for point in points)
    max_x = max(point.x for point in points)
    max_y = max(point.y for point in points)
    return min_x, min_y, max_x, max_y, max_x - min_x, max_y - min_y


def _even_odd_region(loops: Iterable[PlanarLoop]):
    region = GeometryCollection()
    for loop in loops:
        polygon = Polygon((point.x, point.y) for point in loop.points)
        if polygon.is_empty or polygon.area <= 1e-7:
            continue
        region = region.symmetric_difference(polygon)
    return region.buffer(0)


def _toolpaths(model: StepPlanarModel, loops: tuple[PlanarLoop, ...], region, mode: str, tool_diameter: float) -> list[Stroke]:
    if mode == "Engraving":
        return [_loop_stroke(loop) for loop in loops]
    radius = tool_diameter / 2
    if mode == "Outside contour":
        return _strokes_from_geometry(region.buffer(radius, join_style=2).boundary)
    if mode == "Inside contour":
        return _strokes_from_geometry(region.buffer(-radius, join_style=2).boundary)
    if mode == "Pocket":
        return _pocket_strokes(region, radius, tool_diameter)
    if mode == "Hole":
        return _hole_strokes(loops, tool_diameter)
    return []


def _profile_cutout_paths(region, tool_diameter: float) -> list[tuple[Stroke, bool]]:
    """Return compensated inner paths first and outer profiles last."""
    radius = tool_diameter / 2
    polygons = [region] if isinstance(region, Polygon) else list(region.geoms) if isinstance(region, MultiPolygon) else []
    inner_paths: list[tuple[Stroke, bool]] = []
    outer_paths: list[tuple[Stroke, bool]] = []
    for polygon in polygons:
        for ring in polygon.interiors:
            cutout = Polygon(ring)
            compensated = cutout.buffer(-radius, join_style=2)
            if compensated.is_empty:
                raise ValueError("An inner cutout is too small for the selected tool diameter")
            inner_paths.extend((stroke, False) for stroke in _strokes_from_geometry(compensated.boundary))
        compensated_outer = Polygon(polygon.exterior).buffer(radius, join_style=2)
        outer_paths.extend((stroke, True) for stroke in _strokes_from_geometry(compensated_outer.boundary))
    return inner_paths + outer_paths


def _detected_feature_paths(
    model: StepPlanarModel,
    loops: tuple[PlanarLoop, ...],
    region,
    tool_diameter: float,
) -> list[tuple[Stroke, float]]:
    """Generate removal paths that reproduce detected boss/recess topology."""
    radius = tool_diameter / 2
    recess_groups: dict[float, list[object]] = {}
    for feature in model.features:
        if feature.kind != "Recess":
            continue
        recess_groups.setdefault(round(feature.depth, 7), []).append(
            Polygon((point.x, point.y) for point in loops[feature.loop_index].points)
        )
    paths: list[tuple[Stroke, float]] = []
    for feature_depth, polygons in sorted(recess_groups.items()):
        paths.extend((stroke, feature_depth) for stroke in _pocket_strokes(unary_union(polygons), radius, tool_diameter))
    if any(feature.kind == "Raised boss" for feature in model.features):
        boss_depth = max(feature.depth for feature in model.features if feature.kind == "Raised boss")
        paths.extend((stroke, boss_depth) for stroke in _pocket_strokes(region, radius, tool_diameter))
    return paths


def _planar_surface_paths(
    patches: tuple[PlanarSurfacePatch, ...],
    orientation: str,
    region,
    tool_diameter: float,
    offset_x: float,
    offset_y: float,
) -> tuple[tuple[tuple[float, float, float], ...], float]:
    """Generate a bounded raster over accessible planar height-field patches."""
    transformed = tuple(
        _translate_surface_patch(_transform_surface_patch(patch, orientation), offset_x, offset_y)
        for patch in patches
    )
    if not transformed:
        return (), 0.0
    patch_regions = [(_even_odd_region(patch.loops), patch) for patch in transformed]
    current = region.buffer(-tool_diameter / 2, join_style=2)
    if current.is_empty:
        return (), 0.0
    min_x, min_y, max_x, max_y = current.bounds
    stepover = max(0.25, tool_diameter * 0.5)
    sample_step = max(0.2, tool_diameter * 0.25)
    row_count = max(1, int(math.ceil((max_y - min_y) / stepover))) + 1
    paths: list[tuple[tuple[float, float, float], ...]] = []
    for row_index in range(row_count):
        y = min(max_y, min_y + row_index * (max_y - min_y) / max(1, row_count - 1))
        scan = LineString(((min_x - stepover, y), (max_x + stepover, y)))
        spans = _strokes_from_geometry(current.intersection(scan))
        spans.sort(key=lambda span: min(point[0] for point in span))
        if row_index % 2:
            spans = [tuple(reversed(span)) for span in reversed(spans)]
        for span in spans:
            sampled = _sample_surface_span(span, patch_regions, sample_step)
            paths.extend(sampled)
    if not paths:
        return (), 0.0
    connected: list[tuple[tuple[float, float, float], ...]] = []
    active: tuple[tuple[float, float, float], ...] | None = None
    for path in paths:
        if active is not None and _safe_surface_link(current, active[-1], path[0]):
            active = active + (path[0],) + path[1:]
        else:
            if active is not None:
                connected.append(active)
            active = path
    if active is not None:
        connected.append(active)
    minimum_depth = min(point[2] for path in connected for point in path)
    return tuple(connected), minimum_depth


def _sample_surface_span(
    span: Stroke,
    patch_regions: list[tuple[object, PlanarSurfacePatch]],
    sample_step: float,
) -> list[tuple[tuple[float, float, float], ...]]:
    line = LineString(span)
    count = max(2, int(math.ceil(line.length / sample_step)) + 1)
    paths: list[tuple[tuple[float, float, float], ...]] = []
    active: list[tuple[float, float, float]] = []
    for index in range(count):
        point = line.interpolate(line.length * index / (count - 1))
        depth = _surface_depth_at(point.x, point.y, patch_regions)
        candidate = (float(point.x), float(point.y), depth) if depth is not None else None
        if candidate is None or (
            active
            and abs(candidate[2] - active[-1][2])
            > max(0.5, 1.75 * math.dist(candidate[:2], active[-1][:2]))
        ):
            if len(active) >= 2:
                paths.append(tuple(active))
            active = []
        if candidate is not None:
            active.append(candidate)
    if len(active) >= 2:
        paths.append(tuple(active))
    return paths


def _surface_depth_at(
    x: float,
    y: float,
    patch_regions: list[tuple[object, PlanarSurfacePatch]],
) -> float | None:
    point = Point(x, y)
    depths = [patch.height_at(x, y) for region, patch in patch_regions if region.covers(point)]
    return max(depths) if depths else None


def _safe_surface_link(
    region,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> bool:
    return (
        abs(end[2] - start[2]) <= max(0.5, 1.75 * math.dist(start[:2], end[:2]))
        and _safe_stay_down_link(region, start[:2], end[:2])
    )


def _path_metrics(strokes: Iterable[Stroke], passes: int) -> tuple[float, float, int]:
    """Measure the exact XY path set used by every depth pass."""
    paths = tuple(strokes)
    cutting_distance = sum(
        math.dist(start, end)
        for stroke in paths
        for start, end in zip(stroke, stroke[1:])
    ) * passes
    rapid_xy_distance = 0.0
    current = (0.0, 0.0)
    for _pass_index in range(passes):
        for stroke in paths:
            rapid_xy_distance += math.dist(current, stroke[0])
            current = stroke[-1]
        rapid_xy_distance += math.dist(current, (0.0, 0.0))
        current = (0.0, 0.0)
    return cutting_distance, rapid_xy_distance, len(paths) * passes


def _tabbed_profile_commands(
    stroke: Stroke,
    pass_depth: float,
    tab_floor: float,
    tab_count: int,
    tab_width: float,
    cut_feed: float,
    plunge_feed: float,
) -> list[str]:
    """Cut a closed outer profile while leaving evenly distributed tabs."""
    line = LineString(stroke)
    length = line.length
    if length <= tab_count * tab_width:
        raise ValueError("Outer profile is too short for the requested tab count and width")
    intervals = [
        ((index + 0.5) * length / tab_count - tab_width / 2, (index + 0.5) * length / tab_count + tab_width / 2)
        for index in range(tab_count)
    ]
    distances = {0.0, length}
    distances.update(min(length, max(0.0, value)) for interval in intervals for value in interval)
    for coordinate in stroke[1:-1]:
        distances.add(float(line.project(Point(coordinate))))
    ordered = sorted(distances)
    current_depth = pass_depth
    commands: list[str] = []
    for start, end in zip(ordered, ordered[1:]):
        midpoint = (start + end) / 2
        over_tab = any(low <= midpoint <= high for low, high in intervals)
        segment_depth = max(pass_depth, tab_floor) if over_tab else pass_depth
        if not math.isclose(segment_depth, current_depth, abs_tol=1e-6):
            commands.append(f"G1 Z{_fmt(segment_depth)} F{plunge_feed:g}")
            current_depth = segment_depth
        endpoint = line.interpolate(end)
        commands.append(f"G1 X{_fmt(endpoint.x)} Y{_fmt(endpoint.y)} F{cut_feed:g}")
    return commands


def _pocket_strokes(region, radius: float, tool_diameter: float) -> list[Stroke]:
    current = region.buffer(-radius, join_style=2)
    if current.is_empty:
        return []
    return _connected_scanline_strokes(current, max(0.25, tool_diameter * 0.7))


def _connected_scanline_strokes(region, stepover: float) -> list[Stroke]:
    """Clear a pocket with alternating lanes and only proven safe links.

    The old pocket strategy emitted every inward offset boundary separately,
    which caused a retract and a long rapid for each ring.  Scanlines make the
    broad clearing motion predictable and allow adjacent lanes to stay down.
    A link is added only when its straight swept segment is covered by the
    current compensated region; holes, islands, and disconnected components
    therefore remain protected and naturally produce separate strokes.
    """
    if region.is_empty:
        return []
    min_x, min_y, max_x, max_y = region.bounds
    height = max_y - min_y
    row_count = max(1, int(math.ceil(height / stepover))) + 1
    strokes: list[Stroke] = []
    active: Stroke | None = None
    tolerance_region = region.buffer(1e-7)
    for row_index in range(row_count):
        y = min_y if row_count == 1 else min(max_y, min_y + row_index * height / (row_count - 1))
        scan = LineString(((min_x - stepover, y), (max_x + stepover, y)))
        spans = _strokes_from_geometry(region.intersection(scan))
        spans = [span for span in spans if len(span) >= 2 and LineString(span).length > 1e-7]
        spans.sort(key=lambda span: min(point[0] for point in span))
        if row_index % 2:
            spans = [tuple(reversed(span)) for span in reversed(spans)]
        for span in spans:
            if active is not None and _safe_stay_down_link(tolerance_region, active[-1], span[0]):
                active = active + (span[0],) + span[1:]
            else:
                if active is not None:
                    strokes.append(active)
                active = span
    if active is not None:
        strokes.append(active)
    return strokes


def _safe_stay_down_link(region, start: tuple[float, float], end: tuple[float, float]) -> bool:
    if math.dist(start, end) <= 1e-7:
        return True
    return region.covers(LineString((start, end)))


def _hole_strokes(loops: tuple[PlanarLoop, ...], tool_diameter: float) -> list[Stroke]:
    if len(loops) < 2:
        raise ValueError("Hole mode requires at least one inner circular loop")
    strokes: list[Stroke] = []
    tool_radius = tool_diameter / 2
    outer = max(loops, key=lambda loop: loop.area)
    for loop in loops:
        if loop is outer:
            continue
        polygon = Polygon((point.x, point.y) for point in loop.points)
        circularity = 4 * math.pi * polygon.area / max(polygon.length * polygon.length, 1e-9)
        if circularity < 0.88:
            raise ValueError("Hole mode supports circular inner loops only")
        radius = math.sqrt(polygon.area / math.pi) - tool_radius
        if radius <= 0.05:
            raise ValueError("An imported hole must be larger than the selected tool diameter")
        center = polygon.centroid
        strokes.append(tuple((center.x + radius * math.cos(index * math.tau / 48), center.y + radius * math.sin(index * math.tau / 48)) for index in range(49)))
    return strokes


def _loop_stroke(loop: PlanarLoop) -> Stroke:
    first = loop.points[0]
    return tuple((point.x, point.y) for point in loop.points + (first,))


def _strokes_from_geometry(geometry) -> list[Stroke]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        strokes = [_ring_stroke(geometry.exterior)]
        strokes.extend(_ring_stroke(ring) for ring in geometry.interiors)
        return strokes
    if isinstance(geometry, MultiPolygon):
        return [stroke for polygon in geometry.geoms for stroke in _strokes_from_geometry(polygon)]
    if isinstance(geometry, LineString):
        return [_line_stroke(geometry)]
    if isinstance(geometry, MultiLineString):
        return [_line_stroke(line) for line in geometry.geoms]
    if isinstance(geometry, GeometryCollection):
        return [stroke for item in geometry.geoms for stroke in _strokes_from_geometry(item)]
    return []


def _ring_stroke(ring) -> Stroke:
    return tuple((float(x), float(y)) for x, y in ring.coords)


def _line_stroke(line: LineString) -> Stroke:
    return tuple((float(x), float(y)) for x, y in line.coords)


def _validate_strokes_inside_stock(strokes: Iterable[Stroke], width: float, height: float) -> None:
    for stroke in strokes:
        for x, y in stroke:
            if x < -0.001 or y < -0.001 or x > width + 0.001 or y > height + 0.001:
                raise ValueError("Generated toolpath extends outside the declared stock")
