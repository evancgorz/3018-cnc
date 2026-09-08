from __future__ import annotations

import queue
import threading
import time

import pytest

from ttc3018_control.simulation.models import PlantSnapshot, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.runtime import SimulationRuntime
from ttc3018_control.simulation.supervisor import supervisor_main


class FakeConnection:
    def __init__(self, *messages, poll_values=None):
        self.messages = queue.Queue()
        for message in messages:
            self.messages.put(message)
        self.poll_values = iter(poll_values or [])
        self.sent = []
        self.closed = False

    def poll(self, *args):
        try:
            return next(self.poll_values)
        except StopIteration:
            return not self.messages.empty()

    def recv(self):
        return self.messages.get_nowait()

    def send(self, value):
        self.sent.append(value)

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, alive=False):
        self.alive = alive
        self.started = False
        self.terminated = False

    def start(self):
        self.started = True

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False


def test_supervisor_worker_handles_snapshots_stock_hazards_intents_and_stop():
    ready = FakeConnection()
    control = FakeConnection()
    incoming = queue.Queue()
    outgoing = queue.Queue()
    profile = SimulationProfile(stock_resolution=1)
    workpiece = SimulationWorkpiece(stock_width=8, stock_height=8, stock_thickness=3)
    first = PlantSnapshot(0, "Idle", (1, 1, 3), (0, 0, 0), 0, 5000, 5000).to_dict()
    second = PlantSnapshot(1, "Run", (1, 1, -1), (0, 0, 0), 100, 5000, 5000).to_dict()
    incoming.put({"type": "snapshot", "snapshot": first})
    incoming.put({"type": "snapshot", "snapshot": second})
    incoming.put({"type": "telemetry_overflow"})
    control.messages.put({"op": "scenario_intents", "intents": [{"name": "jog"}, "bad"]})
    thread = threading.Thread(target=supervisor_main, args=(ready, control, incoming, outgoing, profile.to_dict(), "token", workpiece.__dict__), daemon=True)
    thread.start()
    time.sleep(.25)
    control.messages.put({"op": "stop"})
    thread.join(2)
    assert not thread.is_alive()
    assert ready.sent == [{"version": 1, "token": "token", "role": "supervisor"}]
    items = []
    while True:
        try:
            items.append(outgoing.get_nowait())
        except queue.Empty:
            break
    assert any(item["type"] == "stock_metrics" for item in items)
    assert any(item["type"] == "hazard" for item in items)
    assert any(item["type"] == "intent" for item in items)


def test_supervisor_worker_translates_workpiece_into_machine_frame_for_wco_collision():
    ready = FakeConnection()
    control = FakeConnection()
    incoming = queue.Queue()
    outgoing = queue.Queue()
    profile = SimulationProfile(stock_resolution=1)
    workpiece = SimulationWorkpiece(stock_width=8, stock_height=8, stock_thickness=3)
    # The stock is defined at work-Z 0, while the machine is referenced at
    # machine-Z 30.  The descending spindle-off move must still interlock.
    first = PlantSnapshot(0, "Idle", (1, 1, 30), (0, 0, 30), 0, 0, 0).to_dict()
    second = PlantSnapshot(1, "Run", (1, 1, 27.5), (0, 0, 30), 100, 0, 0).to_dict()
    incoming.put({"type": "snapshot", "snapshot": first})
    incoming.put({"type": "snapshot", "snapshot": second})
    thread = threading.Thread(target=supervisor_main, args=(ready, control, incoming, outgoing, profile.to_dict(), "wco-token", workpiece.__dict__), daemon=True)
    thread.start()
    time.sleep(.25)
    control.messages.put({"op": "stop"})
    thread.join(2)
    assert not thread.is_alive()
    hazards = []
    while True:
        try:
            item = outgoing.get_nowait()
        except queue.Empty:
            break
        if item.get("type") == "hazard":
            hazards.append(item["hazard"]["kind"])
    assert "spindle_off_entry" in hazards


def test_supervisor_worker_detects_explicit_backend_operator_disagreement_without_deadlock():
    """An explicit backend empty verdict must not suppress the actor verdict."""
    ready = FakeConnection()
    control = FakeConnection()
    incoming = queue.Queue()
    outgoing = queue.Queue()
    profile = SimulationProfile()
    first = PlantSnapshot(1, "Idle", (1, 1, 3), (0, 0, 0), 0, 0, 0,
                          sequence=1).to_dict()
    second = PlantSnapshot(2, "Run", (profile.travel_x + 5, 1, 3), (0, 0, 0), 100, 0, 0,
                           sequence=2).to_dict()
    incoming.put({"type": "snapshot", "snapshot": first, "backend_hazards": []})
    # Deliberately claim that the backend saw no hazard even though the
    # independent actor must recompute a travel-limit hazard at this pose.
    incoming.put({"type": "snapshot", "snapshot": second, "backend_hazards": []})
    thread = threading.Thread(target=supervisor_main, args=(
        ready, control, incoming, outgoing, profile.to_dict(), "disagreement-token"), daemon=True)
    thread.start()
    time.sleep(.15)
    control.messages.put({"op": "stop"})
    thread.join(2)
    assert not thread.is_alive(), "disagreement handling must not deadlock the supervisor"
    items = []
    while True:
        try:
            items.append(outgoing.get_nowait())
        except queue.Empty:
            break
    hazards = [item["hazard"] for item in items if item.get("type") == "hazard"]
    assert any(item["kind"] == "travel_limit" for item in hazards)
    assert any(item["kind"] == "commanded_executed_divergence" for item in hazards)
    assert any(item.get("type") == "operator_intent"
               and item["intent"]["action"] == "interlock"
               and item["intent"]["hazard_kind"] == "commanded_executed_divergence"
               for item in items)


