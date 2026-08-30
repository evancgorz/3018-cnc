from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .step_engraver import STEP_ORIENTATIONS, STEP_ZERO_LOCATIONS


@dataclass(frozen=True)
class StepPrepareSettings:
    """Reusable operator preferences for the guided STEP preparation flow."""

    orientation: str = "Top (XY)"
    zero_location: str = "Lower-left"
    tool_diameter: float = 3.175
    passes: int = 2
    max_stepdown: float = 1.0
    safe_z: float = 3.0
    cut_feed: float = 300.0
    plunge_feed: float = 100.0
    spindle_rpm: int = 0
    breakthrough: float = 0.2
    tab_count: int = 4
    tab_width: float = 4.0
    tab_height: float = 0.8

    def validate(self) -> None:
        if self.orientation not in STEP_ORIENTATIONS:
            raise ValueError("Unknown STEP path orientation")
        if self.zero_location not in STEP_ZERO_LOCATIONS:
            raise ValueError("Unknown STEP work-zero location")
        finite = (
            self.tool_diameter,
            self.max_stepdown,
            self.safe_z,
            self.cut_feed,
            self.plunge_feed,
            self.breakthrough,
            self.tab_width,
            self.tab_height,
        )
        if not all(math.isfinite(value) for value in finite):
            raise ValueError("STEP preparation settings must be finite")
        if not 0.1 <= self.tool_diameter <= 20:
            raise ValueError("Tool diameter must be between 0.1 and 20 mm")
        if not isinstance(self.passes, int) or not 1 <= self.passes <= 100:
            raise ValueError("Depth passes must be a whole number from 1 to 100")
        if not 0 <= self.max_stepdown <= 20:
            raise ValueError("Maximum stepdown must be between 0 and 20 mm")
        if not 0.1 <= self.safe_z <= 100:
            raise ValueError("Safe Z must be between 0.1 and 100 mm")
        if not 1 <= self.cut_feed <= 3000 or not 1 <= self.plunge_feed <= 1000:
            raise ValueError("Cut and plunge feeds are outside the supported range")
        if not isinstance(self.spindle_rpm, int) or not 0 <= self.spindle_rpm <= 24000:
            raise ValueError("Spindle RPM must be a whole number from 0 to 24000")
        if not 0 <= self.breakthrough <= 2:
            raise ValueError("Breakthrough must be between 0 and 2 mm")
        if not isinstance(self.tab_count, int) or not 0 <= self.tab_count <= 12:
            raise ValueError("Tab count must be a whole number from 0 to 12")
        if not 0.5 <= self.tab_width <= 20:
            raise ValueError("Tab width must be between 0.5 and 20 mm")
        if not 0.1 <= self.tab_height <= 20:
            raise ValueError("Tab height must be between 0.1 and 20 mm")


class StepPrepareSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> StepPrepareSettings:
        if not self.path.exists():
            return StepPrepareSettings()
        settings = StepPrepareSettings(**json.loads(self.path.read_text(encoding="utf-8")))
        settings.validate()
        return settings

    def save(self, settings: StepPrepareSettings) -> None:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
