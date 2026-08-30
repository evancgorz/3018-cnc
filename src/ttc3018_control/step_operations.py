"""Normalized operation planning for the bounded STEP 2.5D workflow."""

from __future__ import annotations

from dataclasses import dataclass

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


def _outer_index(model: StepPlanarModel) -> int:
    return max(range(len(model.loops)), key=lambda index: model.loops[index].area)

