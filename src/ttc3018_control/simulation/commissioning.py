"""Synthetic-safe twin/controller A/B commissioning plans and reports.

This module deliberately operates on supplied captures.  It never discovers,
opens, or probes a physical endpoint; the guarded physical provider exists
only to make that boundary explicit for a future separately authorized run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .parity import ParityCapture, ParityTolerance, reject_physical_capture_without_authorization


COMMISSIONING_SCHEMA_VERSION = 1
DEFAULT_IGNORED_FIELDS = ("hardware_id", "pid", "port", "wall_time")
DEFAULT_ABORT_CATEGORIES = ("malformed", "missing", "extra", "semantic", "outlier", "unexpected_alarm")


@dataclass(frozen=True)
class CommissioningGate:
    name: str
    mode: str
    commands: tuple[str, ...]
    read_only: bool = True
    max_events: int = 64

    def validate(self) -> None:
        if not self.name or not self.mode or not self.commands:
            raise ValueError("Commissioning gates require a name, mode, and commands")
        if self.max_events <= 0:
            raise ValueError("Commissioning gate event budget must be positive")
        if not self.read_only and self.mode != "optional_cutting":
            raise ValueError("Only the optional cutting gate may be non-read-only")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode, "commands": list(self.commands),
                "read_only": self.read_only, "max_events": self.max_events}


@dataclass(frozen=True)
class CommissioningPlan:
    name: str
    gates: tuple[CommissioningGate, ...]
    tolerances: ParityTolerance = ParityTolerance()
    ignored_fields: tuple[str, ...] = DEFAULT_IGNORED_FIELDS
    abort_categories: tuple[str, ...] = DEFAULT_ABORT_CATEGORIES
    schema_version: int = COMMISSIONING_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != COMMISSIONING_SCHEMA_VERSION or not self.name:
            raise ValueError("Unsupported or malformed commissioning plan")
        if not self.gates:
            raise ValueError("Commissioning plan must contain at least one gate")
        for gate in self.gates:
            gate.validate()
        self.tolerances.validate()
        if len(set(self.ignored_fields)) != len(self.ignored_fields):
            raise ValueError("Commissioning ignored fields must be unique")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schema_version": self.schema_version, "name": self.name,
                "gates": [gate.to_dict() for gate in self.gates],
                "tolerances": asdict(self.tolerances),
                "ignored_fields": list(self.ignored_fields),
                "abort_categories": list(self.abort_categories)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CommissioningPlan":
        if not isinstance(data, Mapping):
            raise ValueError("Commissioning plan must be an object")
        try:
            tolerances = ParityTolerance(**dict(data["tolerances"]))
            gates = tuple(CommissioningGate(
                str(item["name"]), str(item["mode"]), tuple(str(command) for command in item["commands"]),
                bool(item.get("read_only", True)), int(item.get("max_events", 64)),
            ) for item in data["gates"])
            plan = cls(str(data["name"]), gates, tolerances,
                       tuple(str(item) for item in data.get("ignored_fields", DEFAULT_IGNORED_FIELDS)),
                       tuple(str(item) for item in data.get("abort_categories", DEFAULT_ABORT_CATEGORIES)),
                       int(data.get("schema_version", 0)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Malformed commissioning plan") from exc
        plan.validate()
        return plan

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def default_commissioning_plan() -> CommissioningPlan:
    """Return the bounded synthetic plan; no gate executes by constructing it."""
    return CommissioningPlan(
        name="pine-twin-controller-ab-v1",
        gates=(
            CommissioningGate("read_only_status", "read_only", ("?", "$$", "$#")),
            CommissioningGate("tiny_jog", "tiny_jog", ("$J=G91 G21 X1 F60",)),
            CommissioningGate("wco", "wco", ("G10 L20 P1 X0 Y0 Z0", "?")),
            CommissioningGate("probe", "probe", ("$#", "?")),
            CommissioningGate("spindle", "spindle", ("M3 S1000", "M5")),
            CommissioningGate("optional_cutting", "optional_cutting", ("G1 X1 F60",), read_only=False),
        ),
    )


def write_default_plan(path: Path) -> None:
    default_commissioning_plan().write(path)


class CaptureProvider(Protocol):
    def capture(self, plan: CommissioningPlan) -> ParityCapture: ...


class SyntheticCaptureProvider:
    """A supplied capture fixture; capture() performs no controller action."""

    def __init__(self, capture: ParityCapture) -> None:
        self.capture_data = capture

    def capture(self, plan: CommissioningPlan) -> ParityCapture:
        plan.validate()
        return self.capture_data


class PhysicalCaptureProvider:
    """Explicitly inert placeholder for a future physically authorized run."""

    def __init__(self, *, authorized: bool = False, endpoint: str = "") -> None:
        self.authorized = authorized
        self.endpoint = endpoint

    def capture(self, plan: CommissioningPlan) -> ParityCapture:
        plan.validate()
        reject_physical_capture_without_authorization(authorized=self.authorized, endpoint=self.endpoint)
        raise RuntimeError("Physical A/B capture is not executable from the synthetic commissioning package")


@dataclass(frozen=True)
class CommissioningDifference:
    category: str
    message: str
    event_index: int | None = None
    field: str | None = None
    twin: Any = None
    controller: Any = None
    tolerated: bool = False


@dataclass(frozen=True)
class CommissioningReport:
    matched: bool
    aborted: bool
    abort_reason: str | None
    first_divergence: str | None
    differences: tuple[CommissioningDifference, ...]
    ignored_fields: tuple[str, ...]
    tolerances: ParityTolerance
    plan_name: str
    twin: ParityCapture
    controller: ParityCapture

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMMISSIONING_SCHEMA_VERSION,
            "plan": self.plan_name,
            "matched": self.matched,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "first_divergence": self.first_divergence,
            "differences": [asdict(item) for item in self.differences],
            "ignored_fields": list(self.ignored_fields),
            "tolerances": asdict(self.tolerances),
            "twin": self.twin.to_dict(),
            "controller": self.controller.to_dict(),
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    def write_markdown(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Synthetic A/B commissioning report", "", f"- Plan: `{self.plan_name}`",
                 f"- Result: **{'PASS' if self.matched else 'FAIL'}**",
                 f"- Aborted: **{'yes' if self.aborted else 'no'}**",
                 f"- Digest: `{self.digest}`", "", "## Tolerances", "",
                 "| Position mm | Feed mm/min | Spindle RPM | Timing s |", "|---:|---:|---:|---:|",
                 f"| {self.tolerances.position_mm} | {self.tolerances.feed_mm_min} | {self.tolerances.spindle_rpm} | {self.tolerances.timing_seconds} |", "",
                 "## Differences", ""]
        if not self.differences:
            lines.append("No differences.")
        else:
            lines.extend("- " + item.message + (" (tolerated)" if item.tolerated else "") for item in self.differences)
        if self.abort_reason:
            lines.extend(["", f"**Abort:** {self.abort_reason}"])
        lines.extend(["", "## Ignored fields", "", ", ".join(self.ignored_fields) or "None", ""])
        path.write_text("\n".join(lines), encoding="utf-8")


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _finite(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    return False


def _capture_validation(capture: ParityCapture, label: str) -> list[CommissioningDifference]:
    differences: list[CommissioningDifference] = []
    previous_time = -1
    for index, event in enumerate(capture.events, start=1):
        if not isinstance(event, Mapping):
            differences.append(CommissioningDifference("malformed", f"{label} event {index} is not an object", index))
            continue
        if not _finite(event):
            differences.append(CommissioningDifference("malformed", f"{label} event {index} contains non-finite data", index))
        if "kind" in event and not isinstance(event["kind"], str):
            differences.append(CommissioningDifference("malformed", f"{label} event {index} kind is not text", index, "kind"))
        if "time_ns" in event:
            time_ns = event["time_ns"]
            if not isinstance(time_ns, (int, float)) or time_ns < 0 or time_ns < previous_time:
                differences.append(CommissioningDifference("malformed", f"{label} event {index} time is invalid or out of order", index, "time_ns"))
            else:
                previous_time = time_ns
    return differences


def compare_commissioning_captures(plan: CommissioningPlan, twin: ParityCapture, controller: ParityCapture) -> CommissioningReport:
    """Compare two ordered captures while retaining tolerated drift as evidence."""
    plan.validate()
    differences = _capture_validation(twin, "twin") + _capture_validation(controller, "controller")
    ignored = tuple(sorted(set(plan.ignored_fields)))
    max_count = max(len(twin.events), len(controller.events))
    for index in range(max_count):
        if index >= len(twin.events):
            differences.append(CommissioningDifference("extra", f"Controller event {index + 1} has no twin event", index + 1, twin= None, controller=controller.events[index]))
            continue
        if index >= len(controller.events):
            differences.append(CommissioningDifference("missing", f"Controller is missing twin event {index + 1}", index + 1, twin=twin.events[index], controller=None))
            continue
        left, right = twin.events[index], controller.events[index]
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            continue
        for key in sorted(set(left) | set(right)):
            if key in ignored:
                continue
            a, b = left.get(key), right.get(key)
            if a == b:
                continue
            category = "semantic"
            tolerated = False
            message = f"Event {index + 1} {key} differs"
            if key in {"x", "y", "z", "position_mm"} and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = abs(float(a) - float(b))
                category, tolerated = "numeric", delta <= plan.tolerances.position_mm
                message = f"Event {index + 1} {key} differs by {delta:g} mm"
                if not tolerated:
                    category = "outlier"
            elif key in {"feed", "feed_mm_min"} and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = abs(float(a) - float(b))
                category, tolerated = "numeric", delta <= plan.tolerances.feed_mm_min
                message = f"Event {index + 1} {key} differs by {delta:g} mm/min"
                if not tolerated:
                    category = "outlier"
            elif key in {"rpm", "spindle", "spindle_rpm"} and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = abs(float(a) - float(b))
                category, tolerated = "numeric", delta <= plan.tolerances.spindle_rpm
                message = f"Event {index + 1} {key} differs by {delta:g} RPM"
                if not tolerated:
                    category = "outlier"
            elif key in {"time_ns", "elapsed_seconds"} and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = abs(float(a) - float(b)) / (1_000_000_000 if key == "time_ns" else 1)
                category, tolerated = "timing", delta <= plan.tolerances.timing_seconds
                message = f"Event {index + 1} {key} timing differs by {delta:g} s"
                if not tolerated:
                    category = "outlier"
            differences.append(CommissioningDifference(category, message, index + 1, key, a, b, tolerated))
    for label, capture in (("twin", twin), ("controller", controller)):
        for index, event in enumerate(capture.events, start=1):
            if isinstance(event, Mapping) and event.get("kind") == "alarm" and event.get("expected", False) is not True:
                differences.append(CommissioningDifference("unexpected_alarm", f"Unexpected alarm in {label} event {index}", index, "kind", event.get("kind"), event.get("kind")))
    abort = next((item for item in differences if item.category in plan.abort_categories), None)
    first = abort.message if abort else None
    return CommissioningReport(not abort, bool(abort), abort.message if abort else None, first,
                               tuple(differences), ignored, plan.tolerances, plan.name, twin, controller)


def _provider_capture(provider: CaptureProvider | Callable[[CommissioningPlan], ParityCapture], plan: CommissioningPlan) -> ParityCapture:
    capture = provider.capture(plan) if hasattr(provider, "capture") else provider(plan)
    if not isinstance(capture, ParityCapture):
        raise TypeError("Capture providers must return ParityCapture")
    return capture


def run_commissioning_ab(plan: CommissioningPlan, twin_provider: CaptureProvider | Callable[[CommissioningPlan], ParityCapture],
                         controller_provider: CaptureProvider | Callable[[CommissioningPlan], ParityCapture],
                         output_dir: Path | None = None) -> CommissioningReport:
    """Run comparison against supplied providers and optionally persist replay files."""
    plan.validate()
    twin = _provider_capture(twin_provider, plan)
    controller = _provider_capture(controller_provider, plan)
    report = compare_commissioning_captures(plan, twin, controller)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        report.write_json(output_dir / "commissioning_report.json")
        report.write_markdown(output_dir / "commissioning_report.md")
        twin.write(output_dir / "twin_capture.json")
        controller.write(output_dir / "controller_capture.json")
    return report


def replay_commissioning_report(path: Path) -> CommissioningReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != COMMISSIONING_SCHEMA_VERSION:
        raise ValueError("Unsupported commissioning report schema")
    plan = CommissioningPlan(name=str(data["plan"]), gates=default_commissioning_plan().gates,
                             tolerances=ParityTolerance(**data["tolerances"]),
                             ignored_fields=tuple(data["ignored_fields"]))
    twin = ParityCapture(data["twin"]["events"], source=str(data["twin"].get("source", "twin")))
    controller = ParityCapture(data["controller"]["events"], source=str(data["controller"].get("source", "controller")))
    return compare_commissioning_captures(plan, twin, controller)


def synthetic_commissioning_fixtures() -> dict[str, tuple[ParityCapture, ParityCapture]]:
    """Return deterministic fixture pairs for the plan's review cases."""
    base = [
        {"sequence": 1, "kind": "status", "state": "Idle", "x": 0.0, "feed": 0.0, "rpm": 0.0, "time_ns": 0},
        {"sequence": 2, "kind": "jog", "state": "Idle", "x": 1.0, "feed": 60.0, "rpm": 0.0, "time_ns": 1_000_000_000},
        {"sequence": 3, "kind": "wco", "wco": {"x": 1.0, "y": 2.0, "z": 3.0}, "time_ns": 2_000_000_000},
        {"sequence": 4, "kind": "probe", "probe": "open", "time_ns": 3_000_000_000},
        {"sequence": 5, "kind": "spindle", "rpm": 1000.0, "time_ns": 4_000_000_000},
    ]
    twin = ParityCapture(base, source="synthetic-twin")
    matched = ParityCapture([dict(event) for event in base], source="fake-controller")
    drift = [dict(event) for event in base]
    drift[1]["x"] = 1.02
    drift[1]["feed"] = 61.0
    drift[1]["time_ns"] = 1_100_000_000
    tolerated = ParityCapture(drift, source="fake-controller-drift")
    semantic = [dict(event) for event in base]
    semantic[2]["wco"] = {"x": 9.0, "y": 2.0, "z": 3.0}
    semantic[3]["probe"] = "triggered"
    semantic_capture = ParityCapture(semantic, source="fake-controller-semantic")
    alarm = [dict(event) for event in base]
    alarm.append({"sequence": 6, "kind": "alarm", "code": 1, "time_ns": 5_000_000_000})
    missing = ParityCapture(base[:-1], source="fake-controller-missing")
    malformed = ParityCapture([dict(base[0]), {"kind": "status", "x": float("nan")}], source="malformed")
    return {
        "matched": (twin, matched),
        "tolerated_drift": (twin, tolerated),
        "semantic_mismatch": (twin, semantic_capture),
        "unexpected_alarm": (twin, ParityCapture(alarm, source="fake-controller-alarm")),
        "missing_response": (twin, missing),
        "malformed_capture": (twin, malformed),
    }


PHYSICAL_PREFLIGHT_CHECKLIST = (
    "Separate explicit user authorization for physical A/B capture",
    "Exact endpoint selected and independently verified; no discovery/default endpoint",
    "Emergency-stop tested and reachable; spindle power off before setup",
    "Workholding, tool retention, clearance, and sacrificial material verified",
    "Trusted machine reference, WCO, probe input, and travel envelope verified",
    "Abort criteria and evidence operator assigned before any motion",
)


def physical_preflight_checklist() -> tuple[str, ...]:
    """Return the checklist only; this function performs no physical action."""
    return PHYSICAL_PREFLIGHT_CHECKLIST
