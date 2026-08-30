from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from ttc3018_control.step_simulation import (
    StepSimulationError,
    simulate_flat_stock_paths,
    simulate_profile_paths,
    simulate_surface_paths,
)


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


def test_surface_simulation_checks_coverage_and_height_field() -> None:
    paths = (
        ((1, 1, -0.1), (9, 1, -0.9), (9, 3, -0.9), (1, 3, -0.1),
         (1, 5, -0.1), (9, 5, -0.9), (9, 7, -0.9), (1, 7, -0.1),
         (1, 9, -0.1), (9, 9, -0.9)),
    )

    result = simulate_surface_paths(
        paths,
        Polygon(((0, 0), (10, 0), (10, 10), (0, 10))),
        1,
        lambda x, _y: -0.1 * x,
        stock_width=10,
        stock_height=10,
        stock_thickness=2,
    )

    assert result.passed
    assert result.minimum_z == pytest.approx(-0.9)
    assert result.maximum_z == pytest.approx(-0.1)
    assert result.maximum_surface_error == pytest.approx(0)


def test_surface_simulation_rejects_discontinuity_and_unsafe_slope() -> None:
    with pytest.raises(StepSimulationError, match="discontinuity"):
        simulate_surface_paths(
            (((1, 1, -0.1), (9, 1, -0.9)),),
            _rectangle(),
            1,
            lambda x, _y: None if x > 5 else -0.1,
        )

    with pytest.raises(StepSimulationError, match="slope"):
        simulate_surface_paths(
            (((1, 1, 0), (2, 1, -5)),),
            _rectangle(),
            1,
            lambda _x, _y: 0,
            maximum_slope=1,
        )


def test_profile_simulation_accepts_compensated_boundary_and_checks_depth() -> None:
    retained = Polygon(((1, 1), (21, 1), (21, 11), (1, 11)))
    profile = tuple((float(x), float(y)) for x, y in retained.buffer(1, join_style=2).exterior.coords)

    result = simulate_profile_paths(
        (profile,),
        retained,
        1,
        -2.2,
        stock_width=22,
        stock_height=12,
        stock_thickness=2,
        breakthrough=0.2,
    )

    assert result.passed
    assert result.gouged_area <= result.allowed_gouged_area

    with pytest.raises(StepSimulationError, match="physical stock"):
        simulate_profile_paths(
            (profile,), retained, 1, -2.3,
            stock_width=22, stock_height=12, stock_thickness=2,
            breakthrough=0.2,
        )


def test_profile_simulation_rejects_a_path_that_is_not_on_the_boundary() -> None:
    with pytest.raises(StepSimulationError, match="boundary band"):
        simulate_profile_paths(
            (((5, 5), (17, 7)),),
            Polygon(((1, 1), (21, 1), (21, 11), (1, 11))),
            1,
            -1,
            stock_width=22,
            stock_height=12,
            stock_thickness=2,
        )
