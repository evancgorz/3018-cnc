from __future__ import annotations

import queue
import threading
import time

from ttc3018_control.simulation.models import PlantSnapshot, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.public_scenarios import run_public_collision_lifecycle
from ttc3018_control.simulation.supervisor import supervisor_main


class _Connection:
    def __init__(self, *messages):
        self.messages = queue.Queue()
        for message in messages:
            self.messages.put(message)
        self.sent = []

    def poll(self, *_args):
        return not self.messages.empty()

    def recv(self):
        return self.messages.get_nowait()

    def send(self, value):
        self.sent.append(value)


def test_supervisor_latches_continuous_contact_and_rearms_after_clear():
    ready, control = _Connection(), _Connection()
    incoming, outgoing = queue.Queue(), queue.Queue()
    profile = SimulationProfile(stock_resolution=1)
    workpiece = SimulationWorkpiece(stock_width=8, stock_height=8, stock_thickness=3)
    first = PlantSnapshot(0, "Idle", (1, 1, 3), (0, 0, 0), 0, 0, 0).to_dict()
    contact = PlantSnapshot(1, "Run", (1, 1, -1), (0, 0, 0), 100, 0, 0).to_dict()
    still_contact = PlantSnapshot(2, "Run", (1, 1, -1), (0, 0, 0), 100, 0, 0).to_dict()
    clear = PlantSnapshot(3, "Idle", (1, 1, 3), (0, 0, 0), 0, 0, 0).to_dict()
    incoming.put({"type": "snapshot", "snapshot": first})
    incoming.put({"type": "snapshot", "snapshot": contact})
    incoming.put({"type": "snapshot", "snapshot": still_contact})
    incoming.put({"type": "snapshot", "snapshot": clear})
    incoming.put({"type": "snapshot", "snapshot": contact | {"time_ns": 4}})
    thread = threading.Thread(
        target=supervisor_main,
        args=(ready, control, incoming, outgoing, profile.to_dict(), "latch", workpiece.__dict__),
        daemon=True,
    )
    thread.start()
    time.sleep(0.25)
    control.messages.put({"op": "stop"})
    thread.join(2)
    hazards = []
    clears = []
    while True:
        try:
            item = outgoing.get_nowait()
        except queue.Empty:
            break
        if item.get("type") == "hazard":
            hazards.append(item["hazard"]["kind"])
        elif item.get("type") == "hazard_clear":
            clears.append(tuple(item["key"]))
    assert hazards.count("spindle_off_entry") == 2
    assert clears


def test_public_controller_collision_lifecycle_isolated_and_exported(tmp_path):
    result = run_public_collision_lifecycle(tmp_path, tmp_path / "evidence" / "collision.json")
    assert result.passed, result.failure
    assert result.startup_hazard_count == 0
    assert result.incident_count == 1
    assert result.final_job_state == "failed"
    assert result.work_offset is not None and result.work_offset.z == 30.0
    assert result.physical_factory_calls == 0
    assert result.cleanup_complete
    assert (tmp_path / "evidence" / "collision.json").exists()
    assert (tmp_path / "evidence" / "collision.md").exists()


def test_public_controller_collision_lifecycle_replays_same_semantic_result(tmp_path):
    one = run_public_collision_lifecycle(tmp_path / "one", tmp_path / "one" / "evidence.json")
    two = run_public_collision_lifecycle(tmp_path / "two", tmp_path / "two" / "evidence.json")
    assert one.passed and two.passed
    assert (
        one.startup_hazard_count,
        one.incident_count,
        one.incident_kinds,
        one.final_job_state,
        one.work_offset,
    ) == (
        two.startup_hazard_count,
        two.incident_count,
        two.incident_kinds,
        two.final_job_state,
        two.work_offset,
    )
