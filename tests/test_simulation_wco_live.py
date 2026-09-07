from __future__ import annotations

import time
from pathlib import Path

import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import Position
from ttc3018_control.step_engraver import generate_step_gcode
from ttc3018_control.step_geometry import load_step_isolated


ROOT = Path(__file__).parents[1]


def _pump(controller: ApplicationController, predicate, timeout: float = 5.0) -> None:
    """Drive the normal TCP event/status path until predicate is satisfied."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        controller.request_status()
        events = controller.transport_events()
        while not events.empty():
            controller.handle_transport_response(events.get_nowait().text)
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def _connected(tmp_path) -> ApplicationController:
    physical_calls: list[str] = []

    def forbidden(name: str):
        def factory():
            physical_calls.append(name)
            raise AssertionError(f"physical {name} factory called")

        return factory

    controller = ApplicationController(
        tmp_path,
        usb_factory=forbidden("usb"),
        wifi_factory=forbidden("wifi"),
    )
    assert controller.connect_simulation().accepted
    _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle")
    assert not physical_calls
    return controller


def test_g10_l20_zero_uses_fresh_tcp_wco_and_work_position(tmp_path) -> None:
    controller = _connected(tmp_path)
    try:
        assert controller.establish_reference().accepted
        assert controller.jog("X", 2, 600).accepted
        _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle" and controller.machine_position is not None and controller.machine_position.x == pytest.approx(2, abs=0.01))

        outcome = controller.set_work_zero("XYZ")
        assert outcome.accepted
        # Confirmation is deliberately deferred until the updated GRBL report.
        assert not controller.work_zero_confirmed
        assert controller.work_offset is None

        _pump(controller, lambda: controller.work_zero_confirmed)
        assert controller.work_offset == Position(2.0, 0.0, 0.0)
        assert controller.status is not None
        assert controller.status.work_position == Position(0.0, 0.0, 0.0)
        assert controller.status.machine_position == Position(2.0, 0.0, 0.0)
    finally:
        controller.close()


def test_partial_axis_zero_updates_only_that_wco_without_confirming_xyz(tmp_path) -> None:
    controller = _connected(tmp_path)
    try:
        assert controller.establish_reference().accepted
        assert controller.jog("X", 2, 600).accepted
        _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle" and controller.machine_position is not None and controller.machine_position.x == pytest.approx(2, abs=0.01))

        assert controller.set_work_zero("X").accepted
        assert not controller.work_zero_confirmed
        assert controller.work_offset is None
        _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle" and controller.status.work_offset is not None and controller.status.work_offset.x == pytest.approx(2, abs=0.001))
        assert controller.work_offset == Position(2.0, 0.0, 0.0)
        assert controller.status is not None
        assert controller.status.work_position == Position(0.0, 0.0, 0.0)
        assert not controller.work_zero_confirmed
    finally:
        controller.close()


def test_generated_step_preflight_fits_after_safe_z_work_zero(tmp_path) -> None:
    controller = _connected(tmp_path)
    try:
        assert controller.establish_reference().accepted
        assert controller.jog("Z", 6, 600).accepted
        _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle" and controller.machine_position is not None and controller.machine_position.z == pytest.approx(6, abs=0.01))
        assert controller.set_work_zero("XYZ").accepted
        _pump(controller, lambda: controller.work_zero_confirmed)
        assert controller.work_offset == Position(0.0, 0.0, 6.0)

        model = load_step_isolated(ROOT / "examples" / "showcase-pocket-island.step")
        generated = generate_step_gcode(
            model,
            mode="Detected feature",
            stock_width=model.width + 3.175,
            stock_height=model.height + 3.175,
            stock_thickness=model.thickness,
            tool_diameter=3.175,
            max_stepdown=2,
            spindle_rpm=6000,
        )
        controller.load_generated(generated.gcode, "showcase-pocket-island.step.gcode")
        fits, reason = controller.preflight()
        assert fits, reason
    finally:
        controller.close()
