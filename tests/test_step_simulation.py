from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from ttc3018_control.step_simulation import StepSimulationError, simulate_flat_stock_paths


def _rectangle() -> Polygon:
    return Polygon(((0, 0), (20, 0), (20, 10), (0, 10)))


def _covered_lanes() -> tuple[tuple[tuple[float, float], ...], ...]:
    return (
        (
            (1, 1), (19, 1), (19, 3), (1, 3), (1, 5),
            (19, 5), (19, 7), (1, 7), (1, 9), (19, 9),
        ),
    )


def test_flat_stock_simulation_reports_reachable_coverage_and_unreachable_corners() -> None:
    result = simulate_flat_stock_paths(
        _covered_lanes(),
        _rectangle(),
        1,
        -1,
        stock_width=20,
        stock_height=10,
        stock_thickness=2,
        passes=2,
    )

    assert result.passed
    assert result.checked_strokes == 1
    assert result.cutting_segments == 9
    assert result.target_area == pytest.approx(200)
    assert result.reachable_area == pytest.approx(144)
    assert result.unreachable_area > 0
    assert result.uncovered_area <= result.allowed_uncovered_area
    assert result.passes == 2


def test_flat_stock_simulation_rejects_sparse_coverage() -> None:
    with pytest.raises(StepSimulationError, match="uncut"):
        simulate_flat_stock_paths((((1, 5), (19, 5)),), _rectangle(), 1, -1)


def test_flat_stock_simulation_rejects_centerline_outside_reachable_region() -> None:
    with pytest.raises(StepSimulationError, match="reachable"):
        simulate_flat_stock_paths((((0, 5), (19, 5)),), _rectangle(), 1, -1)


def test_flat_stock_simulation_rejects_depth_below_physical_stock() -> None:
    with pytest.raises(StepSimulationError, match="physical stock"):
        simulate_flat_stock_paths(
            _covered_lanes(), _rectangle(), 1, -2.1, stock_thickness=2
        )


def test_flat_stock_simulation_rejects_swept_retained_material() -> None:
    retained = Polygon(((8, 4), (12, 4), (12, 6), (8, 6)))

    with pytest.raises(StepSimulationError, match="gouges"):
        simulate_flat_stock_paths(
            _covered_lanes(),
            _rectangle(),
            1,
            -1,
            retained_region=retained,
        )
