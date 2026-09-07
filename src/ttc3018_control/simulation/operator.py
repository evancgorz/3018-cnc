"""Independent virtual operator and safety actor.

This module is deliberately transport/application/backend free.  It receives
immutable plant observations and returns immutable hazard/intent records.  The
runtime owns the actor process and is the only boundary that routes its typed
intents back toward the application.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from .geometry import AABB, CoordinateFrame, MachineGeometryProfile, swept_bounds
from .models import Hazard, HazardKind, PlantSnapshot, SimulationProfile, SimulationWorkpiece


@dataclass(frozen=True)
class OperatorFixture:
    """Immutable fixture proxy supplied to the independent actor."""

    name: str
    bounds: AABB
    frame: str = "machine"

    def __post_init__(self) -> None:
        if not self.name or self.frame not in {"machine", "work"}:
            raise ValueError("Operator fixture requires a name and machine/work frame")
        self.bounds.validate()

    def machine_bounds(self, frame: CoordinateFrame) -> AABB:
        return self.bounds if self.frame == "machine" else frame.work_bounds_to_machine(self.bounds)


@dataclass(frozen=True)
class OperatorIntent:
    """Typed action returned by the independent actor."""

    action: str
    reason: str
    sequence: int
    hazard_kind: str = ""

    def __post_init__(self) -> None:
        if self.action not in {"hold", "abort", "interlock", "recover", "recovery_denied"}:
            raise ValueError(f"Unknown operator action: {self.action}")
        if not self.reason:
            raise ValueError("Operator intent requires a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "sequence": self.sequence,
            "hazard_kind": self.hazard_kind,
            "source": "independent_operator",
        }


@dataclass(frozen=True)
class OperatorAssessment:
    """Result of one immutable observation submitted to the actor."""

    snapshot_sequence: int
    hazards: tuple[Hazard, ...] = ()
    cleared: tuple[tuple[str, str, str], ...] = ()
    intents: tuple[OperatorIntent, ...] = ()
    stale: bool = False
    disagreement: bool = False


class IndependentVirtualOperator:
    """Recompute safety facts without calling the backend collision oracle."""

    _ALARM_KINDS = frozenset({
        HazardKind.TRAVEL_LIMIT, HazardKind.MACHINE_COLLISION,
        HazardKind.TOOL_STOCK, HazardKind.HOLDER_STOCK,
        HazardKind.TOOL_FIXTURE, HazardKind.HOLDER_FIXTURE,
        HazardKind.TOOL_BED, HazardKind.RAPID_STOCK,
        HazardKind.SPINDLE_OFF_ENTRY, HazardKind.EXCESSIVE_DEPTH,
        HazardKind.RETAINED_GOUGE,
    })

    def __init__(self, profile: SimulationProfile | None = None,
                 workpiece: SimulationWorkpiece | None = None,
                 fixtures: Iterable[OperatorFixture] = (),
                 *, stale_after_ns: int = 2_000_000_000,
                 recovery_token: str = "operator-recovery") -> None:
        self.profile = profile or SimulationProfile.default_3018()
        self.profile.validate()
        if stale_after_ns <= 0:
            raise ValueError("stale_after_ns must be positive")
        if not recovery_token:
            raise ValueError("recovery_token must not be empty")
        self.workpiece = workpiece
        if workpiece is not None:
            workpiece.validate()
        self.geometry = MachineGeometryProfile.default_3018(self.profile)
        self.fixtures = tuple(fixtures)
        self.stale_after_ns = stale_after_ns
        self.recovery_token = recovery_token
        self._previous: PlantSnapshot | None = None
        self._last_sequence = -1
        self._last_time_ns = -1
        self._active_keys: set[tuple[str, str, str]] = set()
        self._failed = False
        self._last_intent_sequence = -1

    @staticmethod
    def _key(hazard: Hazard) -> tuple[str, str, str]:
        return hazard.kind.value, hazard.body_a, hazard.body_b

    @staticmethod
    def _same_pose(first: PlantSnapshot, second: PlantSnapshot) -> bool:
        return math.dist(first.machine_position, second.machine_position) <= 1e-9

    def observe(self, current: PlantSnapshot, *, expected_hazards: Iterable[Hazard] | None = None) -> OperatorAssessment:
        """Assess one fresh snapshot and emit only hazard edges and intents."""
        if not isinstance(current, PlantSnapshot):
            raise TypeError("Operator observations must be PlantSnapshot records")
        if current.sequence <= self._last_sequence or current.time_ns <= self._last_time_ns:
            hazard = Hazard(HazardKind.PROTOCOL, "Stale machine snapshot received", current.time_ns,
                            current.machine_position, source="independent_operator")
            self._failed = True
            return OperatorAssessment(current.sequence, (hazard,), (),
                                      self._failure_intents(hazard, current.sequence), stale=True)
        self._last_sequence = current.sequence
        self._last_time_ns = current.time_ns
        if self._previous is not None and current.time_ns - self._previous.time_ns > self.stale_after_ns:
            hazard = Hazard(HazardKind.PROTOCOL, "Machine snapshot heartbeat is stale", current.time_ns,
                            current.machine_position, source="independent_operator")
            self._failed = True
            return OperatorAssessment(current.sequence, (hazard,), (),
                                      self._failure_intents(hazard, current.sequence), stale=True)

        observed = (self._recompute(self._previous, current)
                    if self._previous is not None and current.state in {"Run", "Jog", "Hold:0", "Hold"}
                    else ())
        observed_keys = {self._key(item) for item in observed}
        new_hazards = tuple(item for item in observed if self._key(item) not in self._active_keys)
        cleared = tuple(sorted(self._active_keys - observed_keys))
        self._active_keys = observed_keys
        self._previous = current

        expected = tuple(expected_hazards) if expected_hazards is not None else ()
        disagreement = expected_hazards is not None and {self._key(item) for item in expected} != observed_keys
        if disagreement:
            new_hazards += (Hazard(HazardKind.DIVERGENCE,
                                   "Independent operator disagrees with backend hazard verdict",
                                   current.time_ns, current.machine_position,
                                   source="independent_operator"),)
        intents: list[OperatorIntent] = []
        for hazard in new_hazards:
            intents.extend(self._hazard_intents(hazard, current.sequence))
        return OperatorAssessment(current.sequence, new_hazards, cleared, tuple(intents), disagreement=disagreement)

    def report_failure(self, reason: str, *, sequence: int | None = None) -> OperatorAssessment:
        """Fail closed when the owned supervisor/runtime cannot continue."""
        if not reason:
            raise ValueError("Failure reason must not be empty")
        self._failed = True
        seq = self._last_sequence if sequence is None else sequence
        hazard = Hazard(HazardKind.SUPERVISOR_UNAVAILABLE, reason, max(0, self._last_time_ns),
                        self._previous.machine_position if self._previous else (0.0, 0.0, 0.0),
                        source="independent_operator")
        return OperatorAssessment(seq, (hazard,), (), self._failure_intents(hazard, seq))

    def consume_intent(self, intent: dict[str, Any]) -> tuple[OperatorIntent, ...]:
        """Validate an immutable user-intent event before it reaches the app."""
        if not isinstance(intent, dict):
            return (OperatorIntent("interlock", "Malformed operator intent", self._last_intent_sequence),)
        sequence = int(intent.get("sequence", self._last_intent_sequence + 1))
        if sequence <= self._last_intent_sequence:
            return (OperatorIntent("abort", "Stale operator intent rejected", sequence),
                    OperatorIntent("interlock", "Stale operator intent rejected", sequence))
        self._last_intent_sequence = sequence
        name = str(intent.get("name", ""))
        reason = str(intent.get("reason", f"Operator requested {name or 'unknown action'}"))
        if name in {"hold", "pause", "pause_job"}:
            return (OperatorIntent("hold", reason, sequence),)
        if name in {"abort", "abort_job"}:
            return (OperatorIntent("abort", reason, sequence),)
        return ()

    def authorize_recovery(self, authorization: str, snapshot: PlantSnapshot) -> OperatorAssessment:
        """Require explicit authorization and a fresh hazard-free Idle sample."""
        if authorization != self.recovery_token:
            intent = OperatorIntent("recovery_denied", "Recovery authorization was not accepted",
                                    snapshot.sequence, HazardKind.SUPERVISOR_UNAVAILABLE.value)
            return OperatorAssessment(snapshot.sequence, intents=(intent,), stale=False)
        assessment = self.observe(snapshot)
        if assessment.stale or assessment.hazards or snapshot.state not in {"Idle", "Alarm"}:
            return OperatorAssessment(snapshot.sequence, assessment.hazards, assessment.cleared,
                                      assessment.intents + (OperatorIntent(
                                          "recovery_denied", "Recovery requires a fresh hazard-free Idle/Alarm snapshot",
                                          snapshot.sequence),), assessment.stale, assessment.disagreement)
        self._failed = False
        return OperatorAssessment(snapshot.sequence, assessment.hazards, assessment.cleared,
                                  (OperatorIntent("recover", "Explicit operator recovery authorization accepted",
                                                  snapshot.sequence),))

    def _failure_intents(self, hazard: Hazard, sequence: int) -> tuple[OperatorIntent, ...]:
        reason = hazard.message
        return (OperatorIntent("hold", reason, sequence, hazard.kind.value),
                OperatorIntent("abort", reason, sequence, hazard.kind.value),
                OperatorIntent("interlock", reason, sequence, hazard.kind.value))

    def _hazard_intents(self, hazard: Hazard, sequence: int) -> tuple[OperatorIntent, ...]:
        if hazard.kind not in self._ALARM_KINDS:
            return (OperatorIntent("interlock", hazard.message, sequence, hazard.kind.value),)
        return (OperatorIntent("hold", hazard.message, sequence, hazard.kind.value),
                OperatorIntent("interlock", hazard.message, sequence, hazard.kind.value))

    def _recompute(self, previous: PlantSnapshot | None, current: PlantSnapshot) -> tuple[Hazard, ...]:
        if previous is None:
            return ()
        hazards: list[Hazard] = []
        frame = CoordinateFrame(tuple(current.work_offset))
        limits = (self.profile.travel_x, self.profile.travel_y, self.profile.travel_z)
        if any(value < -0.001 or value > limit + 0.001
               for value, limit in zip(current.machine_position, limits)):
            hazards.append(self._hazard(HazardKind.TRAVEL_LIMIT, "Axis exceeded virtual travel", current))
        tool = swept_bounds(previous, current, "cutter", self.geometry, self.profile)
        holder = swept_bounds(previous, current, "tool-holder", self.geometry, self.profile)
        for body in self.geometry.bodies(current, self.profile):
            if body.name in {"left-upright", "right-upright"} and holder.penetrates(body.bounds):
                hazards.append(self._hazard(HazardKind.MACHINE_COLLISION,
                                            "Tool holder intersects fixed frame upright", current,
                                            "tool-holder", body.name))
        bed = AABB(-self.geometry.base_margin, -self.geometry.base_margin, -8.0,
                   self.profile.travel_x + self.geometry.base_margin,
                   self.profile.travel_y + self.geometry.base_margin, -0.1)
        if tool.penetrates(bed):
            hazards.append(self._hazard(HazardKind.TOOL_BED, "Cutter intersects bed/spoilboard", current, "cutter", "bed"))
        for fixture in self.fixtures:
            fixture_bounds = fixture.machine_bounds(frame)
            if tool.penetrates(fixture_bounds):
                hazards.append(self._hazard(HazardKind.TOOL_FIXTURE, "Cutter intersects fixture", current, "cutter", fixture.name))
            if holder.penetrates(fixture_bounds):
                hazards.append(self._hazard(HazardKind.HOLDER_FIXTURE, "Holder intersects fixture", current, "tool-holder", fixture.name))
        if self.workpiece is not None:
            hazards.extend(self._stock_hazards(previous, current, tool, holder))
        motion = current.motion
        if current.state in {"Run", "Hold:0", "Hold"} and motion is not None and not motion.probing:
            if self._same_pose(previous, current) and motion.target != motion.start and motion.progress < 1.0:
                hazards.append(self._hazard(HazardKind.STALLED_MOTION,
                                            "Controller reports motion without pose progress", current,
                                            "controller", "machine"))
        return tuple(hazards)

    def _stock_hazards(self, previous: PlantSnapshot, current: PlantSnapshot,
                       tool: AABB, holder: AABB) -> list[Hazard]:
        stock = self.workpiece
        assert stock is not None
        box = CoordinateFrame(tuple(current.work_offset)).work_bounds_to_machine(AABB(
            stock.origin_x, stock.origin_y, stock.origin_z - stock.stock_thickness,
            stock.origin_x + stock.stock_width, stock.origin_y + stock.stock_height,
            stock.origin_z))
        penetrates = (tool.max_x > box.min_x and tool.min_x < box.max_x
                      and tool.max_y > box.min_y and tool.min_y < box.max_y
                      and tool.min_z < box.max_z and tool.max_z > box.min_z)
        rapid = bool(current.motion and current.motion.rapid)
        downward = current.machine_position[2] < previous.machine_position[2] - 1e-9
        horizontal_or_down = current.machine_position[2] <= previous.machine_position[2] + 1e-9
        hazards: list[Hazard] = []
        if penetrates and (downward or (rapid and horizontal_or_down)):
            if rapid:
                hazards.append(self._hazard(HazardKind.RAPID_STOCK, "Rapid move enters stock", current, "cutter", "stock"))
            elif current.spindle_rpm <= 1.0:
                hazards.append(self._hazard(HazardKind.SPINDLE_OFF_ENTRY,
                                            "Cutter enters stock with spindle off", current, "cutter", "stock"))
            if tool.min_z < box.min_z:
                hazards.append(self._hazard(HazardKind.EXCESSIVE_DEPTH,
                                            "Cutter exceeds stock bottom", current, "cutter", "stock"))
        # Holder contact remains conservative even though cutter top-plane
        # contact is not considered stock entry.
        if holder.intersects(box):
            hazards.append(self._hazard(HazardKind.HOLDER_STOCK, "Tool holder intersects stock", current,
                                        "tool-holder", "stock"))
        return hazards

    @staticmethod
    def _hazard(kind: HazardKind, message: str, snapshot: PlantSnapshot,
                body_a: str = "", body_b: str = "") -> Hazard:
        return Hazard(kind, message, snapshot.time_ns, snapshot.machine_position,
                      body_a, body_b, source="independent_operator")
