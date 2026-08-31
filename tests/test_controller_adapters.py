import pytest

from ttc3018_control.controller_adapters import Capability, GenericGrblAdapter, Grbl11Adapter, UnsupportedCapability
from ttc3018_control.grbl import Position, parse_probe_report, parse_tool_length_report


def test_grbl11_builds_guarded_commands() -> None:
    adapter = Grbl11Adapter()
    assert adapter.home_command() == b"$H\n"
    assert adapter.probe_command("Z", -5, 100) == b"G91 G21 G38.2 Z-5 F100\n"
    assert adapter.retract_command("Z", 2, 25) == b"G91 G21 Z2 F25\n"
    assert adapter.work_offset_command(1, Position(10, 20, 30)) == b"G10 L20 P1 X10 Y20 Z30\n"
    assert adapter.tool_offset_command(1.25) == b"G43.1 Z1.25\n"
    assert adapter.clear_tool_offset_command() == b"G49\n"


def test_generic_adapter_never_emits_unsupported_automation() -> None:
    adapter = GenericGrblAdapter()
    assert adapter.capabilities.supports(Capability.MOTION)
    with pytest.raises(UnsupportedCapability):
        adapter.home_command()
    with pytest.raises(UnsupportedCapability):
        adapter.probe_command("Z", -1, 10)


def test_probe_and_tlo_reports() -> None:
    assert parse_probe_report("[PRB:1.000,-2.000,3.000:1]") == (Position(1, -2, 3), True)
    assert parse_probe_report("[PRB:1,2,3:0]") == (Position(1, 2, 3), False)
    assert parse_probe_report("[PRB:bad]") is None
    assert parse_tool_length_report("[TLO:-1.25]") == -1.25


@pytest.mark.parametrize(
    ("reference", "measured", "expected"),
    [(10, 8, 2), (8, 10, -2), (-4, -5, 1)],
)
def test_tool_length_delta(reference: float, measured: float, expected: float) -> None:
    assert Grbl11Adapter.tool_length_delta(reference, measured) == expected

