from pathlib import Path

import pytest

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.step_engraver import STEP_MODES, generate_step_gcode
from ttc3018_control.step_geometry import (
    PlanarLoop,
    Point2D,
    StepHeightField,
    StepPlanarModel,
    load_step_isolated,
)


ROOT = Path(__file__).parents[1]


def _surface_model(field: StepHeightField) -> StepPlanarModel:
    outer = PlanarLoop(
        (
            Point2D(0, 0),
            Point2D(field.columns * field.resolution, 0),
            Point2D(field.columns * field.resolution, field.rows * field.resolution),
            Point2D(0, field.rows * field.resolution),
        )
    )
    return StepPlanarModel(
        ROOT / "surface.synthetic.step",
        (outer,),
        0.0,
        5.0,
        (0, 0, 0, outer.bounds[2], outer.bounds[3], 5),
        height_field=field,
    )


def test_isolated_ocp_height_field_is_deterministic_and_bounded() -> None:
    path = ROOT / "examples" / "showcase-pocket-island.step"
    first = load_step_isolated(path)
    second = load_step_isolated(path)
    assert first.height_field is not None
    assert first.height_field.digest == second.height_field.digest
    assert first.height_field.resolution == pytest.approx(1.0)
    assert first.height_field.valid_cells > 0
    assert first.height_field.valid_cells + first.height_field.void_cells <= first.height_field.max_cells
    assert all(
        value is None or -first.thickness - 1e-6 <= value <= 1e-6
        for row in first.height_field.cells
        for value in row
    )
    assert "3D surface" in STEP_MODES


@pytest.mark.parametrize("fixture", ("cusp-nested-relief.step", "cusp-ramp-and-features.step"))
def test_curved_or_compound_fixture_has_visible_mesh_and_surface_program(fixture: str) -> None:
    model = load_step_isolated(ROOT / "examples" / fixture)
    assert model.height_field is not None
    job = generate_step_gcode(
        model,
        mode="3D surface",
        stock_width=model.width + 6,
        stock_height=model.height + 6,
        stock_thickness=model.thickness + 1,
        tool_diameter=3.175,
        safe_z=3,
        max_stepdown=1.0,
    )
    parsed = parse_gcode(job.gcode)
    assert job.surface_paths
    assert job.surface_simulation is not None and job.surface_simulation.passed
    assert all(
        point[0] >= 0 and point[1] >= 0 and point[2] <= 3
        for path in job.surface_paths
        for point in path
    )
    assert parsed.commands
    assert "3D surface" in job.gcode


def test_surface_raster_splits_voids_and_cliffs_without_bridging() -> None:
    field = StepHeightField(
        1.0,
        (
            (0.0, 0.0, None, None, -3.0, -3.0, -3.0),
            (0.0, 0.0, None, None, -3.0, -3.0, -3.0),
            (0.0, 0.0, None, None, -3.0, -3.0, -3.0),
            (0.0, 0.0, None, None, -3.0, -3.0, -3.0),
        ),
        12,
    )
    job = generate_step_gcode(
        _surface_model(field),
        mode="3D surface",
        stock_width=10,
        stock_height=6,
        stock_thickness=5,
        tool_diameter=1.0,
        safe_z=3,
        max_stepdown=1.0,
    )
    assert len(job.surface_paths) == 8
    assert all(len(path) in {2, 3} for path in job.surface_paths)
    assert all(abs(path[0][2] - path[-1][2]) <= 1e-9 for path in job.surface_paths)
    assert job.surface_simulation is not None and job.surface_simulation.passed


def test_height_field_rejects_nonfinite_and_over_budget_observations() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        StepHeightField(1.0, ((float("nan"),),), 1)
    with pytest.raises(ValueError, match="cell budget"):
        StepHeightField(1.0, ((0.0, 0.0),), 1, max_cells=1)


def test_3d_surface_requires_a_bounded_mesh_observation() -> None:
    model = _surface_model(
        StepHeightField(1.0, ((0.0, 0.0), (0.0, 0.0)), 2)
    )
    model = StepPlanarModel(
        model.path,
        model.loops,
        model.top_z,
        model.thickness,
        model.source_bounds,
    )
    with pytest.raises(ValueError, match="triangulated surface"):
        generate_step_gcode(model, mode="3D surface")


def test_3d_surface_rejects_explicit_undercut_collision_only_observation() -> None:
    field = StepHeightField(
        1.0,
        ((0.0, 0.0), (0.0, 0.0)),
        4,
        collision_only=True,
    )
    with pytest.raises(ValueError, match="collision-only"):
        generate_step_gcode(_surface_model(field), mode="3D surface")
