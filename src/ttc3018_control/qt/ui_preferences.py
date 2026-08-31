"""Versioned, non-safety UI preferences."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass
class UiPreferences:
    version: int = 1
    first_run_complete: bool = False
    expert_mode: bool = False
    last_workspace: int = 2
    coordinates_expanded: bool = False


class UiPreferencesStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> UiPreferences:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or int(raw.get("version", 0)) != 1:
                return UiPreferences()
            return UiPreferences(
                first_run_complete=bool(raw.get("first_run_complete", False)),
                expert_mode=bool(raw.get("expert_mode", False)),
                last_workspace=max(0, min(2, int(raw.get("last_workspace", 2)))),
                coordinates_expanded=bool(raw.get("coordinates_expanded", False)),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return UiPreferences()

    def save(self, preferences: UiPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
            json.dump(asdict(preferences), handle, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(self.path)
