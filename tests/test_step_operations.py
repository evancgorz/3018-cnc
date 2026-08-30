from __future__ import annotations

import pytest
from pathlib import Path

from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepFeature, StepPlanarModel
from ttc3018_control.step_operations import (
    StepOperation,
    build_step_operation_plan,
    validate_operation_plan,
)


def test_operation_plan_accepts_valid_dependencies() -> None:
    validate_operation_plan(
        (
            StepOperation("inside", "Inside", -1),
            StepOperation("outside", "Outside", -1, depends_on=("inside",)),
        )
    )


@pytest.mark.parametrize(
    "operations, message",
    [
        ((StepOperation("same", "A", -1), StepOperation("same", "B", -1)), "duplicate"),
        ((StepOperation("a", "A", -1, depends_on=("missing",)),), "unknown"),
        ((StepOperation("a", "A", -1, depends_on=("b",)), StepOperation("b", "B", -1, depends_on=("a",))), "cycle"),
        ((StepOperation("a", "A", float("nan")),), "non-finite"),
    ],
)
def test_operation_plan_rejects_invalid_graph(operations, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_operation_plan(operations)


def test_nested_detected_features_are_topologically_ordered_inner_first() -> None:
    def square(left: float, bottom: float, size: float) -> PlanarLoop:
        return PlanarLoop(tuple(
            Point2D(x, y)
            for x, y in (
                (left, bottom),
                (left + size, bottom),
                (left + size, bottom + size),
                (left, bottom + size),
            )
        ))

    model = StepPlanarModel(
        Path("nested.step"),
        (square(0, 0, 40), square(5, 5, 30), square(10, 10, 20)),
        5,
        5,
        (0, 0, 0, 40, 40, 5),
        features=(
            StepFeature("Recess", 1, 1, parent_loop_index=0),
            StepFeature("Recess", 2, 3, parent_loop_index=1),
        ),
        loop_parents=(None, 0, 1),
    )

    operations = build_step_operation_plan(
        model,
        "Detected feature",
        depth=-3,
        stock_thickness=5,
        breakthrough=0.2,
    )

    assert [operation.feature_indices for operation in operations] == [(1,), (0,)]
    assert operations[1].depends_on == ("feature-depth-0",)
    validate_operation_plan(operations)
