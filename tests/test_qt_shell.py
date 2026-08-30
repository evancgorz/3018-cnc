from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ttc3018_control.qt.main import build_engine
from ttc3018_control.grbl import GrblStatus, Position


def test_qt_shell_loads(qapp) -> None:
    engine, view_model = build_engine()

    roots = engine.rootObjects()
    assert len(roots) == 1
    assert roots[0].property("title") == "TTC 3018 Control — Qt Preview"
    assert view_model.connection == "Disconnected"


def test_qt_view_model_projects_grbl_status(qapp) -> None:
    _engine, view_model = build_engine()

    view_model.apply_status(
        GrblStatus(
            "Idle",
            machine_position=Position(10, 20, 3),
            work_position=Position(1, 2, 3),
            spindle=12000,
        )
    )

    assert view_model.connection == "Connected — GRBL Idle"
    assert view_model.machine_position == "X10.00  Y20.00  Z3.00"
    assert view_model.work_position == "X1.00  Y2.00  Z3.00"
    assert view_model.spindle == "12000 RPM"
