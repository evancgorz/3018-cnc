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
    strategy: str = ""
    feature_kinds: tuple[str, ...] = ()


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
        # Every root loop is a retained-part boundary.  Only contained loops
        # represent internal through-cutouts; disconnected roots must not be
        # mistaken for holes simply because one happens to be smaller.
        inner = tuple(
            index
            for index, parent in enumerate(model.resolved_loop_parents)
            if parent is not None
        )
        operations = []
        if inner:
            operations.append(
                StepOperation(
                    "internal-through",
                    "Internal through-cutouts",
                    -(stock_thickness + breakthrough),
                    inner,
                    strategy="compensated inner profiles",
                )
            )
        operations.append(
            StepOperation(
                "outer-profile",
                "Outer profile",
                -(stock_thickness + breakthrough),
                depends_on=("internal-through",) if inner else (),
                strategy="compensated outer profile with retention tabs",
            )
        )
        return tuple(operations)
    if mode == "Detected feature":
        grouped: dict[float, list[int]] = {}
        for index, feature in enumerate(model.features):
            target_depth = (
                stock_thickness + breakthrough
                if feature.is_through
                else feature.depth
            )
            grouped.setdefault(round(target_depth, 7), []).append(index)
        sorted_groups = sorted(grouped.items(), reverse=True)
        operation_ids_by_feature: dict[int, str] = {}
        for index, (_feature_depth, feature_indices) in enumerate(sorted_groups):
            operation_id = f"feature-depth-{index}"
            for feature_index in feature_indices:
                operation_ids_by_feature[feature_index] = operation_id
        dependencies_by_operation: dict[str, set[str]] = {
            f"feature-depth-{index}": set()
            for index in range(len(sorted_groups))
        }
        for child_feature_index, child_feature in enumerate(model.features):
            parent_feature_indices = {
                parent_feature_index
                for parent_feature_index, parent_feature in enumerate(model.features)
                if parent_feature.loop_index == child_feature.parent_loop_index
            }
            child_operation_id = operation_ids_by_feature.get(child_feature_index)
            for parent_feature_index in parent_feature_indices:
                parent_operation_id = operation_ids_by_feature.get(parent_feature_index)
                if (
                    child_operation_id is not None
                    and parent_operation_id is not None
                    and child_operation_id != parent_operation_id
                ):
                    # Finish nested work before the containing feature so an
                    # island or support volume is not detached prematurely.
                    dependencies_by_operation[parent_operation_id].add(child_operation_id)

        operations = []
        for index, (feature_depth, feature_indices) in enumerate(sorted_groups):
            feature_kinds = tuple(sorted({model.features[feature_index].kind for feature_index in feature_indices}))
            if feature_kinds == ("Raised boss",):
                strategy = "connected boss-surround clearing"
            elif feature_kinds == ("Recess",):
                strategy = "connected pocket clearing"
            else:
                strategy = "connected mixed-feature clearing"
            operations.append(
                StepOperation(
                    f"feature-depth-{index}",
                    " / ".join(feature_kinds) + " clearing",
                    -feature_depth,
                    tuple(feature_indices),
                    tuple(sorted(dependencies_by_operation[f"feature-depth-{index}"])),
                    strategy,
                    feature_kinds,
                )
            )
        return _topological_operation_order(tuple(operations))
    if mode == "Planar surface":
        return (StepOperation("planar-surface", "Planar surface raster", depth, strategy="height-field raster"),)
    strategies = {
        "Engraving": "single-pass centerline",
        "Outside contour": "compensated outside contour",
        "Inside contour": "compensated inside contour",
        "Pocket": "connected scanline/offset clearing",
        "Hole": "circular compensated bore",
    }
    return (
        StepOperation(
            mode.lower().replace(" ", "-"),
            mode,
            depth,
            strategy=strategies.get(mode, ""),
        ),
    )


def validate_operation_plan(operations: tuple[StepOperation, ...]) -> None:
    """Fail closed when operation metadata cannot represent a valid DAG."""
    ids = [operation.operation_id for operation in operations]
    if len(ids) != len(set(ids)):
        raise ValueError("STEP operation plan contains duplicate operation IDs")
    if any(not math.isfinite(operation.target_depth) for operation in operations):
        raise ValueError("STEP operation plan contains a non-finite target depth")
    known = set(ids)
    seen: set[str] = set()
    for operation in operations:
        missing = set(operation.depends_on) - known
        if missing:
            raise ValueError(
                f"STEP operation {operation.operation_id} depends on unknown operation {sorted(missing)[0]}"
            )
        if operation.operation_id in operation.depends_on:
            raise ValueError(f"STEP operation {operation.operation_id} depends on itself")
        if not set(operation.depends_on) <= seen:
            raise ValueError(
                f"STEP operation {operation.operation_id} has a dependency that executes later; "
                "the emitted order contains a dependency cycle or is not topological"
            )
        seen.add(operation.operation_id)
    pending = {operation.operation_id: set(operation.depends_on) for operation in operations}
    resolved: set[str] = set()
    while pending:
        ready = sorted(operation_id for operation_id, dependencies in pending.items() if dependencies <= resolved)
        if not ready:
            raise ValueError("STEP operation plan contains a dependency cycle")
        for operation_id in ready:
            resolved.add(operation_id)
            pending.pop(operation_id)


def _topological_operation_order(
    operations: tuple[StepOperation, ...],
) -> tuple[StepOperation, ...]:
    """Return a stable operation order that satisfies every dependency."""
    by_id = {operation.operation_id: operation for operation in operations}
    pending = {operation.operation_id: set(operation.depends_on) for operation in operations}
    result: list[StepOperation] = []
    while pending:
        ready = [
            operation_id
            for operation_id in by_id
            if operation_id in pending and not pending[operation_id]
        ]
        if not ready:
            raise ValueError("STEP operation plan contains a dependency cycle")
        for operation_id in ready:
            result.append(by_id[operation_id])
            pending.pop(operation_id)
            for dependencies in pending.values():
                dependencies.discard(operation_id)
    return tuple(result)


def _outer_index(model: StepPlanarModel) -> int:
    return max(model.outer_loop_indices, key=lambda index: model.loops[index].area)
