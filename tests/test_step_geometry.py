from __future__ import annotations

from pathlib import Path

import pytest

from ttc3018_control.step_geometry import STEP_PLANES, StepImportError, load_step, load_step_isolated


def _write_box(path: Path, width: float = 40, height: float = 25, depth: float = 5) -> None:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(width, height, depth).Shape(), STEPControl_AsIs)
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
