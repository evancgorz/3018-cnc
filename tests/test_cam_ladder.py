from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from ttc3018_control.agent_cam import build
from ttc3018_control.cam_ladder import compare_raster_candidates, generate_raster_ladder


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "agent-cam"


def _baseline(tmp_path: Path) -> Path:
    folder = tmp_path / "baseline"
    build(EXAMPLES / "raster.json", folder)
    return folder


def test_ladder_generates_faster_exact_file_candidates_with_measured_sweep_omission(tmp_path):
    baseline = _baseline(tmp_path)
    output = tmp_path / "ladder"
    result = generate_raster_ladder(
        baseline / "report.json", output, [0.16, 0.20], max_omission_fraction=0.01,
    )

    baseline_data = json.loads((baseline / "report.json").read_text())
    baseline_seconds = baseline_data["motion"]["feed_based_seconds"]
    assert result["status"] == "review-only"
    assert len(result["candidates"]) == 2
    assert all(item["fidelity_limit_met"] for item in result["candidates"])
    assert all(item["feed_based_seconds"] < baseline_seconds for item in result["candidates"])
    assert result["candidates"][1]["feed_based_seconds"] < result["candidates"][0]["feed_based_seconds"]
    assert all(item["omitted_artwork_fraction"] <= 0.01 for item in result["candidates"])
    assert not (output / "stepover-0.16" / "comparison.json").exists()
    assert (output / result["candidates"][0]["comparison"]).exists()

    for item in result["candidates"]:
        report_path = output / item["candidate_directory"] / "report.json"
        comparison = compare_raster_candidates(
            baseline / "report.json", report_path, max_omission_fraction=0.01,
        )
        assert comparison["candidate"]["gcode_sha256"] == item["gcode_sha256"]
        assert comparison["candidate"]["coverage"]["verified_final_depth_surface_sweep"]
        assert comparison["delta"]["feed_based_seconds"] < 0
        bundle = report_path.parent
        for name, digest in json.loads(report_path.read_text())["sha256"].items():
            assert hashlib.sha256((bundle / name).read_bytes()).hexdigest() == digest


def test_comparison_rejects_changed_fixed_inputs_and_untrusted_gcode(tmp_path):
    baseline = _baseline(tmp_path)
    changed = json.loads((baseline / "design.json").read_text())
    changed["source"] = "baseline/source.pgm"
    changed["settings"]["cut_feed"] += 1
    candidate_dir = tmp_path / "changed"
    spec_path = tmp_path / "changed.json"
    spec_path.write_text(json.dumps(changed))
    build(spec_path, candidate_dir)
    with pytest.raises(ValueError, match="cut_feed"):
        compare_raster_candidates(baseline / "report.json", candidate_dir / "report.json")

    changed["settings"]["cut_feed"] -= 1
    changed["settings"]["stepover"] = 0.16
    spec_path.write_text(json.dumps(changed))
    tampered = tmp_path / "tampered"
    build(spec_path, tampered)
    with (tampered / "candidate-review-only.nc").open("a", encoding="ascii") as handle:
        handle.write("; tampered\n")
    with pytest.raises(ValueError, match="G-code changed"):
        compare_raster_candidates(baseline / "report.json", tampered / "report.json")


def test_fidelity_limit_is_explicit_and_output_is_immutable(tmp_path):
    baseline = _baseline(tmp_path)
    output = tmp_path / "ladder"
    result = generate_raster_ladder(
        baseline / "report.json", output, [0.20], max_omission_fraction=0.0,
    )
    assert not result["candidates"][0]["fidelity_limit_met"]
    assert (output / "stepover-0.2" / "candidate-review-only.nc").exists()
    with pytest.raises(ValueError, match="already exists"):
        generate_raster_ladder(
            baseline / "report.json", output, [0.20], max_omission_fraction=0.1,
        )


@pytest.mark.parametrize("stepovers", [[], [0.12], [0.16, 0.16], [float("nan")], [0.21]])
def test_invalid_ladder_settings_are_rejected_before_output(tmp_path, stepovers):
    baseline = _baseline(tmp_path)
    output = tmp_path / "ladder"
    with pytest.raises(ValueError):
        generate_raster_ladder(
            baseline / "report.json", output, stepovers, max_omission_fraction=0.1,
        )
    assert not output.exists()
