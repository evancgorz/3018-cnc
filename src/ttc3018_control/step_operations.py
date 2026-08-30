"""Normalized operation planning for the bounded STEP 2.5D workflow."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .step_geometry import StepPlanarModel


@dataclass(frozen=True)
class StepOperation:
    operation_id: str
    kind: str
    target_depth: float
    feature_indices: tuple[int, ...] = ()
    depends_on: tuple[str, ...] = ()


def build_step_operation_plan(
    model: StepPlanarModel,
    mode: str,
    *,
    depth: float,
    stock_thickness: float,
    breakthrough: float,
) -> tuple[StepOperation, ...]:
    """Describe the actual operation groups emitted by the STEP generator."""
    if mode == "Profile cutout":
        inner = tuple(index for index in range(len(model.loops)) if index != _outer_index(model))
        operations = []
        if inner:
            operations.append(
                StepOperation("internal-through", "Internal through-cutouts", -(stock_thickness + breakthrough), inner)
            )
        operations.append(
            StepOperation(
                "outer-profile",
                "Outer profile",
                -(stock_thickness + breakthrough),
                depends_on=("internal-through",) if inner else (),
            )
        )
        return tuple(operations)
    if mode == "Detected feature":
        grouped: dict[float, list[int]] = {}
        for index, feature in enumerate(model.features):
            grouped.setdefault(round(feature.depth, 7), []).append(index)
        return tuple(
            StepOperation(
                f"feature-depth-{index}",
                "Detected feature group",
                -feature_depth,
                tuple(feature_indices),
            )
            for index, (feature_depth, feature_indices) in enumerate(sorted(grouped.items(), reverse=True))
        )
    if mode == "Planar surface":
        return (StepOperation("planar-surface", "Planar surface raster", depth),)
    return (StepOperation(mode.lower().replace(" ", "-"), mode, depth),)


def validate_operation_plan(operations: tuple[StepOperation, ...]) -> None:
    """Fail closed when operation metadata cannot represent a valid DAG."""
    ids = [operation.operation_id for operation in operations]
    if len(ids) != len(set(ids)):
        raise ValueError("STEP operation plan contains duplicate operation IDs")
    if any(not math.isfinite(operation.target_depth) for operation in operations):
        raise ValueError("STEP operation plan contains a non-finite target depth")
    known = set(ids)
    for operation in operations:
        missing = set(operation.depends_on) - known
        if missing:
            raise ValueError(
                f"STEP operation {operation.operation_id} depends on unknown operation {sorted(missing)[0]}"
            )
        if operation.operation_id in operation.depends_on:
            raise ValueError(f"STEP operation {operation.operation_id} depends on itself")
    pending = {operation.operation_id: set(operation.depends_on) for operation in operations}
    resolved: set[str] = set()
    while pending:
        ready = sorted(operation_id for operation_id, dependencies in pending.items() if dependencies <= resolved)
        if not ready:
            raise ValueError("STEP operation plan contains a dependency cycle")
        for operation_id in ready:
            resolved.add(operation_id)
            pending.pop(operation_id)


def _outer_index(model: StepPlanarModel) -> int:
    return max(range(len(model.loops)), key=lambda index: model.loops[index].area)