@pytest.mark.skipif(__import__("multiprocessing").get_start_method(allow_none=True) == "fork", reason="requires owned spawn workers")
def test_real_backend_fragmentation_reconnect_interlock_and_orderly_stop():
    runtime = SimulationRuntime()
    host, port = runtime.start(timeout=8)
    try:
        with __import__("socket").create_connection((host, port), timeout=2) as client:
            client.settimeout(2)
            assert b"Grbl" in client.recv(4096)
            client.sendall(b"G1 X")
            client.sendall(b"1 F600\n")
            response = client.recv(4096)
            if b"ok" not in response:
                response += client.recv(4096)
            assert b"ok" in response
            backend_snapshot = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and backend_snapshot is None:
                for item in runtime.poll():
                    if item.get("type") == "snapshot" and "backend_hazards" in item:
                        backend_snapshot = item
                        break
                if backend_snapshot is None:
                    time.sleep(.02)
            assert backend_snapshot is not None
            assert backend_snapshot["backend_hazards"] == []
            runtime._backend_control.send({"op": "interlock", "kind": "fixture"})
            assert b"ALARM:1" in client.recv(4096)
        # Backend accepts one reconnect after the first client closes.
        with __import__("socket").create_connection((host, port), timeout=2) as client:
            client.settimeout(2)
            assert b"Grbl" in client.recv(4096)
    finally:
        runtime.stop()


@pytest.mark.skipif(__import__("multiprocessing").get_start_method(allow_none=True) == "fork", reason="requires owned spawn workers")
def test_real_backend_and_operator_parity_on_wco_stock_entry():
    """The spawned backend verdict and independent actor agree through WCO."""
    workpiece = SimulationWorkpiece(stock_width=8, stock_height=8, stock_thickness=3)
    runtime = SimulationRuntime(profile=SimulationProfile(initial_z=33), workpiece=workpiece, speed="5x")
    host, port = runtime.start(timeout=8)
    try:
        with __import__("socket").create_connection((host, port), timeout=2) as client:
            client.settimeout(2)
            assert b"Grbl" in client.recv(4096)
            # Establish a non-zero Z WCO so the workpiece remains above the
            # machine's hard lower travel limit while work-Z enters stock.
            client.sendall(b"G10 L20 Z0\nG0 Z3\nG1 Z-1 F600\n")
            hazard_kinds = set()
            divergence = False
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                for item in runtime.poll():
                    if item.get("type") == "hazard":
                        kind = item["hazard"]["kind"]
                        hazard_kinds.add(kind)
                        divergence |= kind == "commanded_executed_divergence"
                if "spindle_off_entry" in hazard_kinds:
                    break
                time.sleep(.02)
            assert "spindle_off_entry" in hazard_kinds
            assert not divergence
    finally:
        runtime.stop()


@pytest.mark.skipif(__import__("multiprocessing").get_start_method(allow_none=True) == "fork", reason="requires owned spawn workers")
def test_production_boundary_homing_pins_and_estop_are_fail_closed():
    """Homing/limit declarations and E-stop telemetry cross the owned runtime."""
    from ttc3018_control.simulation.safety import EStopDefinition, EStopMode, HomingLimitProfile

    profile = HomingLimitProfile.default_3018("boundary")
    runtime = SimulationRuntime(homing_profile=profile,
                                estop_definition=EStopDefinition(mode=EStopMode.RESET_ONLY, reset_pin="R"))
    host, port = runtime.start(timeout=8)
    try:
        with __import__("socket").create_connection((host, port), timeout=2) as client:
            client.settimeout(2)
            client.recv(4096)
            client.sendall(b"$22=1\n$23=1\n$5=0\n$21=1\n$H\n")
            response = client.recv(4096)
            if b"ok" not in response:
                response += client.recv(4096)
            assert b"ok" in response
            runtime.set_limit_input("X", True)
            runtime.set_limit_input("Y", True)
            runtime.set_limit_input("Z", True)
            runtime.inject_estop(reset_asserted=True)
            deadline = time.monotonic() + 3
            safety = []
            while time.monotonic() < deadline and not safety:
                safety = [item for item in runtime.poll() if item.get("type") == "safety"]
                if not safety:
                    time.sleep(.02)
            assert safety
            assert runtime.estop_status["interlocked"]
            assert any(h.kind.value == "estop_latched" for h in runtime.hazards)
            client.sendall(b"G0 X1\n")
            assert b"ALARM:1" in client.recv(4096)
            runtime.release_estop()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and runtime.estop_status.get("active", True):
                runtime.poll()
                time.sleep(.02)
            client.sendall(b"$X\n")
            unlock = b""
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and b"ok" not in unlock:
                unlock += client.recv(4096)
            assert b"ok" in unlock
            runtime.acknowledge_estop(reference_trusted=True)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and runtime.estop_status["interlocked"]:
                runtime.poll()
                time.sleep(.02)
            assert not runtime.estop_status["interlocked"]
    finally:
        runtime.stop()


