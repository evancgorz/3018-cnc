from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from ttc3018_control.step_verification import StepVerificationError, verify_flat_clearing_paths


def test_flat_verifier_accepts_overlapping_lanes_and_reports_metrics() -> None:
    region = Polygon(((0, 0), (20, 0), (20, 10), (0, 10)))
    strokes = (
        ((1, 1), (19, 1), (19, 3), (1, 3), (1, 5), (19, 5), (19, 7), (1, 7), (1, 9), (19, 9)),
    )

    result = verify_flat_clearing_paths(strokes, region, 1)

    assert result.passed
    assert result.checked_strokes == 1
    assert result.swept_area > 0
    assert result.uncovered_area <= 0.05


def test_flat_verifier_rejects_centerline_outside_reachable_region() -> None:
    region = Polygon(((0, 0), (20, 0), (20, 10), (0, 10)))

    with pytest.raises(StepVerificationError, match="leaves"):
        verify_flat_clearing_paths((((-1, 5), (19, 5)),), region, 1)


def test_flat_verifier_rejects_region_smaller_than_tool() -> None:
    region = Polygon(((0, 0), (1, 0), (1, 1), (0, 1)))

    with pytest.raises(StepVerificationError, match="too small"):
        verify_flat_clearing_paths((((0.5, 0.5), (0.5, 0.6)),), region, 1)

