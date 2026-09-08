from __future__ import annotations

import json
import multiprocessing as mp
import socket
import time

import pytest

from ttc3018_control.simulation.clock import SimulationClock
from ttc3018_control.simulation.controller import VirtualGrblController
from ttc3018_control.simulation.models import HazardKind, SimulationFault, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.plant import VirtualMachinePlant
from ttc3018_control.simulation.protocol import ProtocolError, parse_line
from ttc3018_control.simulation.runtime import SimulationRuntime
from ttc3018_control.simulation.trace import TraceRecorder, compare_traces
from ttc3018_control.grbl import Position


def test_profile_defaults_are_the_stated_3018_travel() -> None:
    profile = SimulationProfile.default_3018()
    profile.validate()
    assert (profile.travel_x, profile.travel_y, profile.travel_z) == (290.0, 170.0, 40.0)
    assert profile.safe_z == 30.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_profile_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError):
        SimulationProfile(travel_x=value).validate()


def test_clock_is_integer_and_speed_does_not_change_manual_time() -> None:
    clock = SimulationClock()
    assert clock.advance(123) == 123
    clock.set_speed("10x")
    assert clock.advance_wall(0.1) == 1_000_000_123
    clock.set_speed("uncapped")
    assert clock.advance_wall(100.0) == 1_000_000_123


def test_inbound_parser_is_independent_and_tolerates_comments() -> None:
    parsed = parse_line("g1 x1.25 f100 ; operator note")
    assert parsed.values("G") == (1.0,)
    assert parsed.values("X") == (1.25,)
    with pytest.raises(ProtocolError):
        parse_line("G1 Xoops")


def test_controller_ack_is_separate_from_motion_completion_and_status_is_consistent() -> None:
    plant = VirtualMachinePlant(SimulationProfile())
    controller = VirtualGrblController(plant)
    controller.receive(b"G90 G21 G1 X10 Y5 Z2 F600\n")
    assert controller.drain() == ("ok",)
    assert plant.busy
    first = plant.snapshot()
    assert first.machine_position == (0.0, 0.0, 0.0)
    plant.advance(2_000_000_000)
    final = plant.snapshot()
    assert final.machine_position == pytest.approx((10.0, 5.0, 2.0), abs=0.001)
    status = controller.status_line()
    assert "MPos:10.000,5.000,2.000" in status
    assert "WPos:10.000,5.000,2.000" in status


def test_controller_realtime_has_no_ack_and_hold_resume_reset_work() -> None:
    plant = VirtualMachinePlant(SimulationProfile())
    controller = VirtualGrblController(plant)
    controller.receive(b"G1 X100 F60\n!")
    assert controller.drain() == ("ok",)
    plant.advance(1_000_000_000)
    held = plant.snapshot().machine_position
    controller.receive(b"?")
    assert controller.drain()[0].startswith("<Hold")
    plant.advance(1_000_000_000)
    assert plant.snapshot().machine_position == held
    controller.receive(b"~")
    plant.advance(2_000_000_000)
    assert plant.snapshot().machine_position[0] > held[0]
    controller.receive(b"\x18")
    assert plant.state == "Idle"
    assert not plant.busy


def test_controller_accepts_incremental_grbl_jog_command() -> None:
    plant = VirtualMachinePlant(SimulationProfile(initial_x=5.0))
    controller = VirtualGrblController(plant)
    controller.receive(b"$J=G91 G21 X2 F600\n")
    assert controller.drain() == ("ok",)
    plant.advance(1_000_000_000)
    assert plant.machine_position == pytest.approx((7.0, 0.0, 0.0), abs=0.001)


def test_controller_relative_queue_uses_planner_endpoint() -> None:
    """Back-to-back relative jogs must be planned from the queued endpoint."""
    plant = VirtualMachinePlant(SimulationProfile())
    controller = VirtualGrblController(plant)

    controller.receive(b"$J=G91 G21 Z30 F500\n")
    controller.receive(b"$J=G91 G21 Z-20 F500\n")
    assert controller.drain() == ("ok", "ok")
    # The deterministic plant advances one queued block per scheduler tick;
    # drain both planner blocks explicitly.
    plant.advance(10_000_000_000)
    plant.advance(10_000_000_000)

    assert plant.state == "Idle"
    assert plant.machine_position == pytest.approx((0.0, 0.0, 10.0), abs=0.001)


def test_protocol_faults_are_deterministic_and_traceable() -> None:
    controller = VirtualGrblController(VirtualMachinePlant())
    controller.install_fault(SimulationFault("duplicate_ack", at_sequence=1))
    controller.receive(b"G1 X1 F60\n")
    assert controller.drain() == ("ok", "ok")
    controller.clear_faults()
    controller.install_fault(SimulationFault("delayed_ack", at_sequence=2, value="50"))
    controller.receive(b"G1 X2 F60\n")
    assert controller.drain() == ()
    controller.advance(49_000_000)
    assert controller.drain() == ()
    controller.advance(1_000_000)
    assert controller.drain() == ("ok",)


