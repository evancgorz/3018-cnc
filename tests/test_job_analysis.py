import json
import subprocess
import sys

from ttc3018_control.job_analysis import analyze
from ttc3018_control.performance_budget import estimate_runtime_with_calibration


def test_analyze_counts_real_segments_and_resets_turns_at_rapid(tmp_path):
    path = tmp_path / "example.nc"
    path.write_text("G21 G90\nG0 Z2\nG1 Z-1 F60\nG1 X1\nG1 Y1\nG0 Z3\nG0 X2 Y1\nG1 Z-0.5\nG1 X3\nG0 Z3\nM5\nM2\n")
    report = analyze(path)
    assert report["nonzero_cut_segments"] == 3
    assert report["cut_junctions_at_least_90_degrees"] == 1
    assert report["median_cut_segment_mm"] == 1
    assert report["bounds_mm"]["max"]["z"] == 3
    assert report["cut_distance_mm"] == 3
    assert report["plunge_distance_mm"] == 6.5
    assert report["rapid_xy_distance_mm"] == 1
    assert report["rapid_z_distance_mm"] == 9.5
    assert report["retract_count"] == 2
    assert report["cut_segments_at_most_0_1mm"] == 0
    assert report["cut_segments_at_most_0_25mm_percent"] == 0.0
    assert report["cut_junctions_at_least_90_degrees_percent"] == 100.0
    assert report["retracts_per_1000_commands"] > 0
    assert len(report["sha256"]) == 64
    result = subprocess.run([sys.executable, "-m", "ttc3018_control.job_analysis", str(path)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == report
    gated = subprocess.run(
        [sys.executable, "-m", "ttc3018_control.job_analysis", str(path),
         "--target-minutes", "45", "--machine-profile-key", "test-profile"],
        capture_output=True, text=True, check=True,
    )
    runtime_estimate = json.loads(gated.stdout)["runtime_estimate"]
    assert runtime_estimate["status"] == "nominal_only"
    assert runtime_estimate["target_comparison"] is None
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps({
        "schema_version": 1,
        "machine_profile_key": "test-profile",
        "completed_runs": [
            {"completed": True, "run_id": f"run-{i}", "program_sha256": hex(i)[2:] * 64,
             "nominal_seconds": 60, "observed_seconds": 120}
            for i in range(1, 4)
        ],
    }))
    calibrated = subprocess.run(
        [sys.executable, "-m", "ttc3018_control.job_analysis", str(path),
         "--target-minutes", "45", "--machine-profile-key", "test-profile",
         "--calibration-json", str(calibration_path)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(calibrated.stdout)["runtime_estimate"]["status"] == "calibrated_projection"


def test_runtime_estimate_requires_matching_completed_run_calibration() -> None:
    nominal = 600.0
    no_calibration = estimate_runtime_with_calibration(
        nominal, target_minutes=45, machine_profile_key="3018-vbit30-plywood-raster",
        calibration=None,
    )
    assert no_calibration["status"] == "nominal_only"
    assert no_calibration["projected_seconds"] is None

    calibration = {
        "schema_version": 1,
        "machine_profile_key": "3018-vbit30-plywood-raster",
        "completed_runs": [
            {"completed": True, "run_id": "r1", "program_sha256": "a" * 64,
             "nominal_seconds": 600, "observed_seconds": 240},
            {"completed": True, "run_id": "r2", "program_sha256": "b" * 64,
             "nominal_seconds": 600, "observed_seconds": 250},
            {"completed": True, "run_id": "r3", "program_sha256": "c" * 64,
             "nominal_seconds": 600, "observed_seconds": 300},
            # Partial runs are intentionally ignored, regardless of accepted counts.
            {"completed": False, "nominal_seconds": 600, "observed_seconds": 5000,
             "accepted_commands": 99999},
        ],
    }
    result = estimate_runtime_with_calibration(
        nominal, target_minutes=45, machine_profile_key="3018-vbit30-plywood-raster",
        calibration=calibration,
    )
    assert result["status"] == "calibrated_projection"
    assert result["completed_run_count"] == 3
    assert result["observed_ratio_max"] == 0.5
    assert result["projected_seconds"] == 300
    assert result["target_comparison"] == "projected_within_target"
    assert result["target_warning"].endswith("not a runtime guarantee.")


def test_runtime_estimate_is_conservative_and_reports_other_profiles() -> None:
    too_slow = {
        "schema_version": 1,
        "machine_profile_key": "3018-vbit30-plywood-raster",
        "completed_runs": [
            {"completed": True, "run_id": "s1", "program_sha256": "a" * 64,
             "nominal_seconds": 600, "observed_seconds": 3000},
            {"completed": True, "run_id": "s2", "program_sha256": "b" * 64,
             "nominal_seconds": 600, "observed_seconds": 2400},
            {"completed": True, "run_id": "s3", "program_sha256": "c" * 64,
             "nominal_seconds": 600, "observed_seconds": 2700},
        ],
    }
    result = estimate_runtime_with_calibration(
        600, target_minutes=45, machine_profile_key="3018-vbit30-plywood-raster",
        calibration=too_slow,
    )
    assert result["status"] == "calibrated_projection"
    assert result["projected_minutes"] == 50
    assert result["target_comparison"] == "projected_over_target"

    mismatch = estimate_runtime_with_calibration(
        600, target_minutes=45, machine_profile_key="different-profile", calibration=too_slow,
    )
    assert mismatch["status"] == "profile_mismatch"
    assert mismatch["projected_seconds"] is None

    insufficient = estimate_runtime_with_calibration(
        600, target_minutes=45, machine_profile_key="3018-vbit30-plywood-raster",
        calibration={**too_slow, "completed_runs": too_slow["completed_runs"][:2]},
    )
    assert insufficient["status"] == "provisional_projection"
    assert insufficient["projected_minutes"] == 50
    assert insufficient["calibration_quality"] == "provisional"
