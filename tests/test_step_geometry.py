from __future__ import annotations

from pathlib import Path

import pytest

from ttc3018_control.step_geometry import StepImportError, load_step


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


def test_load_step_rejects_non_step_extension(tmp_path: Path) -> None:
    path = tmp_path / "plate.txt"
    path.write_text("not a STEP file", encoding="ascii")

    with pytest.raises(StepImportError, match="extension"):
        load_step(path)
