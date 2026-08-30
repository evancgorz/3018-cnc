from pathlib import Path

from ttc3018_control.connection_settings import (
    ConnectionSettings,
    ConnectionSettingsStore,
    extract_controller_ip,
)


def test_extract_controller_ip_from_identity() -> None:
    assert (
        extract_controller_ip("[MSG:Mode=STA:SSID=hidden:Status=Connected:IP=192.168.86.36:MAC=00]")
        == "192.168.86.36"
    )


def test_extract_controller_ip_from_mks_connection_message() -> None:
    assert extract_controller_ip("[MSG:Connected with 192.168.86.36]") == "192.168.86.36"


def test_extract_controller_ip_rejects_invalid_or_missing_address() -> None:
    assert extract_controller_ip("[MSG:Connecting....]") is None
    assert extract_controller_ip("[MSG:Connected with 999.1.1.1]") is None
    assert extract_controller_ip("IP=0.0.0.0") is None
    assert extract_controller_ip("[MSG:Mode=STA:SSID=hidden:Status=Not connected:IP=0.0.0.0]") is None
    assert extract_controller_ip("[MSG:Mode=AP:SSID=MKS_DLC:IP=192.168.4.1]") is None


def test_connection_settings_round_trip(tmp_path: Path) -> None:
    store = ConnectionSettingsStore(tmp_path / "connection.json")
    expected = ConnectionSettings(
        wifi_host="192.168.86.36",
        wifi_port=23,
        preferred_transport="Wi-Fi TCP",
    )
    store.save(expected)
    assert store.load() == expected
