"""Versioned, secret-free settings for the optional Pine Live companion."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
import tempfile


@dataclass
class LiveSettings:
    version: int = 1
    enabled: bool = False
    preferred_camera_id: str = ""
    bind_host: str = "127.0.0.1"
    port: int = 8765
    quality: str = "balanced"

    def validate(self) -> None:
        if not 1024 <= int(self.port) <= 65535:
            raise ValueError("Live port must be between 1024 and 65535")
        if self.quality not in {"low", "balanced", "high"}:
            raise ValueError("Live quality must be low, balanced, or high")


class LiveSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> LiveSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            settings = LiveSettings(
                version=int(data.get("version", 1)),
                enabled=bool(data.get("enabled", False)),
                preferred_camera_id=str(data.get("preferred_camera_id", "")),
                bind_host=str(data.get("bind_host", "127.0.0.1")),
                port=int(data.get("port", 8765)),
                quality=str(data.get("quality", "balanced")),
            )
            settings.validate()
            return settings
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return LiveSettings()

    def save(self, settings: LiveSettings) -> None:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False)
        temporary = Path(handle.name)
        try:
            with handle:
                json.dump(asdict(settings), handle, indent=2)
                handle.write("\n")
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
