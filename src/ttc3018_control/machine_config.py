"""Versioned, capability-oriented machine definitions.

The original application only needed a travel envelope.  This module keeps
that small geometry model compatible while giving future machines a place to
declare optional hardware without pretending that every controller supports
it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
import math
from uuid import uuid5, NAMESPACE_URL

from .machine_state import MachineProfile


class ControllerKind(StrEnum):
    GRBL11 = "grbl_1_1"
    GENERIC_GRBL = "generic_grbl"


class AxisEnd(StrEnum):
    MIN = "min"
    MAX = "max"


class SwitchMode(StrEnum):
    NONE = "none"
    SINGLE = "single"


class ProbeKind(StrEnum):
    MOVABLE_Z_PLATE = "movable_z_plate"
    FIXED_TOOL_SETTER = "fixed_tool_setter"
    MOVABLE_XYZ = "movable_xyz"
    FIXED_XYZ = "fixed_xyz"


@dataclass(frozen=True)
class AxisDefinition:
    positive_direction: int = 1
    switch_mode: SwitchMode = SwitchMode.NONE
    switch_end: AxisEnd = AxisEnd.MAX
    input_pin: str | None = None
    active_low: bool = False
    hard_limit: bool = False

    def validate(self, axis: str) -> None:
        if self.positive_direction not in (-1, 1):
            raise ValueError(f"{axis} positive direction must be 1 or -1")
        if self.switch_mode is SwitchMode.NONE and (self.input_pin or self.hard_limit):
            raise ValueError(f"{axis} cannot configure a switch pin or hard limit when switches are off")
        if self.switch_mode is SwitchMode.SINGLE and not self.input_pin:
            raise ValueError(f"{axis} single-switch homing requires an input pin")


@dataclass(frozen=True)
class ProbeDefinition:
    kind: ProbeKind
    enabled: bool = False
    input_pin: str = "P"
    tool_radius: float = 0.0
    plate_thickness: float = 0.0
    fast_feed: float = 100.0
    slow_feed: float = 25.0
    max_search: float = 5.0
    retract: float = 2.0

    def validate(self) -> None:
        values = (self.tool_radius, self.plate_thickness, self.fast_feed, self.slow_feed, self.max_search, self.retract)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{self.kind.value} probe values must be finite")
        if self.tool_radius < 0 or self.plate_thickness < 0:
            raise ValueError(f"{self.kind.value} probe geometry cannot be negative")
        if self.enabled and (self.fast_feed <= 0 or self.slow_feed <= 0 or self.max_search <= 0 or self.retract <= 0):
            raise ValueError(f"{self.kind.value} enabled probe requires positive motion settings")


@dataclass(frozen=True)
class SpindleDefinition:
    present: bool = True
    supports_speed_command: bool = True
    max_rpm: float = 12000.0


@dataclass(frozen=True)
class StepperDefinition:
    present: bool = True
    enable_control: bool = False
    disable_when_idle: bool = False


@dataclass(frozen=True)
class MachineDefinition:
    schema_version: int = 1
    machine_id: str = ""
    name: str = "Two Trees TTC 3018"
    controller: ControllerKind = ControllerKind.GRBL11
    travel_x: float = 290.0
    travel_y: float = 170.0
    travel_z: float = 40.0
    safe_z: float = 30.0
    axes: dict[str, AxisDefinition] = field(default_factory=lambda: {axis: AxisDefinition() for axis in "XYZ"})
    probes: tuple[ProbeDefinition, ...] = ()
    spindle: SpindleDefinition = field(default_factory=SpindleDefinition)
    steppers: StepperDefinition = field(default_factory=StepperDefinition)
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def legacy_3018(cls, *, machine_id: str | None = None, profile: MachineProfile | None = None) -> "MachineDefinition":
        profile = profile or MachineProfile(travel_x=290, travel_y=170, travel_z=40, safe_z=30)
        stable_id = machine_id or str(uuid5(NAMESPACE_URL, "ttc3018-control/legacy/Two Trees TTC 3018"))
        return cls(machine_id=stable_id, name=profile.name, travel_x=profile.travel_x, travel_y=profile.travel_y,
                   travel_z=profile.travel_z, safe_z=profile.safe_z)

    def to_profile(self) -> MachineProfile:
        return MachineProfile(self.name, self.travel_x, self.travel_y, self.travel_z, self.safe_z)

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported machine schema version: {self.schema_version}")
        if not self.machine_id.strip() or not self.name.strip():
            raise ValueError("Machine ID and name cannot be empty")
        profile = self.to_profile()
        profile.validate()
        if set(self.axes) != set("XYZ"):
            raise ValueError("Machine definition must declare exactly X, Y, and Z axes")
        for axis in "XYZ":
            self.axes[axis].validate(axis)
        for probe in self.probes:
            probe.validate()
        if not math.isfinite(self.spindle.max_rpm) or self.spindle.max_rpm <= 0:
            raise ValueError("Spindle max RPM must be finite and greater than zero")

    def to_dict(self) -> dict:
        self.validate()
        data = asdict(self)
        data["controller"] = self.controller.value
        data["axes"] = {
            axis: {**values, "switch_mode": values["switch_mode"].value, "switch_end": values["switch_end"].value}
            for axis, values in data["axes"].items()
        }
        data["probes"] = [{**probe, "kind": probe["kind"].value} for probe in data["probes"]]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MachineDefinition":
        if not isinstance(data, dict):
            raise ValueError("Machine definition must be an object")
        axes = {axis: AxisDefinition(**{**values, "switch_mode": SwitchMode(values.get("switch_mode", "none")),
                                        "switch_end": AxisEnd(values.get("switch_end", "max"))})
                for axis, values in data.get("axes", {}).items()}
        probes = tuple(ProbeDefinition(**{**values, "kind": ProbeKind(values["kind"])}) for values in data.get("probes", []))
        definition = cls(schema_version=int(data.get("schema_version", 1)), machine_id=str(data.get("machine_id", "")),
                         name=str(data.get("name", "")), controller=ControllerKind(data.get("controller", ControllerKind.GRBL11)),
                         travel_x=float(data.get("travel_x", 0)), travel_y=float(data.get("travel_y", 0)),
                         travel_z=float(data.get("travel_z", 0)), safe_z=float(data.get("safe_z", 0)), axes=axes,
                         probes=probes, spindle=SpindleDefinition(**data.get("spindle", {})),
                         steppers=StepperDefinition(**data.get("steppers", {})), metadata=dict(data.get("metadata", {})))
        definition.validate()
        return definition

    def fingerprint(self, *areas: str) -> str:
        """Hash safety-relevant subtrees; empty areas means the full definition."""
        data = self.to_dict()
        if areas:
            data = {area: data.get(area) for area in areas}
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

