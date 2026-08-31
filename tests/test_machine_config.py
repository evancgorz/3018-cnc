import pytest

from ttc3018_control.machine_config import (
    AxisDefinition,
    AxisEnd,
    MachineDefinition,
    ProbeDefinition,
    ProbeKind,
    SwitchMode,
)


def test_legacy_definition_is_all_optional_features_off() -> None:
    machine = MachineDefinition.legacy_3018()
    assert machine.to_profile().travels == (290, 170, 40)
    assert all(axis.switch_mode is SwitchMode.NONE for axis in machine.axes.values())
    assert machine.probes == ()


def test_machine_definition_round_trips_and_fingerprints_relevant_changes() -> None:
    machine = MachineDefinition(
        machine_id="m1",
        name="Probe CNC",
        axes={"X": AxisDefinition(switch_mode=SwitchMode.SINGLE, input_pin="X", switch_end=AxisEnd.MIN),
              "Y": AxisDefinition(), "Z": AxisDefinition()},
        probes=(ProbeDefinition(ProbeKind.MOVABLE_Z_PLATE, enabled=True, plate_thickness=1.5),),
    )
    restored = MachineDefinition.from_dict(machine.to_dict())
    assert restored == machine
    assert machine.fingerprint("name") != machine.fingerprint("geometry")
    assert machine.fingerprint("axes") != MachineDefinition.from_dict({**machine.to_dict(), "axes": {
        **machine.to_dict()["axes"], "X": {**machine.to_dict()["axes"]["X"], "active_low": True}
    }}).fingerprint("axes")


@pytest.mark.parametrize("field", ["travel_x", "travel_y", "travel_z", "safe_z"])
def test_machine_definition_rejects_invalid_geometry(field: str) -> None:
    values = {"machine_id": "m1", "travel_x": 10, "travel_y": 10, "travel_z": 10, "safe_z": 5}
    values[field] = -1
    with pytest.raises(ValueError):
        MachineDefinition(**values).validate()


def test_enabled_probe_requires_positive_motion_settings() -> None:
    with pytest.raises(ValueError, match="positive motion"):
        MachineDefinition(machine_id="m1", probes=(ProbeDefinition(ProbeKind.MOVABLE_Z_PLATE, enabled=True, fast_feed=0),)).validate()

