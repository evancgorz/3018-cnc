import pytest

from ttc3018_control.wifi_setup import make_station_commands


def test_station_setup_enables_dhcp_and_telnet() -> None:
    commands = make_station_commands("Workshop", "secret123")
    assert [command for command, _display in commands] == [
        b"[ESP110]STA",
        b"[ESP102]DHCP",
        b"[ESP100]Workshop",
        b"[ESP101]secret123",
        b"[ESP130]ON",
        b"[ESP131]23",
        b"[ESP115]ON",
        b"[ESP444]RESTART",
    ]
    assert "secret123" not in " ".join(display for _command, display in commands)


@pytest.mark.parametrize(
    ("ssid", "password"),
    [("", "secret123"), ("bad]ssid", "secret123"), ("Workshop", "short"), ("Workshop", "bad\npassword")],
)
def test_station_setup_rejects_invalid_credentials(ssid: str, password: str) -> None:
    with pytest.raises(ValueError):
        make_station_commands(ssid, password)
