from pathlib import Path

import pytest

from ttc3018_control.z_touch_plate import ZTouchPlateRecord, ZTouchPlateStore, ZTouchPlateWorkflow


def test_touch_plate_record_requires_three_repeatable_samples() -> None:
    record = ZTouchPlateRecord("m1", (10.0, 10.02, 10.01), 0.05, "fp", True)
    record.validate()
    assert record.commissioned
    with pytest.raises(ValueError, match="three samples"):
        ZTouchPlateRecord("m1", (1.0, 2.0), 0.05, "fp", True).validate()
    with pytest.raises(ValueError, match="tolerance"):
        ZTouchPlateRecord("m1", (1.0, 1.2, 1.1), 0.05, "fp", True).validate()


def test_touch_plate_store_round_trip(tmp_path: Path) -> None:
    store = ZTouchPlateStore(tmp_path / "config" / "z-touch-plates.json")
    record = ZTouchPlateRecord("m1", (1.0, 1.01, 1.02), 0.05, "fp", True, "now")
    store.save(record)
    assert store.load("m1") == record


def test_touch_plate_input_test_is_no_motion_and_open_touch_open() -> None:
    workflow = ZTouchPlateWorkflow()
    result = workflow.start_input_test("")
    assert result.state == "awaiting_press"
    assert workflow.observe_pins("").state == "awaiting_press"
    assert workflow.observe_pins("P").state == "awaiting_release"
    assert workflow.observe_pins("").passed


def test_touch_plate_input_test_ignores_undeclared_limit_pin_reports() -> None:
    workflow = ZTouchPlateWorkflow()

    result = workflow.start_input_test("XYZ")

    assert result.state == "awaiting_press"
    assert workflow.observe_pins("PXYZ").state == "awaiting_release"
    assert workflow.observe_pins("XYZ").passed


def test_touch_plate_input_test_explains_reversed_grbl_probe_polarity() -> None:
    workflow = ZTouchPlateWorkflow()

    result = workflow.start_input_test("PXYZ")

    assert result.state == "blocked"
    assert "GRBL probe polarity ($6) is reversed" in result.message
