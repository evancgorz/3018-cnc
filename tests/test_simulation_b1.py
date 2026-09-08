from __future__ import annotations

import socket
import time

import pytest

from ttc3018_control.simulation import (
    BoundaryTraceFailure,
    BoundaryTraceState,
    ProbeBoundary,
    ProbeBoundaryTraceWorkflow,
    SimulationProfile,
    VirtualGrblController,
    VirtualMachinePlant,
)
from ttc3018_control.simulation.runtime import SimulationRuntime


def _boundary() -> ProbeBoundary:
    return ProbeBoundary(((2.0, 2.0), (8.0, 2.0), (8.0, 8.0), (2.0, 8.0)))


def _probe(start: tuple[float, float, float], command: bytes, expected: tuple[float, float, float]) -> tuple[VirtualGrblController, tuple[str, ...]]:
    plant = VirtualMachinePlant(SimulationProfile(initial_x=start[0], initial_y=start[1], initial_z=start[2]))
    controller = VirtualGrblController(plant)
    controller.configure_probe_boundary(_boundary())
    controller.receive(command)
    assert controller.drain() == ("ok",)
    plant.advance(10_000_000_000)
    responses = controller.drain()
    assert plant.machine_position == pytest.approx(expected, abs=0.001)
    return controller, responses


def test_polygon_probe_first_contact_forward_reverse_and_diagonal() -> None:
    _, forward = _probe((5.0, 5.0, 10.0), b"G91 G38.2 X10 F60\n", (8.0, 5.0, 10.0))
    assert "[PRB:8.000,5.000,10.000:1]" in forward
    _, reverse = _probe((5.0, 5.0, 10.0), b"G91 G38.2 X-10 F60\n", (2.0, 5.0, 10.0))
    assert "[PRB:2.000,5.000,10.000:1]" in reverse
    _, diagonal = _probe((5.0, 5.0, 10.0), b"G91 G38.2 X10 Y10 F60\n", (8.0, 8.0, 10.0))
    assert "[PRB:8.000,8.000,10.000:1]" in diagonal


def test_polygon_probe_no_contact_and_malformed_boundary_fail_closed() -> None:
    _, responses = _probe((5.0, 5.0, 10.0), b"G91 G38.2 X1 F60\n", (6.0, 5.0, 10.0))
    assert any(line.endswith(":0]") for line in responses)
    assert "ALARM:5" in responses
    with pytest.raises(ValueError):
        ProbeBoundary.from_dict({"vertices": [[0, 0], [1, 1], [0, 1], [1, 0]]})
    with pytest.raises(ValueError):
        ProbeBoundary.from_dict({"vertices": [[0, 0], [1, 0]]})


def test_boundary_trace_correlates_reports_and_never_offsets_on_failure() -> None:
    trace = ProbeBoundaryTraceWorkflow()
    assert trace.start(boundary=_boundary(), seed=(5.0, 5.0, 10.0), envelope=(20.0, 20.0, 40.0),
                       reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                       probe_input_open=True)
    expected = ((8.0, 5.0, 10.0), (5.0, 8.0, 10.0), (2.0, 5.0, 10.0), (5.0, 2.0, 10.0))
    index = 0
    while trace.state is BoundaryTraceState.SEARCHING:
        command = trace.next_command()
        assert command is not None
        assert trace.handle_response("ok")
        if command.startswith("G38.2"):
            point = expected[index]
            index += 1
            assert trace.handle_response(f"[PRB:{point[0]:.3f},{point[1]:.3f},{point[2]:.3f}:1]")
    assert trace.state is BoundaryTraceState.COMPLETE
    assert trace.result is not None and len(trace.result.contacts) == 4
    replay = ProbeBoundaryTraceWorkflow()
    assert replay.start(boundary=_boundary(), seed=(5.0, 5.0, 10.0), envelope=(20.0, 20.0, 40.0),
                        reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                        probe_input_open=True)
    assert replay.commands == trace.commands

    contradictory = ProbeBoundaryTraceWorkflow()
    assert contradictory.start(boundary=_boundary(), seed=(5.0, 5.0, 10.0), envelope=(20.0, 20.0, 40.0),
                               reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                               probe_input_open=True)
    command = contradictory.next_command()
    assert command is not None
    assert contradictory.handle_response("ok")
    while not command.startswith("G38.2"):
        command = contradictory.next_command()
        assert command is not None
        assert contradictory.handle_response("ok")
    assert contradictory.handle_response("[PRB:8.000,5.000,10.000:1]")
    # A reverse-X contact reported in the +Y slot is edge-valid but violates
    # the deterministic outward order and must not close the trace.
    command = contradictory.next_command()
    assert command is not None
    assert contradictory.handle_response("ok")
    while not command.startswith("G38.2"):
        command = contradictory.next_command()
        assert command is not None
        assert contradictory.handle_response("ok")
    assert not contradictory.handle_response("[PRB:2.000,5.000,10.000:1]")
    assert contradictory.failure_code is BoundaryTraceFailure.CONTRADICTORY

    failed = ProbeBoundaryTraceWorkflow()
    assert failed.start(boundary=_boundary(), seed=(5.0, 5.0, 10.0), envelope=(20.0, 20.0, 40.0),
                        reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                        probe_input_open=True)
    assert not failed.handle_response("[PRB:5.000,5.000,10.000:1]")
    assert failed.failure_code is BoundaryTraceFailure.STALE_REPORT
    assert failed.result is None


def test_boundary_trace_guards_seed_and_probe_input() -> None:
    trace = ProbeBoundaryTraceWorkflow()
    assert not trace.start(boundary=_boundary(), seed=(1.0, 1.0, 10.0), envelope=(20.0, 20.0, 40.0),
                            reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                            probe_input_open=True)
    assert trace.failure_code is BoundaryTraceFailure.SEED_OUTSIDE
    guarded = ProbeBoundaryTraceWorkflow()
    assert not guarded.start(boundary=_boundary(), seed=(5.0, 5.0, 10.0), envelope=(20.0, 20.0, 40.0),
                              reference_trusted=True, controller_idle=True, spindle_rpm=100.0,
                              probe_input_open=False, supervisor_healthy=False)
    assert guarded.failure_code is BoundaryTraceFailure.GUARD


def test_polygon_probe_loopback_backend_and_supervisor_configuration() -> None:
    runtime = SimulationRuntime(
        profile=SimulationProfile(initial_x=5.0, initial_y=5.0, initial_z=10.0),
        speed="uncapped", probe_boundary=_boundary(),
    )
    endpoint = runtime.start()
    sock = socket.create_connection(endpoint, timeout=2.0)
    sock.settimeout(0.1)
    try:
        startup = bytearray()
        startup_deadline = time.monotonic() + 2.0
        while time.monotonic() < startup_deadline and b"Digital twin" not in startup:
            try:
                startup.extend(sock.recv(4096))
            except TimeoutError:
                continue
        assert b"Digital twin" in startup
        sock.sendall(b"G91 G38.2 X10 F60\n")
        data = bytearray()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and b"[PRB:" not in data:
            try:
                data.extend(sock.recv(4096))
            except TimeoutError:
                continue
        assert b"[PRB:8.000,5.000,10.000:1]" in data
        assert runtime.backend is not None and runtime.backend.is_alive()
        assert runtime.supervisor is not None and runtime.supervisor.is_alive()
    finally:
        sock.close()
        runtime.stop()
    assert runtime.backend is None and runtime.supervisor is None
