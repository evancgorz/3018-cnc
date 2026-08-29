from pathlib import Path

import pytest

from ttc3018_control.commissioning import CommissioningProfile, CommissioningStore, InputTestTracker


def test_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "commissioning.json"
    profile = CommissioningProfile(x_limit_tested=True, plate_thickness=15.2)
    CommissioningStore(path).save(profile)
    assert CommissioningStore(path).load() == profile


def test_profile_prerequisites() -> None:
    profile = CommissioningProfile(
        x_limit_tested=True,
        y_limit_tested=True,
        z_limit_tested=True,
        x_positive_confirmed=True,
        y_positive_confirmed=True,
        z_positive_confirmed=True,
        homing_settings_reviewed=True,
    )
    assert profile.ready_for_homing_test
    assert not profile.ready_for_probe_motion
    profile.homing_verified = True
    profile.probe_tested = True
    profile.plate_thickness = 12.0
    assert profile.ready_for_probe_motion


def test_profile_rejects_implausible_probe_geometry(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CommissioningStore(tmp_path / "unused").save(CommissioningProfile(plate_thickness=-1))


def test_input_test_requires_clean_start_and_press_release() -> None:
    tracker = InputTestTracker()
    assert tracker.start("X", "P").state == "blocked"
    assert tracker.start("X", "").state == "awaiting_press"
    assert tracker.update("X").state == "awaiting_release"
    assert tracker.update("").passed


def test_input_test_rejects_coupled_signal() -> None:
    tracker = InputTestTracker()
    tracker.start("Z", "")
    assert tracker.update("ZP").state == "failed"
