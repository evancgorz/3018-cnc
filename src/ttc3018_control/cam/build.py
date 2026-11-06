"""Build a reproducible, review-only CNC bundle from a versioned design spec."""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import json
import math
from pathlib import Path

from ..gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
from ..job_analysis import analyze_program


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data) -> bytes:
    return (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _keys(data, required, optional=()):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    missing = set(required) - data.keys()
    extra = data.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"Missing fields: {', '.join(sorted(missing)) or 'none'}; "
                         f"unknown fields: {', '.join(sorted(extra)) or 'none'}")


def _number(settings, key):
    value = settings[key]
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be a finite positive number")
    return value


def _preview(program, width, height, diameter):
    paths = []
    for s in program.segments:
        if s.rapid or s.end.z >= 0 or s.start.z != s.end.z:
            continue
        x, y = s.start.x, height - s.start.y
        a, b = s.end.x, height - s.end.y
        if (x, y) != (a, b):
            paths.append(f"M{x:.6f} {y:.6f}L{a:.6f} {b:.6f}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}">\n'
        '<title>Top-surface cutter sweep; not a floor or stock simulation</title>\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        f'<path fill="none" stroke="black" stroke-width="{diameter:.8f}" '
        f'stroke-linecap="round" d="{"".join(paths)}"/>\n</svg>\n'
    ).encode("ascii")


def resolve_design_setup(spec_path: Path, spec: dict) -> dict:
    """Replace a registry reference with exact settings and portable evidence."""
    if not isinstance(spec, dict) or not ({"setup", "setup_snapshot"} & spec.keys()):
        return spec
    from ..hardware_setups import SetupRegistry, parse_setup, resolve_cam_defaults

    if "setup" in spec and "setup_snapshot" in spec:
        raise ValueError("Choose a setup reference or a bundled setup snapshot")
    if "setup" in spec:
        reference = spec["setup"]
        _keys(reference, ("registry", "id"))
        registry = reference["registry"]
        setup_id = reference["id"]
        if not isinstance(registry, str) or not registry.strip() or Path(registry).anchor:
            raise ValueError("setup.registry must be relative to the design spec")
        if not isinstance(setup_id, str) or not setup_id.strip():
            raise ValueError("setup.id must identify a named setup record")
        record = SetupRegistry(spec_path.parent / registry).load(setup_id)
    else:
        record = parse_setup(spec["setup_snapshot"])
    settings = spec.get("settings")
    defaults = resolve_cam_defaults(record, spec.get("kind"), settings)
    resolved = dict(spec)
    resolved.pop("setup", None)
    resolved["setup_snapshot"] = record.to_dict()
    resolved["settings"] = dict(settings) | defaults
    return resolved


