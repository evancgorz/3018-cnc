"""Simulation-only persistence; never shares physical controller settings."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any

from .models import SimulationProfile, SimulationWorkpiece


@dataclass(frozen=True)
class SimulationSettings:
    schema_version: int = 1
    speed: str = "realtime"
    workpiece: SimulationWorkpiece = SimulationWorkpiece()
    profile: SimulationProfile = SimulationProfile()

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported simulation settings schema")
        if self.speed not in {"realtime", "2x", "5x", "10x", "uncapped"}:
            raise ValueError("Unknown simulation speed")
        self.profile.validate()
        self.workpiece.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schema_version": self.schema_version, "speed": self.speed,
                "workpiece": asdict(self.workpiece), "profile": self.profile.to_dict()}


class SimulationSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> SimulationSettings:
        if not self.path.exists():
            return SimulationSettings()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Simulation settings must be an object")
        workpiece = SimulationWorkpiece(**dict(data.get("workpiece", {})))
        profile = SimulationProfile(**dict(data.get("profile", {})))
        settings = SimulationSettings(int(data.get("schema_version", 1)), str(data.get("speed", "realtime")), workpiece, profile)
        settings.validate()
        return settings

    def save(self, settings: SimulationSettings) -> None:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
