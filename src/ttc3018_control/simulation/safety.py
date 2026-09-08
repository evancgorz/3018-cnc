"""Deterministic, hardware-inert homing, E-stop, and XYZ datum contracts.

The classes in this module are deliberately pure software boundaries.  They
model the information that a real commissioning adapter would provide, but
never open GPIO, reset pins, serial ports, or network endpoints.  The twin
uses the same records so safety behaviour can be replayed without a machine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Any, Iterable

from .plant import ProbeBoundary


def _finite(values: Iterable[float], label: str) -> None:
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError(f"{label} must be finite")


class AxisEnd(StrEnum):
    MIN = "min"
    MAX = "max"


@dataclass(frozen=True)
class AxisSensorDeclaration:
    """One optional homing/limit input, including its electrical polarity."""

    axis: str
    travel: float
    homing_end: AxisEnd = AxisEnd.MIN
    active_low: bool = False
    input_pin: str | None = None
    hard_limit: bool = False
    debounce_ms: float = 5.0
    max_override: float | None = None

    def validate(self) -> None:
        axis = self.axis.upper()
        if axis not in "XYZ":
            raise ValueError("axis must be X, Y, or Z")
        if self.travel <= 0 or not math.isfinite(self.travel):
            raise ValueError("axis travel must be finite and positive")
        if self.max_override is not None and (self.max_override <= 0 or not math.isfinite(self.max_override)):
            raise ValueError("max_override must be finite and positive")
        if self.debounce_ms < 0 or not math.isfinite(self.debounce_ms):
            raise ValueError("debounce_ms must be finite and nonnegative")
        if self.hard_limit and not self.input_pin:
            raise ValueError("hard-limit input requires input_pin")

    @property
    def effective_travel(self) -> float:
        self.validate()
        return self.max_override if self.max_override is not None else self.travel


@dataclass(frozen=True)
class HomingLimitProfile:
    """Versioned machine-scoped switch declarations and migration boundary."""

    schema_version: int = 1
    machine_id: str = ""
    axes: tuple[AxisSensorDeclaration, ...] = ()

    @classmethod
    def default_3018(cls, machine_id: str = "digital-twin-3018") -> "HomingLimitProfile":
        return cls(machine_id=machine_id, axes=tuple(
            AxisSensorDeclaration(axis, travel, AxisEnd.MIN)
            for axis, travel in zip("XYZ", (290.0, 170.0, 40.0))))

    @classmethod
    def migrate(cls, data: dict[str, Any], *, machine_id: str) -> "HomingLimitProfile":
        """Migrate legacy ``axes`` mappings without silently enabling inputs."""
        if not isinstance(data, dict):
            raise ValueError("homing profile must be an object")
        raw_axes = data.get("axes", data.get("switches", {}))
        axes: list[AxisSensorDeclaration] = []
        for axis, travel in zip("XYZ", (290.0, 170.0, 40.0)):
            raw = dict(raw_axes.get(axis, {})) if isinstance(raw_axes, dict) else {}
            axes.append(AxisSensorDeclaration(
                axis=axis, travel=float(raw.get("travel", travel)),
                homing_end=AxisEnd(raw.get("homing_end", raw.get("switch_end", "min"))),
                active_low=bool(raw.get("active_low", False)),
                input_pin=raw.get("input_pin"), hard_limit=bool(raw.get("hard_limit", False)),
                debounce_ms=float(raw.get("debounce_ms", 5.0)),
                max_override=raw.get("max_override"),
            ))
        profile = cls(schema_version=int(data.get("schema_version", 1)), machine_id=machine_id,
                      axes=tuple(axes))
        profile.validate()
        return profile

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"unsupported homing profile schema: {self.schema_version}")
        if not self.machine_id.strip():
            raise ValueError("machine_id must be non-empty")
        if {axis.axis.upper() for axis in self.axes} != set("XYZ"):
            raise ValueError("one homing declaration is required for each X/Y/Z axis")
        for declaration in self.axes:
            declaration.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        data = asdict(self)
        data["axes"] = [{**asdict(axis), "homing_end": axis.homing_end.value} for axis in self.axes]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HomingLimitProfile":
        if not isinstance(data, dict):
            raise ValueError("homing profile must be an object")
        axes = tuple(AxisSensorDeclaration(
            axis=str(raw["axis"]), travel=float(raw["travel"]),
            homing_end=AxisEnd(raw.get("homing_end", "min")),
            active_low=bool(raw.get("active_low", False)), input_pin=raw.get("input_pin"),
            hard_limit=bool(raw.get("hard_limit", False)), debounce_ms=float(raw.get("debounce_ms", 5.0)),
            max_override=raw.get("max_override"),
        ) for raw in data.get("axes", ()))
        profile = cls(int(data.get("schema_version", 1)), str(data.get("machine_id", "")), axes)
        profile.validate()
        return profile

    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class HomingCommissioningRecord:
    schema_version: int = 1
    machine_id: str = ""
    profile_fingerprint: str = ""
    tested_inputs: dict[str, bool] = field(default_factory=dict)
    directions_confirmed: bool = False
    homing_verified: bool = False

    def valid_for(self, profile: HomingLimitProfile) -> bool:
        profile.validate()
        return (self.schema_version == 1 and self.machine_id == profile.machine_id
                and self.profile_fingerprint == profile.fingerprint()
                and all(self.tested_inputs.get(axis, False) for axis in "XYZ")
                and self.directions_confirmed and self.homing_verified)

    def invalidate_if_changed(self, profile: HomingLimitProfile) -> "HomingCommissioningRecord":
        if self.valid_for(profile):
            return self
        return HomingCommissioningRecord(machine_id=profile.machine_id, profile_fingerprint=profile.fingerprint())


class HomingSensorBank:
    """Debounced logical input bank used by the twin and commissioning tests."""

    def __init__(self, profile: HomingLimitProfile) -> None:
        profile.validate()
        self.profile = profile
        self._raw = {axis: False for axis in "XYZ"}
        self._active = {axis: False for axis in "XYZ"}
        self._changed_ns = {axis: 0 for axis in "XYZ"}

    def set_input(self, axis: str, electrical_active: bool, now_ns: int) -> bool:
        axis = axis.upper()
        declaration = next((item for item in self.profile.axes if item.axis.upper() == axis), None)
        if declaration is None:
            raise ValueError(f"unknown axis {axis}")
        logical = bool(electrical_active)
        if declaration.active_low:
            logical = not logical
        if logical != self._raw[axis]:
            self._raw[axis] = logical
            self._changed_ns[axis] = now_ns
        if now_ns - self._changed_ns[axis] >= round(declaration.debounce_ms * 1_000_000):
            self._active[axis] = self._raw[axis]
        return self._active[axis]

    def active(self, axis: str) -> bool:
        return bool(self._active[axis.upper()])

    def pins(self, polarity_inverted: bool = False) -> str:
        return "".join(axis for axis in "XYZ"
                       if (not self._active[axis] if polarity_inverted else self._active[axis]))

    def homing_position(self, direction_mask: int = 0) -> tuple[float, float, float]:
        """Return the switch pose, applying GRBL `$23` X/Y/Z inversion bits."""
        if not isinstance(direction_mask, int) or not 0 <= direction_mask <= 0xFF:
            raise ValueError("homing direction mask must be an integer from 0 to 255")
        positions: list[float] = []
        for index, axis in enumerate("XYZ"):
            declaration = next(item for item in self.profile.axes if item.axis.upper() == axis)
            at_max = declaration.homing_end is AxisEnd.MAX
            if direction_mask & (1 << index):
                at_max = not at_max
            positions.append(declaration.effective_travel if at_max else 0.0)
        return tuple(positions)


class EStopMode(StrEnum):
    DISABLED = "disabled"
    RESET_ONLY = "reset_only"
    FEEDBACK_ONLY = "feedback_only"
    RESET_PLUS_FEEDBACK = "reset_plus_feedback"


@dataclass(frozen=True)
class EStopDefinition:
    schema_version: int = 1
    mode: EStopMode = EStopMode.DISABLED
    input_pin: str | None = None
    reset_pin: str | None = None
    active_low: bool = True
    debounce_ms: float = 25.0
    manual_reset_required: bool = True

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported E-stop schema")
        if self.debounce_ms < 0 or not math.isfinite(self.debounce_ms):
            raise ValueError("E-stop debounce must be finite and nonnegative")
        if self.mode in {EStopMode.FEEDBACK_ONLY, EStopMode.RESET_PLUS_FEEDBACK} and not self.input_pin:
            raise ValueError("feedback E-stop mode requires input_pin")
        if self.mode in {EStopMode.RESET_ONLY, EStopMode.RESET_PLUS_FEEDBACK} and not self.reset_pin:
            raise ValueError("reset E-stop mode requires reset_pin")


@dataclass(frozen=True)
class EStopCommissioningRecord:
    schema_version: int = 1
    definition_fingerprint: str = ""
    input_tested: bool = False
    reset_tested: bool = False
    polarity_confirmed: bool = False

    def valid_for(self, definition: EStopDefinition) -> bool:
        definition.validate()
        encoded = json.dumps(asdict(definition), sort_keys=True, default=str).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        return self.schema_version == 1 and self.definition_fingerprint == fingerprint and (
            definition.mode is EStopMode.DISABLED or
            (self.input_tested if definition.mode in {EStopMode.FEEDBACK_ONLY, EStopMode.RESET_PLUS_FEEDBACK} else True) and
            (self.reset_tested if definition.mode in {EStopMode.RESET_ONLY, EStopMode.RESET_PLUS_FEEDBACK} else True) and
            self.polarity_confirmed)


class EStopLatch:
    """Fail-closed E-stop state machine; callbacks are notification-only."""

    def __init__(self, definition: EStopDefinition) -> None:
        definition.validate()
        self.definition = definition
        self.active = False
        self.latched = False
        self.feedback_confirmed = False
        self.recovery_authorized = False
        self._raw = False
        self._changed_ns = 0

    @property
    def interlocked(self) -> bool:
        return self.latched or self.active

    def observe(self, *, reset_asserted: bool = False, feedback_electrical: bool | None = None, now_ns: int = 0) -> bool:
        mode = self.definition.mode
        feedback = False
        if feedback_electrical is not None and mode in {EStopMode.FEEDBACK_ONLY, EStopMode.RESET_PLUS_FEEDBACK}:
            feedback = not feedback_electrical if self.definition.active_low else bool(feedback_electrical)
            if feedback != self._raw:
                self._raw, self._changed_ns = feedback, now_ns
            if now_ns - self._changed_ns >= round(self.definition.debounce_ms * 1_000_000):
                self.feedback_confirmed = self._raw
        reset_event = bool(reset_asserted) and mode in {EStopMode.RESET_ONLY, EStopMode.RESET_PLUS_FEEDBACK}
        asserted = (self.feedback_confirmed if mode is EStopMode.FEEDBACK_ONLY else
                    (reset_event or self.feedback_confirmed) if mode is EStopMode.RESET_PLUS_FEEDBACK else
                    reset_event if mode is EStopMode.RESET_ONLY else False)
        if asserted:
            self.active = True
            self.latched = True
            self.recovery_authorized = False
        return self.interlocked

    def release(self) -> None:
        self.active = False
        self.feedback_confirmed = False

    def acknowledge(self, *, controller_idle: bool, reference_trusted: bool) -> bool:
        if self.definition.mode is EStopMode.DISABLED:
            return True
        if self.active or self.feedback_confirmed or not controller_idle or not reference_trusted:
            return False
        self.recovery_authorized = True
        self.latched = False
        return True

    def status(self) -> dict[str, Any]:
        return {"mode": self.definition.mode.value, "active": self.active, "latched": self.latched,
                "feedback_confirmed": self.feedback_confirmed, "recovery_authorized": self.recovery_authorized,
                "interlocked": self.interlocked}


class CalibrationState(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    FITTED = "fitted"
    Z_TOUCH = "z_touch"
    COMPLETE = "complete"
    FAILED = "failed"


class CalibrationFailure(StrEnum):
    NONE = ""
    UNCOMMISSIONED = "uncommissioned"
    SEED_OUTSIDE_CIRCLE = "seed_outside_circle"
    NO_CONTACT = "no_contact"
    COLLISION = "collision_interlock"
    ESTOP = "estop_latched"
    STALE_WCO = "stale_wco"
    ENVELOPE = "out_of_envelope"
    RESIDUAL = "circle_residual"


class BoundaryTraceState(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    COMPLETE = "complete"
    FAILED = "failed"


class BoundaryTraceFailure(StrEnum):
    NONE = ""
    INVALID_BOUNDARY = "invalid_boundary"
    SEED_OUTSIDE = "seed_outside_boundary"
    GUARD = "safety_guard"
    NO_CONTACT = "no_contact"
    MALFORMED_REPORT = "malformed_probe_report"
    STALE_REPORT = "stale_probe_report"
    CONTRADICTORY = "contradictory_trace"
    ENVELOPE = "out_of_envelope"


@dataclass(frozen=True)
class BoundaryTraceResult:
    contacts: tuple[tuple[float, float, float], ...]


class ProbeBoundaryTraceWorkflow:
    """Bounded four-direction polygon edge trace over ordinary GRBL replies.

    This is a pure application-boundary orchestrator.  It emits commands for
    the caller to send through the existing transport and accepts only the
    matching ``ok`` then fresh ``[PRB:...:1]`` response for each probe.  It
    never mutates a plant or applies a work offset; a result exists only after
    all four validated contacts are complete.
    """

    _REPORT = re.compile(r"^\[PRB:([^,]+),([^,]+),([^:]+):([01])\]$")

    def __init__(self, *, tolerance: float = 0.1, slow_feed: float = 25.0) -> None:
        if not math.isfinite(tolerance) or tolerance <= 0 or not math.isfinite(slow_feed) or slow_feed <= 0:
            raise ValueError("Trace tolerance/feed must be finite and positive")
        self.tolerance = float(tolerance)
        self.slow_feed = float(slow_feed)
        self.state = BoundaryTraceState.IDLE
        self.failure_code = BoundaryTraceFailure.NONE
        self.failure_reason = ""
        self.boundary: ProbeBoundary | None = None
        self.seed: tuple[float, float, float] | None = None
        self.commands: tuple[str, ...] = ()
        self.contacts: list[tuple[float, float, float]] = []
        self.result: BoundaryTraceResult | None = None
        self._command_index = 0
        self._awaiting_ack = False
        self._awaiting_report = False

    def start(self, *, boundary: ProbeBoundary, seed: tuple[float, float, float],
              envelope: tuple[float, float, float], reference_trusted: bool,
              controller_idle: bool, spindle_rpm: float, probe_input_open: bool,
              collision_clear: bool = True, limits_clear: bool = True,
              estop_clear: bool = True, supervisor_healthy: bool = True,
              status_fresh: bool = True) -> bool:
        try:
            boundary.validate()
            values = tuple(float(value) for value in (*seed, *envelope))
            if len(values) != 6 or not all(math.isfinite(value) for value in values):
                raise ValueError("trace pose/envelope must be finite")
            if any(value < 0 or value > maximum for value, maximum in zip(seed, envelope)):
                return self.fail("seed is outside the machine envelope", BoundaryTraceFailure.ENVELOPE)
        except (TypeError, ValueError) as exc:
            return self.fail(str(exc), BoundaryTraceFailure.INVALID_BOUNDARY)
        if not (reference_trusted and controller_idle and spindle_rpm == 0 and probe_input_open
                and collision_clear and limits_clear and estop_clear and supervisor_healthy and status_fresh):
            return self.fail("Idle, spindle-off, trusted reference, open probe, fresh status, and clear safety are required",
                             BoundaryTraceFailure.GUARD)
        if not boundary.contains((seed[0], seed[1])):
            return self.fail("trace seed must be strictly inside the boundary", BoundaryTraceFailure.SEED_OUTSIDE)
        min_x, min_y, max_x, max_y = boundary.bounds
        distances = (envelope[0] - seed[0], seed[1], envelope[1] - seed[1], seed[1])
        if any(distance <= 0 for distance in distances):
            return self.fail("seed leaves no bounded outward probe distance", BoundaryTraceFailure.ENVELOPE)
        directions = (f"X{distances[0]:.3f}", f"Y{distances[2]:.3f}",
                      f"X-{distances[1]:.3f}", f"Y-{distances[3]:.3f}")
        self.boundary = boundary
        self.seed = tuple(float(value) for value in seed)
        self.contacts.clear()
        self.result = None
        self.failure_code = BoundaryTraceFailure.NONE
        self.failure_reason = ""
        self.commands = tuple(
            command
            for direction in directions
            for command in (
                f"G90 G21 G0 X{seed[0]:.3f} Y{seed[1]:.3f} Z{seed[2]:.3f}",
                "G91",
                f"G38.2 {direction} F{self.slow_feed:.3f}",
            )
        )
        self._command_index = 0
        self._awaiting_ack = False
        self._awaiting_report = False
        self.state = BoundaryTraceState.SEARCHING
        return True

    def next_command(self) -> str | None:
        if self.state is not BoundaryTraceState.SEARCHING or self._awaiting_ack or self._awaiting_report:
            return None
        if self._command_index >= len(self.commands):
            return None
        command = self.commands[self._command_index]
        self._awaiting_ack = True
        self._awaiting_report = command.upper().startswith("G38.2")
        return command

    def handle_response(self, line: str) -> bool:
        if self.state is not BoundaryTraceState.SEARCHING:
            return self.fail("probe response arrived outside an active trace", BoundaryTraceFailure.STALE_REPORT)
        normalized = str(line).strip()
        if normalized == "ok":
            if not self._awaiting_ack:
                return self.fail("unexpected acknowledgement", BoundaryTraceFailure.STALE_REPORT)
            self._awaiting_ack = False
            if not self._awaiting_report:
                self._command_index += 1
            return True
        match = self._REPORT.fullmatch(normalized)
        if match is None:
            return self.fail("malformed or unexpected probe report", BoundaryTraceFailure.MALFORMED_REPORT)
        if not self._awaiting_report or self._awaiting_ack:
            return self.fail("stale or uncorrelated probe report", BoundaryTraceFailure.STALE_REPORT)
        try:
            point = tuple(float(match.group(index)) for index in (1, 2, 3))
        except ValueError:
            return self.fail("probe report coordinates are malformed", BoundaryTraceFailure.MALFORMED_REPORT)
        if match.group(4) != "1":
            return self.fail("probe reported no contact", BoundaryTraceFailure.NO_CONTACT)
        if self.boundary is None or self.boundary.distance_to_boundary(point[:2]) > self.tolerance:
            return self.fail("probe contact contradicts the commissioned boundary", BoundaryTraceFailure.CONTRADICTORY)
        if any(math.dist(point, previous) <= self.tolerance for previous in self.contacts):
            return self.fail("duplicate/contradictory probe contact", BoundaryTraceFailure.CONTRADICTORY)
        if not self._direction_is_valid(point, len(self.contacts)):
            return self.fail("probe contact is out of deterministic outward order",
                             BoundaryTraceFailure.CONTRADICTORY)
        self.contacts.append(point)
        self._awaiting_report = False
        self._command_index += 1
        if len(self.contacts) == 4:
            if not self._validate_contacts():
                return self.fail("probe contacts do not form the ordered closed trace",
                                 BoundaryTraceFailure.CONTRADICTORY)
            self.result = BoundaryTraceResult(tuple(self.contacts))
            self.state = BoundaryTraceState.COMPLETE
        return True

    def _validate_contacts(self) -> bool:
        if self.boundary is None or self.seed is None or len(self.contacts) != 4:
            return False
        if any(not all(math.isfinite(value) for value in point) for point in self.contacts):
            return False
        if any(math.dist(first[:2], second[:2]) <= self.tolerance
               for index, first in enumerate(self.contacts)
               for second in self.contacts[index + 1:]):
            return False
        for index, point in enumerate(self.contacts):
            if not self._direction_is_valid(point, index):
                return False
        area = abs(sum(first[0] * second[1] - second[0] * first[1]
                       for first, second in zip(self.contacts, self.contacts[1:] + self.contacts[:1]))) / 2.0
        return area > self.tolerance * self.tolerance

    def _direction_is_valid(self, point: tuple[float, float, float], index: int) -> bool:
        if self.seed is None or index >= 4:
            return False
        direction = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[index]
        delta = (point[0] - self.seed[0], point[1] - self.seed[1])
        forward = delta[0] * direction[0] + delta[1] * direction[1]
        lateral = abs(delta[0] * direction[1] - delta[1] * direction[0])
        return forward > self.tolerance and lateral <= self.tolerance

    def fail(self, reason: str, code: BoundaryTraceFailure) -> bool:
        self.state = BoundaryTraceState.FAILED
        self.failure_reason = str(reason)
        self.failure_code = code
        self.result = None
        self._awaiting_ack = False
        self._awaiting_report = False
        return False

    def abort_for_safety(self, reason: str = "safety state changed") -> bool:
        return self.fail(reason, BoundaryTraceFailure.GUARD)


@dataclass(frozen=True)
class CalibrationPlateDefinition:
    schema_version: int = 1
    diameter: float = 20.0
    thickness: float = 1.5
    tool_radius: float = 1.5
    safe_z: float = 30.0
    search_margin: float = 4.0
    fast_feed: float = 100.0
    slow_feed: float = 25.0
    repeatability_tolerance: float = 0.1
    max_search_xy: float = 20.0
    max_search_z: float = 10.0
    input_pin: str = "P"
    active_low: bool = False
    circle_center_x: float = 20.0
    circle_center_y: float = 20.0
    # The bundled twin fixture has a deterministic conductive Z surface.  A
    # missing value derives the reachable surface from the bounded plan.
    probe_surface_z: float | None = None

    def validate(self) -> None:
        values = (self.diameter, self.thickness, self.tool_radius, self.safe_z, self.search_margin,
                  self.fast_feed, self.slow_feed, self.repeatability_tolerance, self.max_search_xy, self.max_search_z,
                  self.circle_center_x, self.circle_center_y)
        _finite(values, "calibration plate values")
        if self.probe_surface_z is not None and not math.isfinite(float(self.probe_surface_z)):
            raise ValueError("probe_surface_z must be finite when provided")
        if min(self.diameter, self.thickness, self.fast_feed, self.slow_feed, self.repeatability_tolerance,
               self.max_search_xy, self.max_search_z) <= 0:
            raise ValueError("calibration plate dimensions/feeds must be positive")
        if self.tool_radius < 0 or self.search_margin >= self.diameter / 2:
            raise ValueError("invalid tool radius/search margin")
        if not 0 <= self.effective_probe_surface_z <= self.safe_z:
            raise ValueError("probe_surface_z must be within the safe-Z envelope")

    @property
    def effective_probe_surface_z(self) -> float:
        """Return the deterministic conductive surface used by the twin."""
        self.validate_base()
        return (self.safe_z - self.max_search_z
                if self.probe_surface_z is None else float(self.probe_surface_z))

    def validate_base(self) -> None:
        """Validate dimensions without recursively evaluating the surface."""
        values = (self.diameter, self.thickness, self.tool_radius, self.safe_z, self.search_margin,
                  self.fast_feed, self.slow_feed, self.repeatability_tolerance, self.max_search_xy, self.max_search_z,
                  self.circle_center_x, self.circle_center_y)
        _finite(values, "calibration plate values")
        if self.probe_surface_z is not None and not math.isfinite(float(self.probe_surface_z)):
            raise ValueError("probe_surface_z must be finite when provided")
        if min(self.diameter, self.thickness, self.fast_feed, self.slow_feed, self.repeatability_tolerance,
               self.max_search_xy, self.max_search_z) <= 0:
            raise ValueError("calibration plate dimensions/feeds must be positive")
        if self.tool_radius < 0 or self.search_margin >= self.diameter / 2:
            raise ValueError("invalid tool radius/search margin")

    @property
    def radius(self) -> float:
        self.validate()
        return self.diameter / 2

    def fingerprint(self) -> str:
        self.validate()
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PlateContact:
    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True)
class CalibrationCommissioningRecord:
    """Machine-scoped proof that the plate geometry and conductive input were tested."""

    schema_version: int = 1
    plate_fingerprint: str = ""
    input_tested: bool = False
    geometry_tested: bool = False
    machine_id: str = ""

    def valid_for(self, definition: CalibrationPlateDefinition, *, machine_id: str | None = None) -> bool:
        definition.validate()
        encoded = json.dumps(asdict(definition), sort_keys=True, separators=(",", ":")).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        machine_matches = machine_id is None or self.machine_id == machine_id
        return (self.schema_version == 1 and machine_matches and self.plate_fingerprint == fingerprint
                and self.input_tested and self.geometry_tested)


@dataclass(frozen=True)
class CalibrationResult:
    center: tuple[float, float]
    residual: float
    contacts: tuple[PlateContact, ...]
    tool_radius_compensation: float
    fitted_radius: float = 0.0
    compensated_radius: float = 0.0
    work_zero: tuple[float, float, float] | None = None


def fit_plate_circle(contacts: Iterable[PlateContact], *, tool_radius: float = 0.0,
                     tolerance: float = 0.1) -> CalibrationResult:
    """Fit a circle by a deterministic linear least-squares normal equation."""
    points = tuple(contacts)
    if len(points) < 4:
        raise ValueError("at least four orthogonal contact points are required")
    _finite((value for point in points for value in (point.x, point.y, point.z)), "contact points")
    # x²+y² + A*x + B*y + C = 0; solve the 3x3 normal equations by elimination.
    rows = [(p.x, p.y, 1.0, -(p.x*p.x + p.y*p.y)) for p in points]
    ata = [[sum(row[i] * row[j] for row in rows) for j in range(3)] for i in range(3)]
    aty = [sum(row[i] * row[3] for row in rows) for i in range(3)]
    matrix = [ata[i] + [aty[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(matrix[row][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            raise ValueError("contact points do not localize a circle")
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        scale = matrix[col][col]
        matrix[col] = [v / scale for v in matrix[col]]
        for row in range(3):
            if row == col:
                continue
            scale = matrix[row][col]
            matrix[row] = [a - scale*b for a, b in zip(matrix[row], matrix[col])]
    a, b, c = (matrix[i][3] for i in range(3))
    center = (-a / 2, -b / 2)
    radius = math.sqrt(max(0.0, center[0] * center[0] + center[1] * center[1] - c))
    residual = max(abs(math.dist((point.x, point.y), center) - radius) for point in points)
    if residual > tolerance:
        raise ValueError(f"circle repeatability residual {residual:.4f} exceeds {tolerance:.4f} mm")
    return CalibrationResult(center, residual, points, float(tool_radius), radius,
                             max(0.0, radius - float(tool_radius)))


class AutoXYZCalibrationWorkflow:
    """Explicit, fail-closed public workflow for a conductive calibration plate."""

    def __init__(self, definition: CalibrationPlateDefinition | None = None) -> None:
        self.definition = definition or CalibrationPlateDefinition()
        self.definition.validate()
        self.state = CalibrationState.IDLE
        self.failure_reason = ""
        self.failure_code = CalibrationFailure.NONE
        self.plate_center: tuple[float, float] = (self.definition.circle_center_x, self.definition.circle_center_y)
        self.seed: tuple[float, float, float] | None = None
        self.contacts: list[PlateContact] = []
        self.result: CalibrationResult | None = None
        self.commands: list[str] = []

    def start(self, *, seed: tuple[float, float, float], reference_trusted: bool,
              controller_idle: bool, spindle_rpm: float, envelope: tuple[float, float, float],
              commissioned: bool = False,
              commissioning_record: CalibrationCommissioningRecord | None = None) -> bool:
        # Kept as a keyword-only compatibility gate: callers must explicitly
        # opt into a current, machine-scoped plate/input commissioning record.
        # (The optional parameter is read below through the public wrapper.)
        commissioned = commissioned or bool(commissioning_record and commissioning_record.valid_for(self.definition))
        return self._start(seed=seed, reference_trusted=reference_trusted,
                           controller_idle=controller_idle, spindle_rpm=spindle_rpm,
                           envelope=envelope, commissioned=commissioned)

    def _start(self, *, seed: tuple[float, float, float], reference_trusted: bool,
               controller_idle: bool, spindle_rpm: float, envelope: tuple[float, float, float],
               commissioned: bool) -> bool:
        if not commissioned:
            return self.fail("a current machine-scoped plate/input commissioning record is required",
                             CalibrationFailure.UNCOMMISSIONED)
        if not reference_trusted or not controller_idle or spindle_rpm > 0:
            return self.fail("trusted reference, Idle controller, and spindle-off are required")
        _finite((*seed, *envelope), "calibration pose")
        if any(value < 0 or value > maximum for value, maximum in zip(seed, envelope)):
            return self.fail("calibration seed is outside the machine envelope", CalibrationFailure.ENVELOPE)
        self.plate_center = (self.definition.circle_center_x, self.definition.circle_center_y)
        if math.dist(seed[:2], self.plate_center) > self.definition.radius - self.definition.search_margin:
            return self.fail("calibration seed must be inside the commissioned corner circle",
                             CalibrationFailure.SEED_OUTSIDE_CIRCLE)
        self.seed = seed
        self.contacts.clear()
        self.result = None
        self.commands = [f"G90 G21 G0 Z{self.definition.safe_z:.3f}"]
        cx, cy = self.plate_center
        r = self.definition.radius - self.definition.search_margin
        self.commands.extend((f"G0 X{cx-r:.3f} Y{cy:.3f} Z{self.definition.safe_z:.3f}",
                              "G91", f"G38.2 X{self.definition.max_search_xy:.3f} F{self.definition.slow_feed:.3f}",
                              f"G0 G90 X{cx:.3f} Y{cy+r:.3f} Z{self.definition.safe_z:.3f}",
                              "G91", f"G38.2 Y-{self.definition.max_search_xy:.3f} F{self.definition.slow_feed:.3f}",
                              f"G0 G90 X{cx+r:.3f} Y{cy:.3f} Z{self.definition.safe_z:.3f}",
                              "G91", f"G38.2 X-{self.definition.max_search_xy:.3f} F{self.definition.slow_feed:.3f}",
                              f"G0 G90 X{cx:.3f} Y{cy-r:.3f} Z{self.definition.safe_z:.3f}",
                              "G91", f"G38.2 Y{self.definition.max_search_xy:.3f} F{self.definition.slow_feed:.3f}"))
        self.state = CalibrationState.SEARCHING
        return True

    def record_contact(self, point: PlateContact) -> bool:
        if self.state is not CalibrationState.SEARCHING:
            return self.fail("contact is not expected in the current state")
        self.contacts.append(point)
        if len(self.contacts) >= 4:
            try:
                self.result = fit_plate_circle(self.contacts, tool_radius=self.definition.tool_radius,
                                               tolerance=self.definition.repeatability_tolerance)
            except ValueError as exc:
                return self.fail(str(exc), CalibrationFailure.RESIDUAL)
            self.state = CalibrationState.FITTED
            cx, cy = self.result.center
            outside = max(self.definition.radius + self.definition.search_margin,
                          self.definition.radius + self.definition.tool_radius)
            self.commands.extend(("G0 G90 Z{:.3f}".format(self.definition.safe_z),
                                  f"G0 G90 X{cx+outside:.3f} Y{cy:.3f} Z{self.definition.safe_z:.3f}"))
        return True

    def complete_z_touch(self, z: float, *, wco_fresh: bool, envelope: tuple[float, float, float]) -> bool:
        if self.state not in {CalibrationState.FITTED, CalibrationState.Z_TOUCH} or self.result is None:
            return self.fail("a valid circle fit is required before Z touch")
        if not wco_fresh or not math.isfinite(z) or z < 0 or z > envelope[2]:
            return self.fail("fresh WCO and in-envelope Z touch are required", CalibrationFailure.STALE_WCO if not wco_fresh else CalibrationFailure.ENVELOPE)
        if self.state is CalibrationState.FITTED:
            self.state = CalibrationState.Z_TOUCH
            self.commands.extend(("G91", f"G38.2 Z-{self.definition.max_search_z:.3f} F{self.definition.slow_feed:.3f}",
                                  "G10 L20 P1 X0 Y0 Z0", f"G0 G91 Z{self.definition.safe_z:.3f}"))
        self.result = CalibrationResult(self.result.center, self.result.residual, self.result.contacts,
                                        self.result.tool_radius_compensation, self.result.fitted_radius,
                                        self.result.compensated_radius,
                                        (self.result.center[0], self.result.center[1], z))
        self.state = CalibrationState.COMPLETE
        return True

    def begin_z_touch(self) -> bool:
        """Queue the ordinary-protocol Z-touch tail after XY contacts."""
        if self.state is not CalibrationState.FITTED or self.result is None:
            return self.fail("a valid circle fit is required before Z touch")
        self.state = CalibrationState.Z_TOUCH
        self.commands.extend(("G91", f"G38.2 Z-{self.definition.max_search_z:.3f} F{self.definition.slow_feed:.3f}",
                              "G10 L20 P1 X0 Y0 Z0", f"G0 G91 Z{self.definition.safe_z:.3f}"))
        return True

    def no_contact(self) -> bool:
        return self.fail("no conductive contact was observed", CalibrationFailure.NO_CONTACT)

    def interlock(self, reason: str = "collision/interlock during calibration") -> bool:
        return self.fail(reason, CalibrationFailure.COLLISION)

    def estop(self) -> bool:
        return self.fail("E-stop latched during calibration", CalibrationFailure.ESTOP)

    def fail(self, reason: str, code: CalibrationFailure = CalibrationFailure.NONE) -> bool:
        self.state = CalibrationState.FAILED
        self.failure_reason = str(reason)
        self.failure_code = code
        self.result = None
        return False
