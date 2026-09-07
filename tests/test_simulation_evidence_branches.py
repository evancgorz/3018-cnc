from __future__ import annotations

import json

import pytest

from ttc3018_control.simulation.parity import ParityCapture, ParityTolerance, compare_captures
from ttc3018_control.simulation.scenarios import Scenario, run_headless_scenario
from ttc3018_control.simulation.models import SimulationIntent
from ttc3018_control.simulation.trace import TraceRecorder, compare_traces, load_trace
from ttc3018_control.simulation.verify import main


def test_parity_numeric_timing_semantic_count_and_validation(tmp_path):
    with pytest.raises(ValueError):
        ParityTolerance(position_mm=-1).validate()
    left = ParityCapture([{"x": 1, "y": 2, "z": 3, "position_mm": 4, "time_ns": 1_000_000_000,
                           "elapsed_seconds": 1, "feed": 100, "mode": "A", "wall_time": 1, "pid": 1, "port": 1}])
    right = ParityCapture([{"x": 1.01, "y": 2.2, "z": 3, "position_mm": 4.3, "time_ns": 1_600_000_000,
                            "elapsed_seconds": 2, "feed": 200, "mode": "B", "wall_time": 2, "pid": 2, "port": 2}])
    report = compare_captures(left, right)
    assert not report.matched
    assert {d.category for d in report.differences} >= {"numeric", "timing", "semantic"}
    short = compare_captures(left, ParityCapture([]))
    assert any(d.category == "count" for d in short.differences)
    path = tmp_path / "capture.json"
    left.write(path)
    assert ParityCapture.from_json(path).to_dict()["source"] == "unknown"
    path.write_text(json.dumps({"schema_version": 9, "events": []}))
    with pytest.raises(ValueError):
        ParityCapture.from_json(path)
    with pytest.raises(FileNotFoundError):
        ParityCapture.from_json(tmp_path / "does-not-exist.json")


def test_trace_exports_normalization_and_malformed_replay(tmp_path):
    trace = TraceRecorder(source="test")
    trace.record(0, "one", {"pid": 4, "port": 5, "wall_time": 6, "absolute_path": "x", "session_id": "s", "keep": 1})
    trace.record(1, "two", {"a": 2})
    assert trace.canonical(normalize=False)[0]["payload"]["pid"] == 4
    assert "pid" not in trace.canonical()[0]["payload"]
    json_path = tmp_path / "nested" / "trace.json"
    md_path = tmp_path / "nested" / "trace.md"
    trace.export_json(json_path)
    trace.export_markdown(md_path, title="Evidence")
    assert load_trace(json_path)[0].payload == {"keep": 1}
    assert compare_traces(trace.events, trace.events[:-1])
    malformed = tmp_path / "bad.json"
    malformed.write_text(json.dumps({"schema_version": 1, "events": [{"sequence": 2, "time_ns": 1, "kind": "x"}]}))
    with pytest.raises((ValueError, KeyError)):
        load_trace(malformed)
    malformed.write_text(json.dumps({"schema_version": 9, "events": []}))
    with pytest.raises((ValueError, KeyError)):
        load_trace(malformed)
    malformed.write_text(json.dumps({"schema_version": 1, "events": [{"sequence": 1, "time_ns": 1}]}))
    with pytest.raises((ValueError, KeyError)):
        load_trace(malformed)


def test_custom_unknown_and_malformed_scenarios():
    unknown = run_headless_scenario(Scenario("custom", 9, (SimulationIntent("mystery"),)))
    assert not unknown.passed and "unknown intent" in unknown.failures[0]
    malformed = run_headless_scenario(Scenario("custom", 9, (SimulationIntent("malformed"),)))
    assert malformed.passed


def test_verification_cli_all_named_and_no_match(tmp_path):
    assert main(["--all", "--output", str(tmp_path / "all")]) == 0
    assert (tmp_path / "all" / "summary.json").exists()
    assert main(["--scenario", "status", "--output", str(tmp_path / "one"), "--workpiece", "missing.step"]) == 0
    with pytest.raises(SystemExit):
        main(["--scenario", "missing", "--output", str(tmp_path / "none")])
