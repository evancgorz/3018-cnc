from __future__ import annotations

from pathlib import Path

import pytest

from ttc3018_control.step_geometry import (
    STEP_PLANES,
    PlanarLoop,
    Point2D,
    StepPlanarModel,
    StepImportError,
    load_step,
    load_step_isolated,
    loop_containment_parents,
)
from ttc3018_control.step_engraver import generate_step_gcode
from ttc3018_control.gcode import parse_gcode


def _write_box(path: Path, width: float = 40, height: float = 25, depth: float = 5) -> None:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(width, height, depth).Shape(), STEPControl_AsIs)
    writer.Write(str(path))


def _write_compound_boxes(path: Path) -> None:
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Compound
    from OCP.gp import gp_Pnt

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 15, 5).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(30, 0, 0), 10, 15, 5).Shape())
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    writer.Write(str(path))


def _write_rectangular_pocket(path: Path, *, through: bool = False) -> None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.gp import gp_Pnt

    stock = BRepPrimAPI_MakeBox(40, 25, 5).Shape()
    bottom = -1 if through else 2
    cutter = BRepPrimAPI_MakeBox(gp_Pnt(10, 7, bottom), 12, 8, 7).Shape()
    result = BRepAlgoAPI_Cut(stock, cutter).Shape()
    writer = STEPControl_Writer()
    writer.Transfer(result, STEPControl_AsIs)
    writer.Write(str(path))


def _write_rectangular_boss(path: Path) -> None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.gp import gp_Pnt

    base = BRepPrimAPI_MakeBox(40, 25, 5).Shape()
    boss = BRepPrimAPI_MakeBox(gp_Pnt(10, 7, 5), 12, 8, 3).Shape()
    result = BRepAlgoAPI_Fuse(base, boss).Shape()
    writer = STEPControl_Writer()
    writer.Transfer(result, STEPControl_AsIs)
    writer.Write(str(path))


def test_load_step_normalizes_highest_horizontal_face(tmp_path: Path) -> None:
    path = tmp_path / "plate.step"
    _write_box(path)

    model = load_step(path)

    assert model.width == pytest.approx(40, abs=0.001)
    assert model.height == pytest.approx(25, abs=0.001)
    assert model.thickness == pytest.approx(5, abs=0.001)
    assert len(model.loops) == 1
    assert model.outer_loop.area == pytest.approx(1000, abs=0.01)
    assert model.outer_loop.bounds == pytest.approx((0, 0, 40, 25), abs=0.001)


def test_load_step_can_select_each_orthogonal_face(tmp_path: Path) -> None:
    path = tmp_path / "plate.step"
    _write_box(path)

    auto = load_step(path)
    front = load_step(path, STEP_PLANES[2])
    side = load_step(path, STEP_PLANES[3])

    assert auto.face_plane == "XY"
    assert (auto.width, auto.height, auto.thickness) == pytest.approx((40, 25, 5), abs=0.001)
    assert front.face_plane == "XZ"
    assert (front.width, front.height, front.thickness) == pytest.approx((40, 5, 25), abs=0.001)
    assert side.face_plane == "YZ"
    assert (side.width, side.height, side.thickness) == pytest.approx((25, 5, 40), abs=0.001)


def test_load_step_isolated_round_trips_model(tmp_path: Path) -> None:
    path = tmp_path / "plate.step"
    _write_box(path)

    model = load_step_isolated(path, STEP_PLANES[2])

    assert model.face_plane == "XZ"
    assert (model.width, model.height, model.thickness) == pytest.approx((40, 5, 25), abs=0.001)
    assert model.surface_patches
    assert all(patch.loops for patch in model.surface_patches)


def test_load_step_preserves_disconnected_coplanar_compound_faces(tmp_path: Path) -> None:
    path = tmp_path / "compound.step"
    _write_compound_boxes(path)

    model = load_step_isolated(path)

    assert model.width == pytest.approx(40, abs=0.001)
    assert model.height == pytest.approx(15, abs=0.001)
    assert len(model.loops) == 2
    assert model.outer_loop_indices == (0, 1)
    assert model.resolved_loop_parents == (None, None)

    job = generate_step_gcode(
        model,
        mode="Profile cutout",
        stock_width=42,
        stock_height=17,
        tool_diameter=2,
        stock_thickness=5,
        tab_count=0,
    )
    assert job.stroke_count == 2
    assert parse_gcode(job.gcode).bounds.maximum.x == pytest.approx(42, abs=0.001)


@pytest.mark.parametrize("through", [False, True])
def test_load_step_detects_planar_walled_rectangular_recess(tmp_path: Path, through: bool) -> None:
    path = tmp_path / ("through-pocket.step" if through else "blind-pocket.step")
    _write_rectangular_pocket(path, through=through)

    model = load_step_isolated(path)

    recesses = [feature for feature in model.features if feature.kind == "Recess"]
    assert recesses
    assert recesses[0].depth == pytest.approx(5 if through else 3, abs=0.01)
    assert recesses[0].is_through is through

    job = generate_step_gcode(
        model,
        mode="Detected feature",
        stock_width=40,
        stock_height=25,
        tool_diameter=3,
        stock_thickness=5,
        breakthrough=0.2,
        passes=2,
    )
    program = parse_gcode(job.gcode)
    assert job.feature_simulations and job.feature_simulations[0].passed
    assert program.bounds.minimum.z == pytest.approx(-5.2 if through else -3, abs=0.01)


