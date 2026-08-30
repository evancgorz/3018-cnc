"""STEP import and normalization for the bounded planar 2.5D workflow.

OpenCASCADE remains behind this module.  The rest of the application consumes
small immutable 2D dataclasses and never needs to know about OCC handles.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any


class StepImportError(ValueError):
    """A STEP file could not be imported into a supported planar model."""


STEP_PLANES = (
    "Auto (largest planar face)",
    "XY (top/bottom)",
    "XZ (front/back)",
    "YZ (left/right)",
)


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


@dataclass(frozen=True)
class PlanarLoop:
    points: tuple[Point2D, ...]

    @property
    def signed_area(self) -> float:
        return 0.5 * sum(
            point.x * following.y - following.x * point.y
            for point, following in zip(self.points, self.points[1:] + self.points[:1])
        )

    @property
    def area(self) -> float:
        return abs(self.signed_area)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (
            min(point.x for point in self.points),
            min(point.y for point in self.points),
            max(point.x for point in self.points),
            max(point.y for point in self.points),
        )


@dataclass(frozen=True)
class StepPlanarModel:
    path: Path
    loops: tuple[PlanarLoop, ...]
    top_z: float
    thickness: float
    source_bounds: tuple[float, float, float, float, float, float]
    face_plane: str = "XY"
    face_normal: tuple[float, float, float] = (0.0, 0.0, 1.0)

    @property
    def width(self) -> float:
        points = [point for loop in self.loops for point in loop.points]
        return max(point.x for point in points) - min(point.x for point in points)

    @property
    def height(self) -> float:
        points = [point for loop in self.loops for point in loop.points]
        return max(point.y for point in points) - min(point.y for point in points)

    @property
    def outer_loop(self) -> PlanarLoop:
        return max(self.loops, key=lambda loop: loop.area)

    @property
    def inner_loops(self) -> tuple[PlanarLoop, ...]:
        outer = self.outer_loop
        return tuple(loop for loop in self.loops if loop is not outer)


def load_step(path: Path, plane: str = STEP_PLANES[0]) -> StepPlanarModel:
    """Load a STEP file and normalize a supported orthogonal planar face.

    Auto selects the largest usable planar face.  This is a useful default for
    parts such as brackets whose intended machining face is vertical in the
    source CAD coordinate system.
    """

    path = Path(path)
    if plane not in STEP_PLANES:
        raise StepImportError("Choose Auto, XY, XZ, or YZ for the STEP face orientation")
    if path.suffix.lower() not in {".step", ".stp"}:
        raise StepImportError("Choose a STEP file with a .step or .stp extension")
    if not path.exists() or not path.is_file():
        raise StepImportError(f"STEP file was not found: {path}")

    try:
        modules = _ocp_modules()
        reader = modules["STEPControl_Reader"]()
        result = reader.ReadFile(str(path))
        if result != modules["IFSelect_RetDone"]:
            raise StepImportError("OpenCASCADE could not read this STEP file")
        if reader.TransferRoots() == 0:
            raise StepImportError("The STEP file contains no transferable shape")
        shape = reader.OneShape()
    except StepImportError:
        raise
    except Exception as exc:  # OCP exposes several exception types by version.
        raise StepImportError(f"STEP import failed: {exc}") from exc

    try:
        return _normalize_shape(path, shape, modules, plane)
    except StepImportError:
        raise
    except Exception as exc:
        raise StepImportError(f"STEP geometry could not be normalized: {exc}") from exc


def _ocp_modules() -> dict[str, Any]:
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepTools import BRepTools_WireExplorer
        from OCP.Bnd import Bnd_Box
        from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Plane
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
    except ImportError as exc:
        raise StepImportError(
            "STEP support is unavailable; install the cadquery-ocp dependency"
        ) from exc
    return locals()


def _normalize_shape(path: Path, shape: Any, modules: dict[str, Any], plane: str) -> StepPlanarModel:
    explorer = modules["TopExp_Explorer"](shape, modules["TopAbs_FACE"])
    candidates: list[tuple[float, str, list[PlanarLoop], tuple[float, float, float], float]] = []
    while explorer.More():
        face = modules["TopoDS"].Face_s(explorer.Current())
        surface = modules["BRepAdaptor_Surface"](face, True)
        if surface.GetType() == modules["GeomAbs_Plane"]:
            normal = surface.Plane().Axis().Direction()
            axis = _plane_axis(normal.X(), normal.Y(), normal.Z())
            if axis is not None:
                try:
                    loops = _extract_loops(face, modules, axis)
                except StepImportError:
                    loops = []
                if loops:
                    candidates.append(
                        (
                            max(loop.area for loop in loops),
                            axis,
                            loops,
                            (float(normal.X()), float(normal.Y()), float(normal.Z())),
                            _plane_coordinate(surface.Plane().Location(), axis),
                        )
                    )
        explorer.Next()
    if not candidates:
        raise StepImportError("No closed orthogonal planar face was found; tilted or open geometry is not supported")

    selected = candidates
    if plane != STEP_PLANES[0]:
        requested_axis = plane[:2]
        selected = [candidate for candidate in candidates if candidate[1] == requested_axis]
        if not selected:
            raise StepImportError(f"No closed {requested_axis} planar face was found in this STEP file")
    _face_area, selected_axis, loops, normal, face_coordinate = max(selected, key=lambda candidate: candidate[0])

    all_points = [point for loop in loops for point in loop.points]
    min_x = min(point.x for point in all_points)
    min_y = min(point.y for point in all_points)
    normalized = tuple(
        PlanarLoop(tuple(Point2D(point.x - min_x, point.y - min_y) for point in loop.points))
        for loop in loops
    )
    box = modules["Bnd_Box"]()
    modules["BRepBndLib"].Add_s(shape, box)
    bounds = box.Get()
    thickness = _plane_thickness(bounds, selected_axis)
    return StepPlanarModel(path, normalized, face_coordinate, thickness, bounds, selected_axis, normal)


def _plane_axis(x: float, y: float, z: float) -> str | None:
    components = {"XY": abs(z), "XZ": abs(y), "YZ": abs(x)}
    axis, strength = max(components.items(), key=lambda item: item[1])
    return axis if strength > 0.999 else None


def _plane_coordinate(point: Any, plane: str) -> float:
    if plane == "XY":
        return float(point.Z())
    if plane == "XZ":
        return float(point.Y())
    return float(point.X())


def _plane_thickness(bounds: tuple[float, float, float, float, float, float], plane: str) -> float:
    if plane == "XY":
        return max(0.0, bounds[5] - bounds[2])
    if plane == "XZ":
        return max(0.0, bounds[4] - bounds[1])
    return max(0.0, bounds[3] - bounds[0])


def _extract_loops(face: Any, modules: dict[str, Any], plane: str) -> list[PlanarLoop]:
    wires = modules["TopExp_Explorer"](face, modules["TopAbs_WIRE"])
    loops: list[PlanarLoop] = []
    while wires.More():
        wire = modules["TopoDS"].Wire_s(wires.Current())
        if not wire.Closed():
            raise StepImportError("Open top-face wire is not supported")
        edge_explorer = modules["BRepTools_WireExplorer"](wire, face)
        segments: list[Any] = []
        while edge_explorer.More():
            edge = modules["TopoDS"].Edge_s(edge_explorer.Current())
            curve = modules["BRepAdaptor_Curve"](edge)
            segments.append(_sample_curve(curve, modules))
            edge_explorer.Next()
        if not segments:
            raise StepImportError("Top-face wire contains no edges")
        loop = _polygonize_segments(
            [[_project_point(point, plane) for point in segment] for segment in segments]
        )
        if loop is not None:
            loops.append(loop)
        wires.Next()
    return loops


@dataclass(frozen=True)
class _Point3D:
    x: float
    y: float
    z: float


def _sample_curve(curve: Any, modules: dict[str, Any]) -> list[_Point3D]:
    first = curve.FirstParameter()
    last = curve.LastParameter()
    count = 2 if curve.GetType() == modules["GeomAbs_Line"] else 48
    points: list[_Point3D] = []
    for index in range(count):
        parameter = first + (last - first) * index / (count - 1)
        point = curve.Value(parameter)
        candidate = _Point3D(float(point.X()), float(point.Y()), float(point.Z()))
        if not points or math.dist(
            (candidate.x, candidate.y, candidate.z),
            (points[-1].x, points[-1].y, points[-1].z),
        ) > 1e-7:
            points.append(candidate)
    return points


def _project_point(point: _Point3D, plane: str) -> Point2D:
    if plane == "XY":
        return Point2D(point.x, point.y)
    if plane == "XZ":
        return Point2D(point.x, point.z)
    return Point2D(point.y, point.z)


def _polygonize_segments(segments: list[list[Point2D]]) -> PlanarLoop | None:
    try:
        from shapely.geometry import LineString
        from shapely.ops import polygonize, unary_union
    except ImportError as exc:
        raise StepImportError("STEP geometry requires the shapely dependency") from exc
    lines = [LineString((point.x, point.y) for point in segment) for segment in segments if len(segment) >= 2]
    polygons = list(polygonize(unary_union(lines)))
    if not polygons:
        return None
    polygon = max(polygons, key=lambda candidate: candidate.area)
    coordinates = tuple(Point2D(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1])
    if len(coordinates) < 3 or polygon.area <= 1e-7:
        return None
    return PlanarLoop(coordinates)
