from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttc3018_control.simulation.commissioning import (
    CommissioningPlan,
    PhysicalCaptureProvider,
    SyntheticCaptureProvider,
    compare_commissioning_captures,
    default_commissioning_plan,
    physical_preflight_checklist,
    replay_commissioning_report,
    run_commissioning_ab,
    synthetic_commissioning_fixtures,
)
from ttc3018_control.simulation.parity import ParityCapture


def test_versioned_plan_matches_checked_in_machine_readable_script() -> None:
    plan = default_commissioning_plan()
    on_disk = json.loads((Path(__file__).parents[1] / "examples" / "commissioning_ab_plan.json").read_text(encoding="utf-8"))
    assert plan.to_dict() == on_disk
    assert [gate.mode for gate in plan.gates] == ["read_only", "tiny_jog", "wco", "probe", "spindle", "optional_cutting"]


@pytest.mark.parametrize("name", ["matched", "tolerated_drift"])
def test_synthetic_matched_and_tolerated_fixtures_pass(name: str) -> None:
    twin, controller = synthetic_commissioning_fixtures()[name]
    report = compare_commissioning_captures(default_commissioning_plan(), twin, controller)
    assert report.matched, report.to_dict()
    assert not report.aborted
    assert report.digest == compare_commissioning_captures(default_commissioning_plan(), twin, controller).digest


@pytest.mark.parametrize("name,category", [
    ("semantic_mismatch", "semantic"),
    ("unexpected_alarm", "unexpected_alarm"),
    ("missing_response", "missing"),
    ("malformed_capture", "malformed"),
])
def test_synthetic_mismatch_fixtures_report_first_divergence_and_abort(name: str, category: str) -> None:
    twin, controller = synthetic_commissioning_fixtures()[name]
    report = compare_commissioning_captures(default_commissioning_plan(), twin, controller)
    assert not report.matched and report.aborted
    assert report.first_divergence
    assert any(item.category == category for item in report.differences)


def test_report_json_markdown_and_replay_are_stable(tmp_path: Path) -> None:
    twin, controller = synthetic_commissioning_fixtures()["tolerated_drift"]
    report = run_commissioning_ab(default_commissioning_plan(), SyntheticCaptureProvider(twin), SyntheticCaptureProvider(controller), tmp_path)
    assert report.matched
    assert (tmp_path / "commissioning_report.json").is_file()
    assert (tmp_path / "commissioning_report.md").is_file()
    assert (tmp_path / "twin_capture.json").is_file()
    replay = replay_commissioning_report(tmp_path / "commissioning_report.json")
    assert replay.to_dict() == report.to_dict()
    assert replay.digest == report.digest


def test_physical_provider_requires_explicit_authorization_and_exact_endpoint() -> None:
    plan = default_commissioning_plan()
    with pytest.raises(PermissionError):
        PhysicalCaptureProvider().capture(plan)
    with pytest.raises(ValueError):
        PhysicalCaptureProvider(authorized=True).capture(plan)
    with pytest.raises(RuntimeError, match="not executable"):
        PhysicalCaptureProvider(authorized=True, endpoint="explicit-only").capture(plan)


def test_preflight_checklist_is_inert_and_explicit() -> None:
    checklist = physical_preflight_checklist()
    assert any("Emergency-stop" in item for item in checklist)
    assert any("Exact endpoint" in item for item in checklist)
    assert any("spindle" in item.lower() for item in checklist)