def test_load_step_detects_planar_walled_rectangular_boss(tmp_path: Path) -> None:
    path = tmp_path / "boss.step"
    _write_rectangular_boss(path)

    model = load_step_isolated(path)

    bosses = [feature for feature in model.features if feature.kind == "Raised boss"]
    assert bosses
    assert bosses[0].depth == pytest.approx(3, abs=0.01)
    assert not bosses[0].is_through


def test_wedge_import_preserves_tilted_planar_surface_patch() -> None:
    model = load_step_isolated(Path(__file__).parents[1] / "examples" / "wedge.step")

    tilted = [patch for patch in model.surface_patches if patch.tilted]
    assert tilted
    patch = tilted[0]
    assert patch.a == pytest.approx(0.60696, abs=0.001)
    assert patch.height_at(9.2234, 0) == pytest.approx(-5.983, abs=0.01)
    assert patch.height_at(19.0806, 0) == pytest.approx(0, abs=0.01)


@pytest.mark.parametrize("fixture", ["removed-cylinder.step", "extruded-circle.step"])
def test_real_feature_fixture_round_trips_loop_containment(fixture: str) -> None:
    model = load_step_isolated(Path(__file__).parents[1] / "examples" / fixture)

    assert model.loop_parents == (None, 0)
    assert model.resolved_loop_parents == model.loop_parents
    assert model.features[0].parent_loop_index == 0


def test_loop_containment_parents_represent_nested_pockets_and_islands() -> None:
    def square(left: float, bottom: float, size: float) -> PlanarLoop:
        return PlanarLoop(tuple(
            Point2D(x, y)
            for x, y in (
                (left, bottom),
                (left + size, bottom),
                (left + size, bottom + size),
                (left, bottom + size),
            )
        ))

    loops = (square(0, 0, 40), square(5, 5, 30), square(10, 10, 20), square(15, 15, 10))

    assert loop_containment_parents(loops) == (None, 0, 1, 2)

    model = StepPlanarModel(
        Path("nested.step"), loops, 5, 5, (0, 0, 0, 40, 40, 5),
        loop_parents=(None, 0, 1, 2),
    )
    assert model.outer_loop_indices == (0,)
    assert model.loop_depths == (0, 1, 2, 3)
    assert model.loop_roles == ("outer", "cutout", "island", "cutout")


def test_loop_containment_parents_preserve_disconnected_roots_and_reject_coincident_loops() -> None:
    def square(left: float, bottom: float, size: float) -> PlanarLoop:
        return PlanarLoop(tuple(
            Point2D(x, y)
            for x, y in (
                (left, bottom),
                (left + size, bottom),
                (left + size, bottom + size),
                (left, bottom + size),
            )
        ))

    assert loop_containment_parents((square(0, 0, 10), square(20, 20, 5))) == (None, None)
    with pytest.raises(StepImportError, match="coincident"):
        loop_containment_parents((square(0, 0, 10), square(0, 0, 10)))


def test_loop_containment_parents_rejects_partial_overlap_and_self_intersection() -> None:
    with pytest.raises(StepImportError, match="partially overlap"):
        loop_containment_parents(
            (
                PlanarLoop((Point2D(0, 0), Point2D(10, 0), Point2D(10, 10), Point2D(0, 10))),
                PlanarLoop((Point2D(5, -1), Point2D(15, -1), Point2D(15, 9), Point2D(5, 9))),
            )
        )
    with pytest.raises(StepImportError, match="self-intersecting"):
        loop_containment_parents(
            (PlanarLoop((Point2D(0, 0), Point2D(10, 10), Point2D(0, 10), Point2D(10, 0))),)
        )
    with pytest.raises(StepImportError, match="zero-length"):
        loop_containment_parents(
            (PlanarLoop((Point2D(0, 0), Point2D(10, 0), Point2D(10, 0), Point2D(0, 10))),)
        )


def test_supplied_loop_parent_metadata_must_match_projected_geometry() -> None:
    outer = PlanarLoop((Point2D(0, 0), Point2D(20, 0), Point2D(20, 20), Point2D(0, 20)))
    inner = PlanarLoop((Point2D(5, 5), Point2D(15, 5), Point2D(15, 15), Point2D(5, 15)))
    model = StepPlanarModel(
        Path("inconsistent-topology.step"),
        (outer, inner),
        5,
        5,
        (0, 0, 0, 20, 20, 5),
        loop_parents=(None, None),
    )

    with pytest.raises(StepImportError, match="does not match"):
        _ = model.resolved_loop_parents


def test_load_step_isolated_reports_worker_errors(tmp_path: Path) -> None:
    with pytest.raises(StepImportError, match="STEP file was not found"):
        load_step_isolated(tmp_path / "missing.step")


def test_load_step_rejects_unknown_face_orientation(tmp_path: Path) -> None:
    path = tmp_path / "plate.step"
    _write_box(path)

    with pytest.raises(StepImportError, match="Auto, XY, XZ, or YZ"):
        load_step(path, "angled")


def test_load_step_rejects_non_step_extension(tmp_path: Path) -> None:
    path = tmp_path / "plate.txt"
    path.write_text("not a STEP file", encoding="ascii")

    with pytest.raises(StepImportError, match="extension"):
        load_step(path)
