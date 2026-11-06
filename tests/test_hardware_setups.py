import json
from pathlib import Path

import pytest

from ttc3018_control.hardware_setups import (
    SetupRegistry, list_setups, load_setup, parse_setup, resolve_cam_defaults,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "hardware-setups"


def test_portable_examples_list_and_inspect_without_machine_store(tmp_path):
    summaries = list_setups(EXAMPLES)
    assert [item.id for item in summaries] == [
        "plywood-endmill-profile", "plywood-vbit-engraving"]
    registry = SetupRegistry(EXAMPLES)
    record = registry.load("plywood-vbit-engraving")
    assert record.stock["material"]["provenance"]["kind"] == "user-reported"
    assert record.fixture["datum"]["machine_x_mm"]["value"] is None
    assert record.tool["included_angle_deg"]["value"] == 30
    assert not list(tmp_path.iterdir())


def test_cam_defaults_only_apply_known_matching_facts():
    registry = SetupRegistry(EXAMPLES)
    defaults = registry.cam_defaults("plywood-vbit-engraving", "plaque", {})
    assert defaults == {
        "stock_thickness": 3.25, "v_angle": 30, "tip_diameter": .1,
        "width": 100, "height": 100}
    assert "cut_feed" not in defaults and "safe_z" not in defaults
    endmill = registry.cam_defaults("plywood-endmill-profile", "step-profile", {})
    assert endmill["tool_diameter"] == 3.175
    assert endmill["stock_width"] == endmill["stock_height"] == 100


def test_raster_requires_design_margin_to_match_known_stock():
    registry = SetupRegistry(EXAMPLES)
    matching = registry.cam_defaults(
        "plywood-vbit-engraving", "raster",
        {"outer_diameter": 80, "stock_margin": 10, "cut_feed": 400})
    assert matching["stock_thickness"] == 3.25
    assert "stock_margin" not in matching
    assert "cut_feed" not in matching
    with pytest.raises(ValueError, match="match square stock"):
        registry.cam_defaults(
            "plywood-vbit-engraving", "raster",
            {"outer_diameter": 80, "stock_margin": 5})


def test_reject_conflicting_or_malformed_setup(tmp_path):
    registry = SetupRegistry(EXAMPLES)
    with pytest.raises(ValueError, match="conflicts"):
        registry.cam_defaults(
            "plywood-vbit-engraving", "plaque", {"stock_thickness": 6})
    data = json.loads((EXAMPLES / "plywood-vbit-engraving.json").read_text())
    data["tool"]["included_angle_deg"]["provenance"]["kind"] = []
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance.kind"):
        load_setup(broken)

def test_registry_requires_filename_id_agreement(tmp_path):
    data = json.loads((EXAMPLES / "plywood-vbit-engraving.json").read_text())
    (tmp_path / "wrong-name.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="filename"):
        SetupRegistry(tmp_path).load("wrong-name")


def test_embedded_snapshot_is_immutable_and_preserves_provenance():
    value = json.loads((EXAMPLES / "plywood-vbit-engraving.json").read_text())
    record = parse_setup(value)
    value["stock"]["dimensions_mm"]["thickness"]["value"] = 12
    assert record.stock["dimensions_mm"]["thickness"]["value"] == 3.25
    with pytest.raises(TypeError):
        record.stock["shape"] = "round"
    snapshot = record.to_dict()
    snapshot["stock"]["shape"] = "round"
    assert record.stock["shape"] == "square"

def test_reject_non_g54_fixture_and_unsupported_round_stock(tmp_path):
    data = json.loads((EXAMPLES / "plywood-vbit-engraving.json").read_text())
    data["fixture"]["wcs_slot"] = 2
    record = parse_setup(data)
    with pytest.raises(ValueError, match="G54"):
        resolve_cam_defaults(record, "plaque", {})

    data["fixture"]["wcs_slot"] = 1
    data["stock"]["shape"] = "round"
    data["stock"]["dimensions_mm"] = {
        "thickness": data["stock"]["dimensions_mm"]["thickness"],
        "diameter": {"value": 100, "unit": "mm", "provenance": {"kind": "measured"}},
    }
    record = parse_setup(data)
    with pytest.raises(ValueError, match="requires square or rectangular"):
        resolve_cam_defaults(record, "plaque", {})
