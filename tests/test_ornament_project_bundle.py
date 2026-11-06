import hashlib
import json
from pathlib import Path

from ttc3018_control.gcode import (
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit" / "c018-reproducible-project"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ornament_project_binds_source_setup_and_review_outputs():
    project = json.loads((BUNDLE / "ornament-project.json").read_text(encoding="utf-8"))
    report = json.loads((BUNDLE / "review-report.json").read_text(encoding="utf-8"))
    source = ROOT / project["artwork"]["source_path"]
    vbit_setup = ROOT / project["setup_inputs"]["engraving"]["source_path"]
    endmill_setup = ROOT / project["setup_inputs"]["profile"]["source_path"]
    vector_geometry = BUNDLE / project["artwork"]["vector_geometry"]

    assert project["status"] == "offline_review_only_not_released"
    assert project["artwork"]["retained_source"] is True
    assert _sha256(source) == project["artwork"]["sha256"]
    assert _sha256(vbit_setup) == project["setup_inputs"]["engraving"]["sha256"]
    assert _sha256(endmill_setup) == project["setup_inputs"]["profile"]["sha256"]
    assert _sha256(vector_geometry) == project["inputs_sha256"]["vectorized_artwork_svg"]
    assert project["stock"]["dimensions_mm"] == [110.0, 110.0]
    assert project["stock"]["candidate_dimensions_provenance"].startswith("unverified")
    assert project["stock"]["recorded_setup_dimensions_mm"]["width"] == 100.0
    assert project["fixture_provenance"]["machine_x_mm"] is None
    assert project["process_provenance"]["spindle_rpm"].startswith("unknown")
    assert project["tools"][1]["flute_length_mm"] is None
    assert project["production_release_blockers"]

    for filename, digest in project["outputs_sha256"].items():
        assert _sha256(BUNDLE / filename) == digest
        assert report["outputs_sha256"][filename] == digest


def test_exact_review_programs_share_frame_and_keep_profile_order_and_tabs():
    project = json.loads((BUNDLE / "ornament-project.json").read_text(encoding="utf-8"))
    report = json.loads((BUNDLE / "review-report.json").read_text(encoding="utf-8"))
    engraving_path = BUNDLE / "engraving-review.nc"
    profile_path = BUNDLE / "disc-hole-profile-review.nc"
    engraving_text = engraving_path.read_text(encoding="ascii")
    profile_text = profile_path.read_text(encoding="ascii")
    engraving = parse_gcode(engraving_text, engraving_path)
    profile = parse_gcode(profile_text, profile_path)

    for program in (engraving, profile):
        validate_nonnegative_work_xy(program)
        validate_rapid_xy_clearance(program, 3.0)
    assert "vbit-30deg-0p1" in engraving_text
    assert "endmill-3p175" in profile_text
    assert "G54" in engraving_text and "G54" in profile_text
    assert "M6" not in engraving_text.upper()
    assert "M6" not in profile_text.upper()
    assert "internal-through" in profile_text
    assert profile_text.index("internal-through") < profile_text.index("outer-profile")
    assert "4 x 3 mm, height 0.7 mm" in profile_text
    assert project["origin"].startswith("lower-left")
    assert project["work_coordinate_system"].startswith("G54 P1")
    assert report["shared_xy_frame"] == project["origin"]

    profile_report = report["profile"]
    assert report["engraving"]["operation_id"] == "engrave-approved-artwork"
    assert report["engraving"]["tool_id"] == "vbit-30deg-0p1"
    assert profile_report["tool_id"] == "endmill-3p175"
    assert profile_report["operation_depth_mm"] == 3.45
    assert report["operations"][1]["depends_on"] == []
    assert report["operations"][2]["depends_on"] == ["hanger-hole-through"]
    assert "profile-preview.svg" in project["outputs_sha256"]
    assert profile_report["operation_order"] == ["internal-through", "outer-profile"]
    assert profile_report["xy_frame"]["work_coordinate_system"].startswith("G54 P1")
    assert profile_report["inner_cut_count"] == 1
    assert profile_report["outer_cut_count"] == 1
    assert profile_report["compensated_contours"][0]["id"] == "hanger-hole"
    assert profile_report["compensated_contours"][0]["expected_centerline_radius_mm"] > 0
    assert profile_report["compensated_contours"][1]["id"] == "outside-profile"
    assert profile_report["compensated_contours"][1]["center_stock_xy_mm"] == [55.0, 55.0]
    assert profile_report["simulation"]["passed"] is True
    assert profile_report["simulation"]["retained_gouge_area_mm2"] == 0
    assert profile_report["tabs"]["only_outer_profile"] is True
    assert profile_report["tabs"]["tab_floor_transition_count_in_exact_nc"] == 8
    sweep_bounds = profile_report["exact_tool_sweep_bounds_xy_mm"]
    assert min(sweep_bounds[:2]) > 0
    assert max(sweep_bounds[2:]) < 110

    artwork = report["engraving"]["placement_and_features"]
    assert artwork["hanger"]["nearest_part_edge_wood_ligament_mm"] == 3.0
    assert artwork["hanger"]["cut_sweep_clear_of_hanger_keepout"] is True
    assert artwork["exact_sweep_within_candidate_110mm_stock"] is True
    assert artwork["part"]["center_stock_xy_mm"] == profile_report["xy_frame"]["part_center_mm"]
    assert artwork["minimum_connected_black_component_max_inscribed_diameter_mm"] > 0
    assert artwork["minimum_gap_between_distinct_black_components_mm"] >= 0
    assert artwork["source_counters_narrower_than_final_cutter_mm"] > 0
    assert artwork["unengraved_black_area_mm2"] > 0
    assert artwork["unengraved_black_fraction"] > 0
    assert report["engraving"]["checks"]["exact_vbit_sweep_inside_art"] is True
