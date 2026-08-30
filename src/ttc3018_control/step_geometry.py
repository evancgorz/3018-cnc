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

    @property
    def width(self) -> float:
        return self.source_bounds[3] - self.source_bounds[0]

    @property
    def height(self) -> float:
        return self.source_bounds[4] - self.source_bounds[1]

    @property
    def outer_loop(self) -> PlanarLoop:
        return max(self.loops, key=lambda loop: loop.area)

    @property
    def inner_loops(self) -> tuple[PlanarLoop, ...]:
        outer = self.outer_loop
        return tuple(loop for loop in self.loops if loop is not outer)


def load_step(path: Path) -> StepPlanarModel:
    """Load a STEP file and normalize its highest horizontal planar face.

    The initial supported slice deliberately rejects tilted faces, open wires,
    and files without a horizontal top face.  OCC import errors are translated
    into user-facing ``StepImportError`` messages at this boundary.
    """

    path = Path(path)
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
        return _normalize_shape(path, shape, modules)
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
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
    except ImportError as exc:
        raise StepImportError(
            "STEP support is unavailable; install the cadquery-ocp dependency"
        ) from exc
    return locals()


def _normalize_shape(path: Path, shape: Any, modules: dict[str, Any]) -> StepPlanarModel:
    explorer = modules["TopExp_Explorer"](shape, modules["TopAbs_FACE"])
    candidates: list[tuple[float, Any, Any]] = []
    while explorer.More():
        face = modules["TopoDS"].Face_s(explorer.Current())
        surface = modules["BRepAdaptor_Surface"](face, True)
        if surface.GetType() == modules["GeomAbs_Plane"]:
            normal = surface.Plane().Axis().Direction()
            normal_z = normal.Z()
            if face.Orientation() == modules["TopAbs_REVERSED"]:
                normal_z = -normal_z
            if normal_z > 0.999:
                candidates.append((surface.Plane().Location().Z(), face, surface))
        explorer.Next()
    if not candidates:
        raise StepImportError("No upward horizontal planar top face was found")

    top_z, face, _surface = max(candidates, key=lambda candidate: candidate[0])
    loops = _extract_loops(face, modules)
    if not loops:
        raise StepImportError("The selected top face has no closed wire loops")

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
    thickness = max(0.0, bounds[5] - bounds[2])
    return StepPlanarModel(path, normalized, top_z, thickness, bounds)


def _extract_loops(face: Any, modules: dict[str, Any]) -> list[PlanarLoop]:
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
        loop = _polygonize_segments(segments)
        if loop is not None:
            loops.append(loop)
        wires.Next()
    return loops


def _sample_curve(curve: Any, modules: dict[str, Any]) -> list[Point2D]:
    first = curve.FirstParameter()
    last = curve.LastParameter()
    count = 2 if curve.GetType() == modules["GeomAbs_Line"] else 48
    points: list[Point2D] = []
    for index in range(count):
        parameter = first + (last - first) * index / (count - 1)
        point = curve.Value(parameter)
        candidate = Point2D(float(point.X()), float(point.Y()))
        if not points or math.hypot(candidate.x - points[-1].x, candidate.y - points[-1].y) > 1e-7:
            points.append(candidate)
    return points


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
