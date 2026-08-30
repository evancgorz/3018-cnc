from __future__ import annotations


def make_station_commands(ssid: str, password: str, telnet_port: int = 23) -> list[tuple[bytes, str]]:
    """Build the documented MKS DLC32 ESP3D station-mode setup transaction."""
    ssid = ssid.strip()
    try:
        ssid_bytes = ssid.encode("ascii")
        password_bytes = password.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Use ASCII characters for the SSID and password") from exc
    if not ssid or any(character in ssid for character in "]\r\n"):
        raise ValueError("Enter a valid network name")
    if not 8 <= len(password_bytes) <= 63 or any(character in password for character in "]\r\n"):
        raise ValueError("A WPA/WPA2 password must contain 8 to 63 characters")
    if not 1 <= telnet_port <= 65535:
        raise ValueError("Telnet port must be between 1 and 65535")
    return [
        (b"[ESP110]STA", "[ESP110]STA"),
        (b"[ESP102]DHCP", "[ESP102]DHCP"),
        (b"[ESP100]" + ssid_bytes, "[ESP100]<SSID redacted>"),
        (b"[ESP101]" + password_bytes, "[ESP101]<password redacted>"),
        (b"[ESP130]ON", "[ESP130]ON"),
        (f"[ESP131]{telnet_port}".encode("ascii"), f"[ESP131]{telnet_port}"),
        (b"[ESP115]ON", "[ESP115]ON"),
        (b"[ESP444]RESTART", "[ESP444]RESTART"),
    ]
