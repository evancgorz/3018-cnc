from __future__ import annotations

import pytest

from ttc3018_control.step_operations import StepOperation, validate_operation_plan


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