def test_malformed_status_fault_fails_closed() -> None:
    controller = VirtualGrblController(VirtualMachinePlant())
    controller.install_fault(SimulationFault("malformed_status"))
    assert controller.status_line() == "<Malformed digital-twin status"


def test_controller_wco_and_probe_report_are_geometry_driven() -> None:
    profile = SimulationProfile(initial_x=10.0, initial_y=20.0, initial_z=10.0)
    plant = VirtualMachinePlant(profile)
    plant.probe_surface_z = 4.0
    controller = VirtualGrblController(plant)
    controller.receive(b"G10 L20 P1 X2 Y3 Z4\n")
    assert controller.drain() == ("ok",)
    assert plant.work_offset == [8.0, 17.0, 6.0]
    controller.receive(b"?\n")
    status = controller.drain()[0]
    assert "MPos:10.000,20.000,10.000" in status
    assert "WPos:2.000,3.000,4.000" in status
    assert "WCO:8.000,17.000,6.000" in status
    controller.receive(b"G91 G38.2 Z-10 F60\n")
    assert controller.drain() == ("ok",)
    plant.advance(10_000_000_000)
    assert plant.machine_position[2] == pytest.approx(4.0, abs=0.001)
    assert any(line.startswith("[PRB:") for line in controller.drain())


def test_controller_reports_tool_length_offset_in_work_position() -> None:
    controller = VirtualGrblController(VirtualMachinePlant(SimulationProfile(initial_z=5.0)))
    controller.receive(b"G43.1 Z2\n")
    assert controller.drain() == ("[TLO:2.000]", "ok")
    controller.receive(b"?\n")
    status = controller.drain()[0]
    assert "MPos:0.000,0.000,5.000" in status
    assert "WPos:0.000,0.000,3.000" in status
    controller.receive(b"G49\n")
    assert controller.drain() == ("[TLO:0.000]", "ok")


