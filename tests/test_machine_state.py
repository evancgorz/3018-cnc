from pathlib import Path

import pytest

from ttc3018_control.grbl import Position
from ttc3018_control.machine_state import (
    MachineProfile,
    ProfileStore,
    VirtualEnvelope,
    check_job_bounds,
    plan_safe_position_jogs,
    work_zero_virtual_target,
)


@pytest.fixture
def profile() -> MachineProfile:
    return MachineProfile(travel_x=300, travel_y=180, travel_z=40, safe_z=35)


def test_profile_round_trip(tmp_path: Path, profile: MachineProfile) -> None:
    store = ProfileStore(tmp_path / "machine-profile.json")
    store.save(profile)
    assert store.load() == profile


def test_invalid_profile_is_not_saved(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "machine-profile.json")
    with pytest.raises(ValueError, match="X travel"):
        store.save(MachineProfile())
    assert not store.path.exists()


def test_reference_maps_current_position_to_zero(profile: MachineProfile) -> None:
    envelope = VirtualEnvelope()
    envelope.establish(Position(7, 1, 20), profile)
    assert envelope.relative_position(Position(7, 1, 20)) == Position(0, 0, 0)
    assert envelope.relative_position(Position(12, 3, 25)) == Position(5, 2, 5)


def test_envelope_allows_inside_jog(profile: MachineProfile) -> None:
    envelope = VirtualEnvelope()
    envelope.establish(Position(10, 20, 30), profile)
    allowed, _ = envelope.check_jog("X", 5, Position(15, 20, 30), profile)
    assert allowed


@pytest.mark.parametrize(
    ("axis", "distance", "position"),
    [
        ("X", -1, Position(10, 20, 30)),
        ("X", 1, Position(310, 20, 30)),
        ("Y", 1, Position(10, 200, 30)),
        ("Z", 1, Position(10, 20, 70)),
    ],
)
def test_envelope_blocks_outside_jog(
    profile: MachineProfile,
    axis: str,
    distance: float,
    position: Position,
) -> None:
    envelope = VirtualEnvelope()
    envelope.establish(Position(10, 20, 30), profile)
    allowed, message = envelope.check_jog(axis, distance, position, profile)
    assert not allowed
    assert "allowed range" in message


def test_invalidation_removes_trust(profile: MachineProfile) -> None:
    envelope = VirtualEnvelope()
    envelope.establish(Position(0, 0, 0), profile)
    envelope.invalidate("Controller reset")
    assert not envelope.trusted
    assert envelope.relative_position(Position(1, 2, 3)) is None


def test_work_coordinate_job_bounds_fit_virtual_machine(profile: MachineProfile) -> None:
    allowed, _ = check_job_bounds(
        Position(0, 0, -2),
        Position(20, 10, 5),
        work_offset=Position(50, 40, 20),
        machine_reference=Position(10, 10, 0),
        profile=profile,
    )
    assert allowed


def test_work_coordinate_job_bounds_reject_negative_virtual_z(profile: MachineProfile) -> None:
    allowed, message = check_job_bounds(
        Position(0, 0, -2),
        Position(20, 10, 5),
        work_offset=Position(50, 40, 1),
        machine_reference=Position(10, 10, 0),
        profile=profile,
    )
    assert not allowed
    assert message.startswith("Z job range")


def test_position_move_raises_before_xy_and_lowers_last(profile: MachineProfile) -> None:
    moves = plan_safe_position_jogs(Position(10, 20, 5), Position(30, 40, 2), profile)
    assert moves == [("Z", 30), ("X", 20), ("Y", 20), ("Z", -33)]


def test_position_move_keeps_higher_current_z_for_lateral_motion(profile: MachineProfile) -> None:
    moves = plan_safe_position_jogs(Position(10, 20, 38), Position(30, 40, 5), profile)
    assert moves == [("X", 20), ("Y", 20), ("Z", -33)]


@pytest.mark.parametrize("target", [Position(-1, 0, 0), Position(0, 181, 0), Position(0, 0, 41)])
def test_position_move_rejects_targets_outside_envelope(profile: MachineProfile, target: Position) -> None:
    with pytest.raises(ValueError, match="outside the allowed range"):
        plan_safe_position_jogs(Position(0, 0, 0), target, profile)


def test_work_zero_target_converts_grbl_offset_to_virtual_coordinates() -> None:
    assert work_zero_virtual_target(Position(10, 20, 3), Position(35, 40, 12)) == Position(25, 20, 9)

