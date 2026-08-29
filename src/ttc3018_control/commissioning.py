from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass
class CommissioningProfile:
    x_limit_tested: bool = False
    y_limit_tested: bool = False
    z_limit_tested: bool = False
    probe_tested: bool = False
    x_positive_confirmed: bool = False
    y_positive_confirmed: bool = False
    z_positive_confirmed: bool = False
    homing_settings_reviewed: bool = False
    homing_verified: bool = False
    plate_thickness: float = 0.0
    x_edge_offset: float = 0.0
    y_edge_offset: float = 0.0
    hole_diameter: float = 0.0

    def validate(self) -> None:
        for name in ("plate_thickness", "x_edge_offset", "y_edge_offset", "hole_diameter"):
            value = float(getattr(self, name))
            if value < 0 or value > 100:
                raise ValueError(f"{name.replace('_', ' ').title()} must be between 0 and 100 mm")

    @property
    def limits_tested(self) -> bool:
        return self.x_limit_tested and self.y_limit_tested and self.z_limit_tested

    @property
    def directions_confirmed(self) -> bool:
        return self.x_positive_confirmed and self.y_positive_confirmed and self.z_positive_confirmed

    @property
    def ready_for_homing_test(self) -> bool:
        return self.limits_tested and self.directions_confirmed and self.homing_settings_reviewed

    @property
    def ready_for_probe_motion(self) -> bool:
        return self.homing_verified and self.probe_tested and self.plate_thickness > 0


class CommissioningStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CommissioningProfile:
        if not self.path.exists():
            return CommissioningProfile()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        known = CommissioningProfile.__dataclass_fields__
        profile = CommissioningProfile(**{key: value for key, value in data.items() if key in known})
        profile.validate()
        return profile

    def save(self, profile: CommissioningProfile) -> None:
        profile.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(profile), indent=2) + "\n", encoding="utf-8")


@dataclass
class InputTestResult:
    state: str
    message: str
    passed: bool = False


class InputTestTracker:
    """Require one intended input to transition inactive -> active -> inactive."""

    VALID_TARGETS = {"X", "Y", "Z", "P"}

    def __init__(self) -> None:
        self.target: str | None = None
        self.state = "idle"

    def start(self, target: str, active_pins: str) -> InputTestResult:
        target = target.upper()
        if target not in self.VALID_TARGETS:
            raise ValueError("Input target must be X, Y, Z, or P")
        active = set(active_pins.upper()) & self.VALID_TARGETS
        if active:
            self.target = None
            self.state = "blocked"
            return InputTestResult("blocked", f"Release active input(s) first: {''.join(sorted(active))}")
        self.target = target
        self.state = "awaiting_press"
        return InputTestResult(self.state, f"Press and hold the {self._name(target)}.")

    def update(self, active_pins: str) -> InputTestResult:
        if self.target is None:
            return InputTestResult(self.state, "Start an input test first.")
        active = set(active_pins.upper()) & self.VALID_TARGETS
        unexpected = active - {self.target}
        if unexpected:
            self.state = "failed"
            return InputTestResult(
                "failed",
                f"Unexpected input(s) also activated: {''.join(sorted(unexpected))}. Check wiring.",
            )
        if self.state == "awaiting_press":
            if self.target in active:
                self.state = "awaiting_release"
                return InputTestResult(self.state, f"{self._name(self.target).title()} detected. Release it now.")
            return InputTestResult(self.state, f"Waiting for the {self._name(self.target)} to activate…")
        if self.state == "awaiting_release":
            if self.target not in active:
                self.state = "passed"
                return InputTestResult("passed", f"{self._name(self.target).title()} passed.", True)
            return InputTestResult(self.state, f"Release the {self._name(self.target)}.")
        return InputTestResult(self.state, "Restart this input test.")

    @staticmethod
    def _name(target: str) -> str:
        return "probe plate" if target == "P" else f"{target} limit switch"
