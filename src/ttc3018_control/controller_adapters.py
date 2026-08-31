"""Controller capability adapters and GRBL command semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import FrozenSet

from .grbl import Position, clear_tool_length_offset, make_probe, make_probe_retract, make_setting, make_tool_length_offset, make_work_offset
from .machine_config import ControllerKind


class Capability(StrEnum):
    MOTION = "motion"
    HOMING = "homing"
    PROBING = "probing"
    WORK_OFFSETS = "work_offsets"
    TOOL_LENGTH = "tool_length"
    SETTINGS = "settings"


@dataclass(frozen=True)
class CapabilitySet:
    supported: FrozenSet[Capability]

    def supports(self, capability: Capability) -> bool:
        return capability in self.supported


@dataclass(frozen=True)
class ProbeReport:
    position: Position
    success: bool


class UnsupportedCapability(RuntimeError):
    pass


class ControllerAdapter:
    kind: ControllerKind
    capabilities: CapabilitySet

    def require(self, capability: Capability) -> None:
        if not self.capabilities.supports(capability):
            raise UnsupportedCapability(f"{self.kind.value} does not support {capability.value}")

    def home_command(self) -> bytes:
        self.require(Capability.HOMING)
        return b"$H\n"

    def probe_command(self, axis: str, distance: float, feed: float) -> bytes:
        self.require(Capability.PROBING)
        return make_probe(axis, distance, feed)

    def retract_command(self, axis: str, distance: float, feed: float) -> bytes:
        self.require(Capability.PROBING)
        return make_probe_retract(axis, distance, feed)

    def work_offset_command(self, slot: int, position: Position) -> bytes:
        self.require(Capability.WORK_OFFSETS)
        return make_work_offset(slot, position)

    def tool_offset_command(self, z_offset: float) -> bytes:
        self.require(Capability.TOOL_LENGTH)
        return make_tool_length_offset(z_offset)

    def clear_tool_offset_command(self) -> bytes:
        self.require(Capability.TOOL_LENGTH)
        return clear_tool_length_offset()

    def setting_command(self, number: int, value: float) -> bytes:
        self.require(Capability.SETTINGS)
        return make_setting(number, value)


class Grbl11Adapter(ControllerAdapter):
    kind = ControllerKind.GRBL11
    capabilities = CapabilitySet(frozenset(Capability))

    @staticmethod
    def tool_length_delta(reference_trigger_z: float, measured_trigger_z: float) -> float:
        """Return the dynamic Z TLO needed to preserve the reference tip.

        The subtraction is intentionally isolated and table-tested.  GRBL's
        G43.1 value is session state, so callers must confirm [TLO] before
        treating it as active.
        """
        result = reference_trigger_z - measured_trigger_z
        if not math.isfinite(result):
            raise ValueError("Tool length measurement must be finite")
        return result


class GenericGrblAdapter(ControllerAdapter):
    kind = ControllerKind.GENERIC_GRBL
    capabilities = CapabilitySet(frozenset({Capability.MOTION}))

