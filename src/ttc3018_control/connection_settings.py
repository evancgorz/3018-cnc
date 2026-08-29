from __future__ import annotations

from dataclasses import asdict, dataclass
from ipaddress import IPv4Address
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class ConnectionSettings:
    wifi_host: str = "192.168.4.1"
    wifi_port: int = 23
    preferred_transport: str = "USB serial"

    def validate(self) -> None:
        if not self.wifi_host.strip():
            raise ValueError("Wi-Fi host cannot be empty")
        if not 1 <= self.wifi_port <= 65535:
            raise ValueError("TCP port must be between 1 and 65535")
        if self.preferred_transport not in {"USB serial", "Wi-Fi TCP"}:
            raise ValueError("Preferred transport must be USB serial or Wi-Fi TCP")


class ConnectionSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ConnectionSettings:
        if not self.path.exists():
            return ConnectionSettings()
        settings = ConnectionSettings(**json.loads(self.path.read_text(encoding="utf-8")))
        settings.validate()
        return settings

    def save(self, settings: ConnectionSettings) -> None:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def extract_controller_ip(message: str) -> str | None:
    """Extract an address from supported DLC32 network-status formats."""
    match = re.search(
        r"(?:\bIP=|\bConnected with\s+)(\d{1,3}(?:\.\d{1,3}){3})",
        message,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        address = IPv4Address(match.group(1))
    except ValueError:
        return None
    if address.is_unspecified:
        return None
    return str(address)
