from __future__ import annotations

import json

import pytest

from ttc3018_control.simulation.parity import ParityCapture, ParityTolerance, compare_captures
from ttc3018_control.simulation.scenarios import Scenario, built_in_scenarios, run_headless_scenario
from ttc3018_control.simulation.models import SimulationIntent
from ttc3018_control.simulation.trace import (TraceEvent, TraceRecorder, compare_traces,
                                               first_trace_difference, load_trace,
                                               replay_scenario_trace)
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


def test_trace_load_rejects_bad_payload_time_and_truncated_json(tmp_path):
    malformed = tmp_path / "invalid.json"
    malformed.write_text(json.dumps({"schema_version": 1, "events": [
        {"sequence": 1, "time_ns": 2, "kind": "a", "payload": []},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="payload"):
        load_trace(malformed)
    malformed.write_text(json.dumps({"schema_version": 1, "events": [
        {"sequence": 1, "time_ns": 2, "kind": "a"},
        {"sequence": 2, "time_ns": 1, "kind": "b"},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="monotonic"):
        load_trace(malformed)
    malformed.write_text('{"schema_version": 1, "events": [', encoding="utf-8")
    with pytest.raises(ValueError, match="Truncated"):
        load_trace(malformed)
    malformed.write_text('{"schema_version": 1, "events": [{"sequence": 1, "time_ns": 0, "kind": "a", "payload": {"x": NaN}}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_trace(malformed)


def test_trace_canonical_digest_and_first_difference_are_stable():
    first = TraceRecorder(source="test")
    first.record(0, "command", {"z": 1, "pid": 10, "nested": {"port": 2, "keep": True}})
    second = TraceRecorder(source="test")
    second.record(0, "command", {"nested": {"keep": True, "port": 999}, "z": 1, "pid": 44})
    assert first.digest() == second.digest()
    left = (TraceEvent(1, 0, "command", {"line": "G1"}, "controller"),)
    right = (TraceEvent(1, 0, "response", {"line": "ok"}, "controller"),)
    assert first_trace_difference(left, right).startswith("event 1 identity")
    assert compare_traces(left, right)[0].startswith("event 1 identity")


def test_trace_evidence_is_bounded_without_breaking_sequence_validity(tmp_path):
    trace = TraceRecorder(source="bounded", max_events=3)
    for index in range(10):
        trace.record(index, "motion", {"index": index})
    assert trace.truncated
    assert [event.sequence for event in trace.events] == [1, 2, 3]
    path = tmp_path / "bounded.json"
    trace.export_json(path)
    assert len(load_trace(path)) == 3


def test_replay_api_and_cli_cover_every_builtin_scenario(tmp_path):
    for scenario in built_in_scenarios():
        trace = TraceRecorder(source="scenario")
        result = run_headless_scenario(scenario)
        for item in result.trace_events:
            trace.record(item["time_ns"], item["kind"], item["payload"], source=item["source"])
        path = tmp_path / f"{scenario.name}.trace.json"
        trace.export_json(path)
        replay = replay_scenario_trace(path)
        assert replay["matched"]
    status_trace = tmp_path / "status.trace.json"
    status_result = run_headless_scenario(built_in_scenarios()[0])
    source = TraceRecorder(source="scenario")
    for item in status_result.trace_events:
        source.record(item["time_ns"], item["kind"], item["payload"], source=item["source"])
    source.export_json(status_trace)
    assert main(["--replay", str(status_trace), "--output", str(tmp_path / "replay")]) == 0
    replay_json = json.loads((tmp_path / "replay" / "replay.json").read_text(encoding="utf-8"))
    assert replay_json["matched"] and (tmp_path / "replay" / "replay.md").exists()
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
