from __future__ import annotations

import json

import pytest

from ttc3018_control.simulation.property_scenarios import (
    COMPACT_PROPERTY_SEEDS,
    DEFAULT_PROPERTY_STEPS,
    run_property_corpus,
    run_property_scenario,
    write_property_replay_artifact,
)


def test_compact_seed_corpus_preserves_long_run_invariants_and_digest_replay():
    first = run_property_corpus(COMPACT_PROPERTY_SEEDS, steps=48)
    second = run_property_corpus(COMPACT_PROPERTY_SEEDS, steps=48)
    assert all(result.passed for result in first), first
    assert [result.trace_digest for result in first] == [result.trace_digest for result in second]
    assert all(result.max_planner_depth <= 15 for result in first)
    assert all(result.max_response_depth <= 256 for result in first)
    assert all(all(a >= b - 1e-8 for a, b in zip(result.stock_volumes, result.stock_volumes[1:]))
               for result in first)


def test_property_result_reports_seed_step_action_and_replay_artifact(tmp_path):
    result = run_property_scenario(13, steps=DEFAULT_PROPERTY_STEPS, stress_depth=2)
    assert result.passed, result.replay_context()
    artifact = tmp_path / "property-replay.json"
    write_property_replay_artifact(result, artifact)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["seed"] == 13
    assert payload["replay"]["steps"] == DEFAULT_PROPERTY_STEPS


@pytest.mark.parametrize("kwargs", [
    {"steps": 0}, {"steps": 4097}, {"stress_depth": 0}, {"stress_depth": 17},
])
def test_property_controls_are_bounded(kwargs):
    with pytest.raises(ValueError):
        run_property_scenario(1, **kwargs)