@pytest.mark.parametrize("mode", ["timeout", "mismatch"])
def test_runtime_parent_handshake_failures_clean_owned_children(mode):
    runtime = SimulationRuntime()

    class Context:
        def __init__(self):
            self.ready = FakeConnection()
            self.control = FakeConnection()
            self.calls = 0

        def Pipe(self, duplex=True):
            self.calls += 1
            if self.calls == 1:
                if mode == "timeout":
                    self.ready.poll_values = iter([False])
                else:
                    self.ready.poll_values = iter([True])
                    self.ready.messages.put({"version": 99, "token": "wrong"})
                return self.ready, None
            return self.control, None

        def Queue(self, maxsize=0):
            return queue.Queue(maxsize)

        def Process(self, *args, **kwargs):
            return FakeProcess()

    runtime.ctx = Context()
    with pytest.raises(RuntimeError, match="handshake"):
        runtime.start(timeout=0)
    assert not runtime.started and runtime.backend is None


def test_runtime_prestart_scenario_and_stop_paths():
    runtime = SimulationRuntime()
    assert runtime.poll() == ()
    with pytest.raises(RuntimeError):
        runtime.start_scenario([])
    runtime.stop()
    with pytest.raises(ValueError):
        SimulationRuntime(speed="bad")
    with pytest.raises(ValueError):
        SimulationRuntime(workpiece=SimulationWorkpiece(path="missing.step"))


def test_runtime_poll_interlock_dedup_and_dead_supervisor_fail_closed():
    runtime = SimulationRuntime()
    runtime.started = True
    runtime.supervisor = FakeProcess(alive=False)
    runtime._telemetry = queue.Queue()
    runtime._supervisor_in = queue.Queue(maxsize=1)
    runtime._supervisor_out = queue.Queue()
    runtime._backend_control = FakeConnection()
    runtime._supervisor_control = FakeConnection()
    runtime._telemetry.put({"type": "snapshot", "snapshot": {"value": 1}})
    runtime._supervisor_in.put("full")
    hazard = {"kind": "protocol", "message": "bad", "time_ns": 1,
              "position": (0, 0, 0), "severity": "alarm", "source": "supervisor"}
    runtime._supervisor_out.put({"type": "hazard", "hazard": hazard})
    runtime._supervisor_out.put({"type": "hazard", "hazard": hazard})
    runtime._supervisor_out.put({"type": "stock_metrics", "metrics": {"removed_volume": 1}})
    runtime._supervisor_out.put({"type": "heartbeat"})
    runtime.poll()
    assert runtime.stock_metrics == {"removed_volume": 1}
    # Replayed samples from one semantic incident are latched once; only a
    # clear edge can re-arm the same hazard key.
    assert len([item for item in runtime.hazards if item.kind.value == "protocol"]) == 1
    assert any(item.kind.value == "supervisor_unavailable" for item in runtime.hazards)
    assert runtime._backend_control.sent.count({"op": "interlock", "kind": "protocol"}) == 1
    runtime.stop()


def test_runtime_poll_bounds_live_queue_drain_for_ui_responsiveness():
    runtime = SimulationRuntime()
    runtime.started = True
    runtime.supervisor = FakeProcess(alive=True)
    runtime._telemetry = queue.Queue()
    runtime._supervisor_in = queue.Queue(maxsize=512)
    runtime._supervisor_out = queue.Queue()
    runtime._backend_control = FakeConnection()
    for index in range(runtime.MAX_EVENTS_PER_POLL + 50):
        runtime._telemetry.put({"type": "snapshot", "snapshot": {"value": index}})
    forwarded = runtime.poll()
    assert len(forwarded) == runtime.MAX_EVENTS_PER_POLL
    assert not runtime._telemetry.empty()
    runtime.stop()


def test_runtime_stop_uses_exact_owned_terminate_fallback():
    runtime = SimulationRuntime()
    runtime.backend = FakeProcess(alive=True)
    runtime.supervisor = FakeProcess(alive=True)
    runtime._backend_control = FakeConnection()
    runtime._supervisor_control = FakeConnection()
    runtime.stop(timeout=0)
    assert runtime.backend is None and runtime.supervisor is None
