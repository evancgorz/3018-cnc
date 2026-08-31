from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from typing import Any

from .machine_records import MachineRecordStore
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


class CommissioningStatus(StrEnum):
    OFF = "off"
    DECLARED = "declared"
    NEEDS_COMMISSIONING = "needs_commissioning"
    IN_PROGRESS = "in_progress"
    COMMISSIONED = "commissioned"
    FAILED = "failed"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityEvidence:
    """Machine-scoped proof that an optional capability was tested."""

    status: CommissioningStatus = CommissioningStatus.DECLARED
    fingerprint: str = ""
    timestamp: str = ""
    measurements: dict[str, float] | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityEvidence":
        return cls(status=CommissioningStatus(data.get("status", CommissioningStatus.DECLARED)),
                   fingerprint=str(data.get("fingerprint", "")), timestamp=str(data.get("timestamp", "")),
                   measurements=dict(data.get("measurements") or {}) or None, note=str(data.get("note", "")))


@dataclass(frozen=True)
class CommissioningRecord:
    machine_id: str
    capabilities: dict[str, CapabilityEvidence]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "machine_id": self.machine_id,
                "capabilities": {key: value.to_dict() for key, value in self.capabilities.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommissioningRecord":
        if data.get("schema_version", 1) != 1:
            raise ValueError("Unsupported commissioning schema version")
        machine_id = str(data.get("machine_id", ""))
        if not machine_id:
            raise ValueError("Commissioning record requires a machine ID")
        return cls(machine_id, {key: CapabilityEvidence.from_dict(value) for key, value in data.get("capabilities", {}).items()})


def invalidate_evidence(
    old_fingerprints: dict[str, str],
    new_fingerprints: dict[str, str],
    evidence: dict[str, CapabilityEvidence],
) -> dict[str, CapabilityEvidence]:
    """Mark only changed dependency areas stale, preserving cosmetic records."""
    result = dict(evidence)
    for capability, item in evidence.items():
        if item.status not in {CommissioningStatus.COMMISSIONED, CommissioningStatus.STALE}:
            continue
        if old_fingerprints.get(capability) != new_fingerprints.get(capability):
            result[capability] = CapabilityEvidence(
                status=CommissioningStatus.STALE, fingerprint=new_fingerprints.get(capability, ""),
                timestamp=item.timestamp, measurements=item.measurements, note="Machine configuration changed; recommission this capability."
            )
    return result


def capability_ready(
    capability: str,
    *,
    declared: bool,
    evidence: CapabilityEvidence | None,
    adapter_supported: bool,
) -> tuple[bool, str]:
    if not declared:
        return False, "Capability is disabled in this machine profile."
    if not adapter_supported:
        return False, "The selected controller does not support this capability."
    if evidence is None or evidence.status is not CommissioningStatus.COMMISSIONED:
        return False, "Capability must be commissioned for the current machine configuration."
    return True, "Capability is ready."


class CommissioningRecordStore:
    def __init__(self, path: Path) -> None:
        self.records = MachineRecordStore(path)

    def load(self, machine_id: str) -> CommissioningRecord | None:
        data = self.records.load(machine_id)
        return CommissioningRecord.from_dict(data) if data is not None else None

    def save(self, record: CommissioningRecord) -> None:
        if not record.machine_id.strip():
            raise ValueError("Commissioning record requires a machine ID")
        self.records.save(record.machine_id, record.to_dict())