def test_application_simulation_isolates_physical_work_zero_and_factories(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.work_zero_settings import SavedWorkZero, WorkZeroStore

    store = WorkZeroStore(tmp_path / "config" / "work-zero.json")
    store.save(SavedWorkZero(11, 12, 13))
    before = (tmp_path / "config" / "work-zero.json").read_bytes()
    physical_calls = []

    def forbidden():
        physical_calls.append(True)
        raise AssertionError("physical factory was constructed")

    controller = ApplicationController(tmp_path, usb_factory=forbidden, wifi_factory=forbidden)
    outcome = controller.connect_simulation()
    assert outcome.accepted
    try:
        controller._save_work_zero(Position(1, 2, 3))
        assert (tmp_path / "config" / "work-zero.json").read_bytes() == before
    finally:
        controller.disconnect()
    assert not physical_calls
    assert (tmp_path / "config" / "work-zero.json").read_bytes() == before


def test_application_controller_uses_normal_tcp_event_dispatch_for_twin(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    forbidden_calls: list[str] = []

    def forbidden():
        forbidden_calls.append("physical")
        raise AssertionError("physical factory was constructed")

    controller = ApplicationController(tmp_path, usb_factory=forbidden, wifi_factory=forbidden)
    assert controller.connect_simulation().accepted
    try:
        deadline = time.time() + 3
        while time.time() < deadline and controller.status is None:
            events = controller.transport_events()
            while not events.empty():
                controller.handle_transport_response(events.get_nowait().text)
            time.sleep(0.02)
        assert controller.status is not None
        assert controller.status.state == "Idle"
        assert controller.establish_reference().accepted
        assert controller.jog("X", 2, 600).accepted
        deadline = time.time() + 3
        while time.time() < deadline:
            controller.request_status()
            events = controller.transport_events()
            while not events.empty():
                controller.handle_transport_response(events.get_nowait().text)
            if controller.machine_position and controller.machine_position.x >= 1.999:
                break
            time.sleep(0.02)
        assert controller.machine_position is not None
        assert controller.machine_position.x == pytest.approx(2, abs=0.01)
    finally:
        controller.close()
    assert not forbidden_calls


def test_application_simulation_estop_invalidates_reference_and_work_zero(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.simulation.runtime import SimulationRuntime
    from ttc3018_control.simulation.safety import EStopDefinition, EStopMode

    controller = ApplicationController(
        tmp_path,
        simulation_factory=lambda: SimulationRuntime(
            estop_definition=EStopDefinition(mode=EStopMode.RESET_ONLY, reset_pin="R")))
    assert controller.connect_simulation().accepted
    try:
        deadline = time.time() + 3
        while time.time() < deadline and controller.status is None:
            while not controller.transport_events().empty():
                controller.handle_transport_response(controller.transport_events().get_nowait().text)
            time.sleep(.02)
        assert controller.establish_reference().accepted
        controller.session.work_zero_confirmed = True
        outcome = controller.inject_simulation_estop(reset_asserted=True)
        assert outcome.accepted
        deadline = time.time() + 3
        while time.time() < deadline and controller.reference_trusted:
            controller.poll_simulation()
            time.sleep(.02)
        assert not controller.reference_trusted
        assert not controller.work_zero_confirmed
        assert controller.release_simulation_estop().accepted
        assert not controller.acknowledge_simulation_estop().accepted
        assert controller.establish_reference().accepted
        assert controller.acknowledge_simulation_estop().accepted
    finally:
        controller.close()


def test_trace_round_trip_and_difference(tmp_path) -> None:
    trace = TraceRecorder()
    trace.record(0, "start", {"pid": 42, "port": 1234})
    trace.record(1, "ok")
    assert trace.digest()
    path = tmp_path / "trace-test.json"
    trace.export_json(path)
    assert json.loads(path.read_text())["events"][0]["payload"] == {}
    assert compare_traces(trace.events, trace.events) == ()


@pytest.mark.skipif(mp.get_start_method(allow_none=True) == "fork", reason="spawn contract is validated on Windows")
def test_runtime_starts_loopback_backend_and_supervisor_without_physical_transports() -> None:
    runtime = SimulationRuntime()
    host, port = runtime.start(timeout=8.0)
    try:
        assert host == "127.0.0.1"
        assert 0 < port < 65536
        with socket.create_connection((host, port), timeout=2.0) as client:
            client.settimeout(2.0)
            banner = client.recv(256).decode("utf-8", errors="replace")
            assert "Grbl 1.1h" in banner
            client.sendall(b"?\n")
            time.sleep(0.05)
            response = client.recv(4096).decode("utf-8", errors="replace")
            assert "<Idle" in response
        runtime.poll()
        assert runtime.supervisor is not None and runtime.supervisor.is_alive()
        runtime.start_scenario([{"name": "establish_reference", "arguments": {}}])
        deadline = time.time() + 2
        items = ()
        while time.time() < deadline and not any(item.get("type") == "intent" for item in items):
            time.sleep(0.05)
            items = runtime.poll()
        assert any(item.get("type") == "intent" for item in items)
    finally:
        runtime.stop()
    assert not runtime.started
    assert runtime.backend is None and runtime.supervisor is None


@pytest.mark.skipif(mp.get_start_method(allow_none=True) == "fork", reason="spawn contract is validated on Windows")
def test_runtime_supervisor_tracks_stock_metrics_in_an_owned_process() -> None:
    runtime = SimulationRuntime(
        profile=SimulationProfile(initial_z=0.0, stock_resolution=1.0),
        workpiece=SimulationWorkpiece(stock_width=12, stock_height=12, stock_thickness=5, origin_z=10),
        speed="10x",
    )
    host, port = runtime.start(timeout=8.0)
    try:
        with socket.create_connection((host, port), timeout=2.0) as client:
            client.settimeout(0.2)
            client.recv(4096)
            client.sendall(b"G90 G21 G1 Z10 F600\n")
            time.sleep(0.15)
            client.recv(4096)
            client.sendall(b"M3 S5000\nG1 Z8 F60\n")
            deadline = time.time() + 3
            while time.time() < deadline:
                runtime.poll()
                if runtime.stock_metrics and runtime.stock_metrics.get("removed_volume", 0) > 0:
                    break
                time.sleep(0.05)
        assert runtime.stock_metrics is not None
        assert runtime.stock_metrics["removed_volume"] > 0
        assert runtime.supervisor is not None and runtime.supervisor.is_alive()
    finally:
        runtime.stop()


@pytest.mark.skipif(mp.get_start_method(allow_none=True) == "fork", reason="spawn contract is validated on Windows")
def test_runtime_accepts_initial_faults_through_owned_loopback_boundary() -> None:
    runtime = SimulationRuntime(
        profile=SimulationProfile(initial_z=5.0),
        faults=[SimulationFault("reset_alarm", at_sequence=1)],
    )
    host, port = runtime.start(timeout=8.0)
    try:
        with socket.create_connection((host, port), timeout=2.0) as client:
            client.settimeout(1.0)
            client.recv(4096)
            client.sendall(b"G1 X1 F60\n")
            received = b""
            for _ in range(3):
                received += client.recv(4096)
                if b"ALARM:1" in received:
                    break
            assert b"ALARM:1" in received
        assert runtime.started
    finally:
        runtime.stop()


@pytest.mark.skipif(mp.get_start_method(allow_none=True) == "fork", reason="spawn contract is validated on Windows")
def test_runtime_translates_backend_fault_markers_to_one_bounded_interlock() -> None:
    runtime = SimulationRuntime(faults=[
        SimulationFault("telemetry_overflow", at_time_ns=0),
        SimulationFault("backend_heartbeat_loss", at_time_ns=0),
    ])
    host, port = runtime.start(timeout=8.0)
    try:
        with socket.create_connection((host, port), timeout=2.0) as client:
            client.settimeout(0.2)
            client.recv(4096)
            deadline = time.time() + 2.0
            while time.time() < deadline and not runtime.hazards:
                runtime.poll()
                time.sleep(0.02)
        assert len(runtime.hazards) == 1
        assert runtime.hazards[0].kind is HazardKind.SUPERVISOR_UNAVAILABLE
        kinds = [event.kind for event in runtime.trace.events]
        assert "fault" in kinds and "hazard" in kinds
    finally:
        runtime.stop()
