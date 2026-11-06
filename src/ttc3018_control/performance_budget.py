"""Conservative, explicitly calibrated runtime estimates for offline CNC review.

Nominal G-code estimates omit controller dynamics. Command acceptance counts
and partial job percentages are not physical progress evidence. Calibration
uses completed runs from a named, comparable machine/tool/material/CAM profile.
All target comparisons are informational; they never block execution.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any


CALIBRATION_SCHEMA_VERSION = 1
ESTABLISHED_CALIBRATION_RUNS = 3


def _positive_seconds(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive number of seconds")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number of seconds") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} must be a positive number of seconds")
    return seconds


def estimate_runtime_with_calibration(
    nominal_seconds: float,
    *,
    machine_profile_key: str,
    calibration: Mapping[str, Any] | None = None,
    target_minutes: float | None = None,
) -> dict[str, Any]:
    """Project actual duration using full, same-profile physical run samples.

    The estimate uses the largest observed actual/nominal ratio. One or two
    completed comparable runs still produce a projection, marked provisional;
    at least three label it established. Target comparisons are warnings only.
    """
    nominal = _positive_seconds(nominal_seconds, "nominal_seconds")
    target = None if target_minutes is None else _positive_seconds(
        float(target_minutes) * 60.0, "target_minutes")
    key = str(machine_profile_key).strip()
    if not key:
        raise ValueError("machine_profile_key is required for runtime calibration")

    base: dict[str, Any] = {
        "target_minutes": None if target is None else target / 60.0,
        "machine_profile_key": key,
        "nominal_seconds": nominal,
        "calibration_schema_version": CALIBRATION_SCHEMA_VERSION,
        "established_after_completed_runs": ESTABLISHED_CALIBRATION_RUNS,
        "target_comparison": None,
    }
    if calibration is None:
        return {
            **base,
            "status": "nominal_only",
            "message": "No completed-run calibration was supplied; actual runtime cannot be projected.",
            "completed_run_count": 0,
            "projected_seconds": None,
        }
    if calibration.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise ValueError("unsupported runtime calibration schema_version")
    calibration_key = str(calibration.get("machine_profile_key", "")).strip()
    if calibration_key != key:
        return {
            **base,
            "status": "profile_mismatch",
            "message": "Calibration profile does not match the candidate profile.",
            "calibration_profile_key": calibration_key,
            "completed_run_count": 0,
            "projected_seconds": None,
        }

    samples = calibration.get("completed_runs", ())
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        raise ValueError("completed_runs must be an array")
    ratios: list[float] = []
    evidence: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise ValueError(f"completed_runs[{index}] must be an object")
        if sample.get("completed") is not True:
            continue
        run_id = str(sample.get("run_id", "")).strip()
        program_sha256 = str(sample.get("program_sha256", "")).strip().lower()
        if not run_id:
            raise ValueError(f"completed_runs[{index}].run_id is required")
        if run_id in run_ids:
            raise ValueError(f"completed_runs[{index}].run_id is duplicated")
        if re.fullmatch(r"[0-9a-f]{64}", program_sha256) is None:
            raise ValueError(f"completed_runs[{index}].program_sha256 must be a 64-character SHA-256")
        planned = _positive_seconds(sample.get("nominal_seconds"), f"completed_runs[{index}].nominal_seconds")
        actual = _positive_seconds(sample.get("observed_seconds"), f"completed_runs[{index}].observed_seconds")
        ratio = actual / planned
        ratios.append(ratio)
        evidence.append({"run_id": run_id, "program_sha256": program_sha256,
                         "actual_to_nominal_ratio": ratio})
        run_ids.add(run_id)

    count = len(ratios)
    if count == 0:
        return {
            **base,
            "status": "nominal_only",
            "message": "No completed comparable runs are available; partial command counts are not runtime calibration.",
            "completed_run_count": 0,
            "projected_seconds": None,
        }

    # The maximum observed ratio keeps a small sample conservative. Profile
    # matching prevents blending measurements from different machine setups.
    factor = max(ratios)
    projected = nominal * factor
    established = count >= ESTABLISHED_CALIBRATION_RUNS
    target_comparison = None if target is None else (
        "projected_within_target" if projected <= target else "projected_over_target"
    )
    status = "calibrated_projection" if established else "provisional_projection"
    message = (
        "Projection uses the largest observed actual/nominal ratio for the matching profile."
        if established else
        f"Provisional projection from {count} completed run(s); {ESTABLISHED_CALIBRATION_RUNS} or more provide a steadier reference."
    )
    return {
        **base,
        "status": status,
        "message": message,
        "completed_run_count": count,
        "calibration_quality": "established" if established else "provisional",
        "observed_ratio_min": min(ratios),
        "observed_ratio_max": factor,
        "completed_run_evidence": evidence,
        "projected_seconds": projected,
        "projected_minutes": projected / 60.0,
        "target_comparison": target_comparison,
        "target_warning": (
            None if target_comparison is None else
            ("Projected time is above the requested target." if projected > target else
             "Projected time is within the requested target; this is not a runtime guarantee.")
        ),
        "method": "candidate nominal seconds multiplied by the maximum completed-run actual/nominal ratio for this exact profile key",
    }
