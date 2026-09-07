"""Independent-friendly collision classifications and continuous checks."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .geometry import AABB, CoordinateFrame, MachineGeometryProfile, swept_bounds
from .models import Hazard, HazardKind, PlantSnapshot, SimulationProfile
from .stock import StockModel


@dataclass(frozen=True)
class Fixture:
    name: str
    bounds: AABB
    frame: str = "machine"

    def validate(self) -> None:
        if not self.name or self.frame not in {"machine", "work"}:
            raise ValueError("Fixture requires a name and machine/work frame")
        self.bounds.validate()

    def machine_bounds(self, frame: CoordinateFrame) -> AABB:
        self.validate()
        return self.bounds if self.frame == "machine" else frame.work_bounds_to_machine(self.bounds)


class CollisionWorld:
    def __init__(self, profile: SimulationProfile | None = None, geometry: MachineGeometryProfile | None = None) -> None:
        self.profile = profile or SimulationProfile.default_3018()
        self.geometry = geometry or MachineGeometryProfile.default_3018(self.profile)
        self.fixtures: list[Fixture] = []
        # Keep the nominal Z=0 reference plane clear; penetration below it is
        # what constitutes a bed collision in the virtual envelope.
        self.bed = AABB(-self.geometry.base_margin, -self.geometry.base_margin, -8.0,
                        self.profile.travel_x + self.geometry.base_margin,
                        self.profile.travel_y + self.geometry.base_margin, -0.1)

    def add_fixture(self, fixture: Fixture) -> None:
        fixture.validate()
        self.fixtures.append(fixture)

    def check_transition(self, previous: PlantSnapshot, current: PlantSnapshot, *, rapid: bool,
                         spindle_on: bool, stock: StockModel | None = None,
                         target_cutting: bool = True,
                         stock_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[Hazard, ...]:
        hazards: list[Hazard] = []
        frame = CoordinateFrame(tuple(stock_offset))
        x, y, z = current.machine_position
        limits = (self.profile.travel_x, self.profile.travel_y, self.profile.travel_z)
        if any(value < -0.001 or value > limit + 0.001 for value, limit in zip(current.machine_position, limits)):
            hazards.append(self._hazard(HazardKind.TRAVEL_LIMIT, "Axis exceeded virtual travel", current))
        tool = swept_bounds(previous, current, "cutter", self.geometry, self.profile)
        holder = swept_bounds(previous, current, "tool-holder", self.geometry, self.profile)
        # The carriage/gantry overlap is an allowed joint contact.  The
        # cutter/holder envelope, however, must not sweep into either fixed
        # upright at the ends of X travel.  Check the swept envelope rather
        # than only the endpoint so a fast lateral move cannot tunnel through
        # the frame.
        for body in self.geometry.bodies(current, self.profile):
            if body.name not in {"left-upright", "right-upright"}:
                continue
            if holder.penetrates(body.bounds):
                hazards.append(self._hazard(HazardKind.MACHINE_COLLISION,
                                            "Tool holder intersects fixed frame upright", current,
                                            "tool-holder", body.name))
        if tool.penetrates(self.bed):
            hazards.append(self._hazard(HazardKind.TOOL_BED, "Cutter intersects bed/spoilboard", current, "cutter", "bed"))
        for fixture in self.fixtures:
            fixture_bounds = fixture.machine_bounds(frame)
            if tool.penetrates(fixture_bounds):
                hazards.append(self._hazard(HazardKind.TOOL_FIXTURE, "Cutter intersects fixture", current, "cutter", fixture.name))
            if holder.penetrates(fixture_bounds):
                hazards.append(self._hazard(HazardKind.HOLDER_FIXTURE, "Holder intersects fixture", current, "tool-holder", fixture.name))
        if stock is not None:
            # The application uses GRBL's positive-up Z convention: stock top
            # is work-Z 0 and material extends down by its thickness.  Treat
            # mere contact with the top plane as safe; only penetration is a
            # stock entry.  This avoids a false alarm at the reference plane.
            stock_box = frame.work_bounds_to_machine(AABB(
                stock.workpiece.origin_x,
                stock.workpiece.origin_y,
                stock.workpiece.origin_z - stock.workpiece.stock_thickness,
                stock.workpiece.origin_x + stock.workpiece.stock_width,
                stock.workpiece.origin_y + stock.workpiece.stock_height,
                stock.workpiece.origin_z))
            penetrates_stock = (tool.max_x > stock_box.min_x and tool.min_x < stock_box.max_x
                                and tool.max_y > stock_box.min_y and tool.min_y < stock_box.max_y
                                and tool.min_z < stock_box.max_z and tool.max_z > stock_box.min_z)
            previous_tool = swept_bounds(previous, previous, "cutter", self.geometry, self.profile)
            downward = current.machine_position[2] < previous.machine_position[2] - 1e-9
            horizontal_or_down = current.machine_position[2] <= previous.machine_position[2] + 1e-9
            previous_penetrates = (previous_tool.max_x > stock_box.min_x and previous_tool.min_x < stock_box.max_x
                                   and previous_tool.max_y > stock_box.min_y and previous_tool.min_y < stock_box.max_y
                                   and previous_tool.min_z < stock_box.max_z and previous_tool.max_z > stock_box.min_z)
            if penetrates_stock and (downward or (rapid and horizontal_or_down)):
                if rapid:
                    hazards.append(self._hazard(HazardKind.RAPID_STOCK, "Rapid move enters stock", current, "cutter", "stock"))
                elif not spindle_on and (downward or previous_penetrates):
                    hazards.append(self._hazard(HazardKind.SPINDLE_OFF_ENTRY, "Cutter enters stock with spindle off", current, "cutter", "stock"))
                elif not target_cutting:
                    hazards.append(self._hazard(HazardKind.RETAINED_GOUGE, "Cutter enters retained material", current, "cutter", "stock"))
                if tool.min_z < stock_box.min_z:
                    hazards.append(self._hazard(HazardKind.EXCESSIVE_DEPTH, "Cutter exceeds stock bottom", current, "cutter", "stock"))
            # The holder's physical envelope is unsafe on stock contact even
            # when the cutter's top-plane entry rule treats mere contact as
            # safe; retain this conservative holder/stock guard.
            if holder.intersects(stock_box):
                hazards.append(self._hazard(HazardKind.HOLDER_STOCK, "Tool holder intersects stock", current, "tool-holder", "stock"))
        return tuple(hazards)

    def _hazard(self, kind: HazardKind, message: str, snapshot: PlantSnapshot,
                body_a: str = "", body_b: str = "") -> Hazard:
        return Hazard(kind, message, snapshot.time_ns, snapshot.machine_position, body_a, body_b)


def compare_snapshots(expected: PlantSnapshot, actual: PlantSnapshot, tolerance: float = 0.001) -> Hazard | None:
    if math.dist(expected.machine_position, actual.machine_position) > tolerance:
        return Hazard(HazardKind.DIVERGENCE, "Executed pose diverged from commanded pose", actual.time_ns,
                      actual.machine_position, source="supervisor")
    return None
