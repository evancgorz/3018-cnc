from pathlib import Path

import pytest

from ttc3018_control.agent_cam import build
from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.cam_sequence import create, inspect
from ttc3018_control.simulation.controller import VirtualGrblController
from ttc3018_control.simulation.models import SimulationProfile
from ttc3018_control.simulation.plant import VirtualMachinePlant


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "agent-cam"


def test_review_sequence_preserves_exact_files_and_guarded_twin_handoff(tmp_path):
    build(EXAMPLES / "sequence-engraving.json", tmp_path / "engraving")
    build(EXAMPLES / "step-profile.json", tmp_path / "cutout")
    reports = ["engraving/report.json", "cutout/report.json"]
    manifest = tmp_path / "sequence.json"
    with pytest.raises(ValueError, match="final pass"):
        create(manifest, "Plate fixture, lower-left of stock", reports[::-1])
    sequence = create(manifest, "Plate fixture, lower-left of stock", reports)
    assert inspect(manifest) == sequence
    assert [stage["tool"]["type"] for stage in sequence["passes"]] == ["V-bit", "Flat endmill"]

    app = ApplicationController(tmp_path / "machine")
    for stage in sequence["passes"]:
        program = app.load_program(tmp_path / stage["report"])
        assert program.source_sha256 == stage["program_sha256"]
        assert not app.authorize_job_start(
            review_acknowledged=True, physical_preflight_confirmed=True
        ).accepted

        # Each tool has its own Z setup in the simulation. The same XY
        # frame is retained while the exact pass is played to the controller.
        plant = VirtualMachinePlant(SimulationProfile(initial_z=6.0))
        controller = VirtualGrblController(plant)
        controller.receive(b"G10 L20 P1 Z0\n")
        assert "ok" in controller.drain()
        for command in program.commands:
            controller.receive((command + "\n").encode("ascii"))
            responses = controller.drain()
            assert "ok" in responses, (command, responses)
            controller.advance(30_000_000_000)
            assert not any(line.startswith(("ALARM", "error")) for line in controller.drain())
        assert tuple(plant.work_offset[:2]) == (0.0, 0.0)
        assert plant.spindle_rpm == 0

    (tmp_path / "cutout" / "cutter-sweep.svg").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="cutter-sweep.svg"):
        inspect(manifest)
