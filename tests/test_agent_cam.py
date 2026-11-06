import hashlib
import json
from pathlib import Path

import pytest

from ttc3018_control.agent_cam import build
from ttc3018_control.gcode import load_gcode

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "agent-cam"


@pytest.mark.parametrize(("kind", "depths"), [
    ("plaque", [0.2]),
    ("raster", [0.25, 0.3]),
    ("step-pocket", [0.25, 0.5]),
])
def test_example_bundles_are_reproducible_and_hash_exact_bytes(tmp_path, kind, depths):
    output = tmp_path / "first"
    report = build(EXAMPLES / f"{kind}.json", output)
    assert report["status"] == "review-only"
    assert report["cut_depths_mm_below_top"] == depths
    program = load_gcode(output / "candidate-review-only.nc")
    assert "G54" in program.commands[0].split()
    assert program.commands[-2:] == ("M5", "M2")
    assert program.bounds.minimum.z == -depths[-1]
    assert '<path fill="none"' in (output / "cutter-sweep.svg").read_text()

    replay = tmp_path / "replay"
    build(output / "design.json", replay)
    for name, expected in report["sha256"].items():
        data = (output / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected
        assert (replay / name).read_bytes() == data
    with pytest.raises(ValueError, match="already exists"):
        build(EXAMPLES / f"{kind}.json", output)


def test_unknown_stock_thickness_and_unverified_pass_are_rejected(tmp_path):
    spec = json.loads((EXAMPLES / "plaque.json").read_bytes())
    path = tmp_path / "design.json"
    output = tmp_path / "out"
    spec["settings"].pop("stock_thickness")
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="stock_thickness"):
        build(path, output)
    spec["settings"].update(stock_thickness=6, max_stepdown=0.1)
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="single pass"):
        build(path, output)
    assert not output.exists()


def test_rejects_cutter_overhang_even_when_centerline_fits(tmp_path):
    spec = json.loads((EXAMPLES / "plaque.json").read_bytes())
    spec["settings"]["tip_diameter"] = 12
    path = tmp_path / "design.json"
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="Cutter sweep"):
        build(path, tmp_path / "out")


def test_bundle_uses_guarded_job_loader_and_preserves_loaded_job_on_failure(tmp_path):
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.gcode import GCodeError

    bundle = tmp_path / "bundle"
    report = build(EXAMPLES / "plaque.json", bundle)
    manifest = bundle / "report.json"
    app = ApplicationController(tmp_path / "machine")
    expected = app.load_program(bundle / "candidate-review-only.nc")

    # Older C-096 manifests did not include the structured tool field.
    report.pop("tool")
    manifest.write_text(json.dumps(report), encoding="utf-8")
    actual = app.load_program(manifest)
    assert actual == expected
    provenance = app.program_provenance
    assert provenance["report_state"] == "matched"
    assert any("75 × 35 × 6" in line for line in provenance["details"])

    (bundle / "design.json").write_text("{}", encoding="utf-8")
    with pytest.raises(GCodeError, match="design.json"):
        app.load_program(manifest)
    assert app.job.program is actual
