from pathlib import Path

import pytest

from ttc3018_control.grbl import Position
from ttc3018_control.machine_state import MachineProfile, ProfileStore, VirtualEnvelope


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