def build(spec_path: Path, output: Path) -> dict:
    """Compile a saved design spec; this module never attaches to a backend."""
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory")
    spec = resolve_design_setup(spec_path, json.loads(spec_path.read_text(encoding="utf-8-sig")))
    _keys(spec, ("schema_version", "concept", "kind", "settings"), ("source", "notes", "setup_snapshot"))
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    if not isinstance(spec["concept"], str) or not spec["concept"].strip():
        raise ValueError("concept must describe the intended design")
    if "notes" in spec and not isinstance(spec["notes"], str):
        raise ValueError("notes must be text")
    kind, settings = spec["kind"], spec["settings"]
    source = None
    source_bytes = None
    if kind in ("raster", "step-pocket", "step-profile"):
        if not isinstance(spec.get("source"), str) or not spec["source"].strip():
            raise ValueError(f"{kind} requires a source path relative to the spec")
        source = spec_path.parent / spec["source"]
        source_bytes = source.read_bytes()
    elif "source" in spec:
        raise ValueError("Plaque geometry is defined by its text settings; omit source")

    common = ("stock_thickness", "max_stepdown", "safe_z", "cut_feed", "plunge_feed", "spindle_rpm")
    cam = {}
    if kind == "raster":
        from ..ornament_cam import OrnamentSettings, generate_engraving

        required = [field.name for field in fields(OrnamentSettings)
                    if field.name not in ("optimize_paths", "approach_z")]
        _keys(settings, required, ("optimize_paths", "approach_z"))
        config = OrnamentSettings(**settings)
        gcode, cam, _ = generate_engraving(source, config)
        width = height = config.outer_diameter + 2 * config.stock_margin
        diameter, depth = config.effective_diameter, config.engraving_depth
    elif kind == "plaque":
        from ..plaque_engraver import generate_plaque_gcode

        design = ("title", "title_height", "width", "height", "margin", "border")
        _keys(settings, (*common, *design, "depth", "v_angle", "tip_diameter"),
              ("title_font", "subtitle", "subtitle_height", "subtitle_font"))
        depth = _number(settings, "depth")
        angle = _number(settings, "v_angle")
        tip = settings["tip_diameter"]
        if not 0 < angle < 180 or type(tip) not in (int, float) or not math.isfinite(tip) or tip < 0:
            raise ValueError("Provide a V-bit included angle below 180° and nonnegative tip diameter")
        if depth > _number(settings, "max_stepdown"):
            raise ValueError("Plaque engraving is single pass; depth must not exceed max_stepdown")
        if "subtitle" in settings and settings["subtitle"] and "subtitle_height" not in settings:
            raise ValueError("Set subtitle_height when using a subtitle")
        args = {k: v for k, v in settings.items() if k not in
                ("stock_thickness", "max_stepdown", "v_angle", "tip_diameter")}
        args["depth"] = -depth
        result = generate_plaque_gcode(**args)
        gcode, width, height = result.gcode, result.width, result.height
        diameter = tip + 2 * depth * math.tan(math.radians(angle / 2))
        cam = {"strokes": result.stroke_count, "passes": 1}
    elif kind in ("step-pocket", "step-profile"):
        from ..step_engraver import generate_step_gcode
        from ..step_geometry import load_step_isolated

        profile = kind == "step-profile"
        cut_fields = ("breakthrough", "tab_count", "tab_width", "tab_height") if profile else ("depth",)
        _keys(settings, (*common, "stock_width", "stock_height", "tool_diameter", *cut_fields))
        if source.suffix.lower() not in (".step", ".stp"):
            raise ValueError(f"{kind} requires a .step or .stp source")
        if profile:
            if type(settings["tab_count"]) is not int or settings["tab_count"] < 2:
                raise ValueError("A profile candidate requires at least two retention tabs")
            depth = _number(settings, "stock_thickness") + _number(settings, "breakthrough")
        else:
            depth = _number(settings, "depth")
        width, height = (_number(settings, k) for k in ("stock_width", "stock_height"))
        diameter = _number(settings, "tool_diameter")
        result = generate_step_gcode(
            load_step_isolated(source), mode="Profile cutout" if profile else "Pocket",
            zero_location="Center" if profile else "Lower-left", **(settings | {"depth": -depth}),
        )
        gcode = result.gcode
        cam = {"passes": result.passes, "operations": [asdict(op) for op in result.operations],
               "verification": asdict(result.verification) if result.verification else None,
               "stock_simulation": asdict(result.simulation) if result.simulation else None}
        if profile:
            cam["profile_simulation"] = asdict(result.profile_simulation) if result.profile_simulation else None
            cam["retention_tabs"] = {key: settings[key] for key in ("tab_count", "tab_width", "tab_height")}
    else:
        raise ValueError("kind must be plaque, raster, step-pocket or step-profile")

    if kind != "step-profile" and depth >= _number(settings, "stock_thickness"):
        raise ValueError("Depth must be less than stock_thickness; these templates do not cut through")
    if source is not None and source.read_bytes() != source_bytes:
        raise ValueError("Source changed during generation; retry with a stable file")
    # Bind the exact encoded output to the parser and preview. These generators
    # use absolute millimetres; plaque and STEP rely on the default G54 unless set.
    if kind != "raster":
        gcode = "G54\n" + gcode
    raw = ("(OFFLINE CANDIDATE - OPERATOR REVIEW REQUIRED)\n" + gcode).encode("ascii")
    program = parse_gcode(raw.decode("ascii"))
    validate_nonnegative_work_xy(program)
    clearance = _number(settings, "safe_z")
    validate_rapid_xy_clearance(program, clearance)
    if program.commands[-2:] != ("M5", "M2"):
        raise ValueError("Expected spindle stop and program end")
    levels = sorted({-s.end.z for s in program.segments if not s.rapid and s.end.z < 0})
    if (not levels or not math.isclose(levels[-1], depth, abs_tol=0.00005) or
            any(b - a > _number(settings, "max_stepdown") + 0.00005
                for a, b in zip([0, *levels], levels))):
        raise ValueError("Emitted depth or stepdown differs from the design limits")
    if any(min(s.start.x, s.end.x, s.start.y, s.end.y) < 0 for s in program.segments):
        raise ValueError("Motion crosses the lower-left work origin")
    if program.bounds.maximum.x > width or program.bounds.maximum.y > height:
        raise ValueError("Motion exceeds declared XY stock dimensions")
    radius = diameter / 2
    for s in program.segments:
        if s.rapid or min(s.start.z, s.end.z) >= 0:
            continue
        for pt in (s.start, s.end):
            if not radius - 1e-6 <= pt.x <= width - radius + 1e-6 or not (
                radius - 1e-6 <= pt.y <= height - radius + 1e-6
            ):
                raise ValueError("Cutter sweep exceeds the declared XY stock dimensions")

    bundled = dict(spec)
    files = {"candidate-review-only.nc": raw,
             "cutter-sweep.svg": _preview(program, width, height, diameter)}
    if source is not None:
        bundled["source"] = "source" + source.suffix.lower()
        files[bundled["source"]] = source_bytes
    files["design.json"] = _json(bundled)
    tool = ({"type": "Flat endmill", "diameter_mm": diameter} if kind in ("step-pocket", "step-profile") else
            {"type": "V-bit", "included_angle_deg": settings["v_angle"],
             "tip_diameter_mm": settings["tip_diameter"]})
    report = {
        "schema_version": 1, "status": "review-only", "kind": kind,
        "origin": "G54, lower-left stock XY, top surface Z0; millimetres",
        "tool": tool,
        "stock_mm": [width, height, settings["stock_thickness"]],
        "cut_depths_mm_below_top": levels, "surface_sweep_diameter_mm": diameter,
        "sha256": {name: _sha(data) for name, data in files.items()},
        "bounds": asdict(program.bounds), "motion": analyze_program(program), "cam": cam,
        "review": [
            "Check source geometry, footprint, stock, material, tool, zero and clamp clearance.",
            "Sweep shows the top-surface footprint, not floor finish or physical simulation.",
            "Runtime is nominal; acceleration and actual machine performance are not modeled.",
            "No machine configuration or physical readiness was checked.",
        ],
    }
    if "setup_snapshot" in spec:
        report["setup"] = spec["setup_snapshot"]
    if settings["spindle_rpm"] is None:
        report["review"].append("No spindle startup was specified.")
    files["report.json"] = _json(report)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        with (output / name).open("xb") as handle:
            handle.write(data)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="versioned design JSON")
    parser.add_argument("output", type=Path, help="new bundle directory")
    args = parser.parse_args(argv)
    try:
        report = build(args.spec, args.output)
    except (ValueError, TypeError, AttributeError, OSError, RuntimeError) as exc:
        parser.exit(2, f"CAM preparation rejected: {exc}\n")
    print(json.dumps({"status": report["status"], "bundle": str(args.output.resolve()),
                      "gcode_sha256": report["sha256"]["candidate-review-only.nc"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
