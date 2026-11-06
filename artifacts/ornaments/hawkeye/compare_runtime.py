"""Compare offline examples; never connects to a controller or changes G-code."""
from pathlib import Path
import hashlib
import json
import math

from ttc3018_control.gcode import parse_gcode, validate_rapid_xy_clearance


def metrics(text):
    program = parse_gcode(text)
    validate_rapid_xy_clearance(program, 3.0)
    result = {name: 0.0 for name in ("cutting_minutes", "plunge_minutes", "rapid_minutes")}
    plunges = 0
    for segment in program.segments:
        distance = math.dist(
            (segment.start.x, segment.start.y, segment.start.z),
            (segment.end.x, segment.end.y, segment.end.z),
        )
        xy = (segment.start.x, segment.start.y) != (segment.end.x, segment.end.y)
        name = "rapid_minutes" if segment.rapid else "cutting_minutes" if xy else "plunge_minutes"
        result[name] += distance / (3000 if segment.rapid else segment.feed or 300)
        if not segment.rapid and not xy and segment.end.z < segment.start.z:
            plunges += 1
    result["estimated_minutes"] = program.estimated_seconds / 60
    result["plunges"] = plunges
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    baseline = root / "draft-review-v2"
    scheduling = root / "runtime-optimized-v1"
    optimized = root / "runtime-approach-v1"
    before = json.loads((baseline / "report.json").read_text(encoding="utf-8"))
    after = json.loads((optimized / "report.json").read_text(encoding="utf-8"))
    assert before["source_sha256"] == after["source_sha256"]
    assert all(after["settings"][key] == value for key, value in before["settings"].items())
    text = (optimized / "engraving.nc").read_text(encoding="ascii")
    first = text.index("(Engraving pass 1 of 2)")
    second = text.index("(Engraving pass 2 of 2)")
    # Timing projection only: retain the final-depth pass in memory. This does
    # NOT verify that a single 0.25 mm pass is suitable for the real material.
    single = text[:first] + text[second:]
    result = {
        "scope": "engraving only; no cutout, tool-change, acceleration or hardware timing",
        "rapid_assumption_mm_per_min": 3000,
        "same_source_depth_feeds_and_tool_width": True,
        "approach_scenario": "Vertical rapid to +0.2 mm after XY travel at +3 mm; assumes verified flatness/clearance",
        "baseline_two_pass": metrics((baseline / "engraving.nc").read_text(encoding="ascii")),
        "scheduling_only_two_pass_unchanged_settings": metrics((scheduling / "engraving.nc").read_text(encoding="ascii")),
        "optimized_two_pass_with_illustrative_approach": metrics(text),
        "single_pass_timing_projection_unverified": metrics(single),
        "single_pass_caveat": "Requires max_stepdown 0.25 instead of 0.125; untested, not a cutting recommendation",
        "artwork_inaccessible_fraction_unchanged": after["inaccessible_black_fraction"],
        "optimized_program_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        "generator_sha256": hashlib.sha256((root.parents[2] / "src/ttc3018_control/ornament_cam.py").read_bytes()).hexdigest(),
    }
    (optimized / "runtime-comparison.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
