from __future__ import annotations

from pathlib import Path

import pytest

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.step_engraver import generate_step_gcode
from ttc3018_control.step_geometry import STEP_PLANES, StepImportError, load_step_isolated


ROOT = Path(__file__).parents[1]


def _write_rotated_shape(path: Path, *, nested: bool = False, compound: bool = False) -> None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Compound
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf

    shape = BRepPrimAPI_MakeBox(20, 10, 5).Shape()
    if nested:
        shape = BRepAlgoAPI_Cut(
            shape, BRepPrimAPI_MakeBox(gp_Pnt(5, 2, 2), 10, 5, 4).Shape()
        ).Shape()
    if compound:
        compound_shape = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound_shape)
        builder.Add(compound_shape, shape)
        builder.Add(compound_shape, BRepPrimAPI_MakeBox(gp_Pnt(40, 0, 0), 10, 10, 5).Shape())
        shape = compound_shape
    transform = gp_Trsf()
    transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 1, 0)), 0.4)
    shape = BRepBuilderAPI_Transform(shape, transform, True).Shape()
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(str(path))


def test_auto_and_explicit_arbitrary_basis_are_deterministic_and_thick(tmp_path: Path) -> None:
    path = tmp_path / "rotated-box.step"
    _write_rotated_shape(path)
    auto = load_step_isolated(path)
    explicit = load_step_isolated(path, STEP_PLANES[4])
    repeat = load_step_isolated(path)

    assert auto.face_plane == explicit.face_plane == "ARBITRARY"
    assert auto.face_basis == explicit.face_basis == repeat.face_basis
    assert auto.loops == explicit.loops == repeat.loops
    assert auto.thickness == pytest.approx(5.0, abs=0.01)
    origin, u, v, normal = auto.face_basis
    assert all(abs(sum(vector[index] ** 2 for index in range(3)) - 1.0) < 1e-6
               for vector in (u, v, normal))
    assert abs(sum(u[index] * v[index] for index in range(3))) < 1e-6
    assert abs(sum(u[index] * normal[index] for index in range(3))) < 1e-6
    assert abs(sum(v[index] * normal[index] for index in range(3))) < 1e-6
    assert len(auto.loops) == 1 and auto.loop_parents == (None,)


def test_arbitrary_nested_and_compound_topology_and_generation_bounds(tmp_path: Path) -> None:
    nested_path = tmp_path / "rotated-nested.step"
    _write_rotated_shape(nested_path, nested=True)
    nested = load_step_isolated(nested_path)
    assert nested.face_plane == "ARBITRARY"
    assert nested.loop_roles == ("outer", "cutout")
    assert nested.loop_parents == (None, 0)
    job = generate_step_gcode(
        nested, mode="Automatic part", stock_width=nested.width + 10.0,
        stock_height=nested.height + 10.0, stock_thickness=nested.thickness,
        tool_diameter=3.0, tab_count=0,
    )
    bounds = parse_gcode(job.gcode).bounds
    assert bounds.minimum.x >= -1e-6 and bounds.minimum.y >= -1e-6
    assert bounds.maximum.x <= nested.width + 10.0 + 1e-6
    assert bounds.maximum.y <= nested.height + 10.0 + 1e-6

    compound_path = tmp_path / "rotated-compound.step"
    _write_rotated_shape(compound_path, compound=True)
    compound = load_step_isolated(compound_path)
    assert compound.face_plane == "ARBITRARY"
    assert compound.outer_loop_indices == (0, 1)
    assert compound.resolved_loop_parents == (None, None)


def test_arbitrary_selection_rejects_missing_or_nonstep_input(tmp_path: Path) -> None:
    with pytest.raises(StepImportError, match="not found"):
        load_step_isolated(tmp_path / "missing.step", STEP_PLANES[4])
    invalid = tmp_path / "invalid.txt"
    invalid.write_text("not STEP", encoding="ascii")
    with pytest.raises(StepImportError, match="extension"):
        load_step_isolated(invalid, STEP_PLANES[4])
