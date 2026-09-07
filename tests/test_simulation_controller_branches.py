from __future__ import annotations

import pytest

from ttc3018_control.application.job_service import JobService
from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.grbl import GrblStatus
from ttc3018_control.simulation.controller import VirtualGrblController
from ttc3018_control.simulation.models import SimulationFault, SimulationProfile
from ttc3018_control.simulation.plant import VirtualMachinePlant
from ttc3018_control.simulation.protocol import ParsedLine, ProtocolError, parse_line


def make_controller(**kwargs):
    profile = SimulationProfile(**kwargs)
    return VirtualGrblController(VirtualMachinePlant(profile))


def send(controller, command: str):
    controller.receive((command + "\n").encode())
    return controller.drain()


def test_input_types_overflow_and_all_realtime_bytes():
    controller = make_controller(rx_capacity=32)
    with pytest.raises(TypeError):
        controller.receive("G1 X1")
    controller.receive(b"X" * 40)
    assert "error:11" in controller.drain()
    controller.receive(b"\n")
    controller.receive(b"G1 X1 F60\n")
    assert "ok" in controller.drain()
    controller.receive(b"?")
    assert controller.drain()[0].startswith("<")
    controller.receive(b"!")
    assert controller.plant.hold_requested
    controller.receive(b"~")
    assert not controller.plant.hold_requested
    controller.receive(b"\x85")
    controller.receive(b"\x18")
    assert "Grbl 1.1h ['$' for help]" in controller.drain()


def test_fragmented_line_and_realtime_interleave_preserve_order_and_status():
    controller = make_controller()
    controller.receive(b"G1 X")
    assert controller.drain() == ()
    controller.receive(b"?!")
    realtime = controller.drain()
    assert realtime[0].startswith("<Idle")
    assert controller.plant.hold_requested
    controller.receive(b"1 F60 ; trailing comment\n")
    assert controller.drain() == ("ok",)
    assert len(controller.plant.queue) == 1


def test_alarm_requires_unlock_and_soft_reset_restores_modal_state():
    controller = make_controller()
    controller.plant.position[0] = controller.plant.profile.travel_x + 1
    controller.plant._check_limits()
    assert controller.alarm and controller.plant.state == "Alarm"
    assert controller.drain() == ("ALARM:1",)
    assert send(controller, "G1 X1 F60") == ("ALARM:1",)
    assert not controller.plant.busy
    assert send(controller, "$X ; unlock comment") == ("ok",)
    assert controller.plant.state == "Idle" and not controller.alarm
    assert send(controller, "G91") == ("ok",)
    controller.receive(b"\x18")
    assert controller.drain() == ("Grbl 1.1h ['$' for help]",)
    assert send(controller, "$G")[0].startswith("[GC:G21 G0")


def test_system_queries_settings_and_system_errors():
    controller = make_controller()
    assert controller.boot()[0].startswith("Grbl")
    assert any(item.startswith("$130=") for item in send(controller, "$$"))
    assert send(controller, "$I") == ("[VER:1.1h.digital-twin]", "[OPT:V,15,128]", "ok")
    assert send(controller, "$G")[0].startswith("[GC:G21")
    assert send(controller, "$#")[0].startswith("[G54:")
    assert send(controller, "$X") == ("ok",)
    assert send(controller, "$H") == ("ok",)
    assert send(controller, "$6=1") == ("ok",)
    for bad in ("$6=-1", "$999=1", "$foo", "$6=nan"):
        assert send(controller, bad)[0].startswith("error:1")
    assert send(controller, "$J=G91 G21 F120 X1")[0] == "ok"
    assert send(controller, "$J=G91 G21 X1")[0] == "ok"
    with pytest.raises(ProtocolError):
        controller._system("$J=G91 Xoops")


def test_modal_g_m_inventory_and_invalid_feed():
    controller = make_controller()
    for command in ("G17", "G21", "G90", "G91", "G94", "G54", "G40", "G49", "G43.1 Z2", "G80", "G4 P1"):
        result = send(controller, command)
        assert result[-1] == "ok"
    assert send(controller, "M3 S2500") == ("ok",)
    assert send(controller, "M4") == ("ok",)
    assert send(controller, "M5") == ("ok",)
    assert send(controller, "M0") == ("ok",)
    assert send(controller, "M1") == ("ok",)
    assert send(controller, "M2") == ("ok",)
    assert send(controller, "M30") == ("ok",)
    assert send(controller, "G1 X1 F0")[0].startswith("error:1")
    assert send(controller, "G20")[0].startswith("error:1")
    assert send(controller, "G99")[0].startswith("error:1")
    assert send(controller, "M99")[0].startswith("error:1")


def test_arcs_both_directions_zero_radius_and_partial_offsets():
    controller = make_controller(initial_x=10, initial_y=0)
    assert send(controller, "G90 G3 X0 Y0 I-5 J0 F100") == ("ok",)
    controller.plant.advance(10_000_000_000)
    assert send(controller, "G2 X10 Y0 I5 J0 F100") == ("ok",)
    assert send(controller, "G2 X11 Y0 F100")[0].startswith("error:1")
    assert send(controller, "G10 L20 P1 X3")[0] == "ok"
    assert controller.plant.work_offset == [-3.0, 0.0, 0.0]
    assert send(controller, "G10 L10 X1")[0].startswith("error:1")
    assert send(controller, "G10 L20 P1")[0] == "ok"


def test_probe_miss_and_limit_alarm_pin_and_buffer_reporting():
    controller = make_controller(initial_z=10, planner_capacity=2)
    controller.plant.probe_surface_z = None
    assert send(controller, "G91 G38.2 Z-1 F60") == ("ok",)
    controller.plant.advance(10_000_000_000)
    assert any(line.startswith("[PRB:") and line.endswith(":0]") for line in controller.drain())
    controller.plant.pins = "X"
    assert "Pn:X" in controller.status_line()
    controller.receive(b"G1 X999 F60\n")
    controller.plant.position[0] = 999
    controller.plant._check_limits()
    assert controller.alarm
    assert any(line.startswith("ALARM") for line in controller.drain())
    assert "Bf:" in controller.status_line()


def test_planner_backpressure_defers_motion_ack_and_keeps_realtime_responsive():
    controller = make_controller(planner_capacity=2)

    controller.receive(b"G1 X1 F60\nG1 X2 F60\nG1 X3 F60\n")
    assert controller.drain() == ("ok", "ok")
    assert len(controller._deferred_lines) == 1
    assert len(controller.plant.queue) + (1 if controller.plant.active is not None else 0) <= 2

    controller.receive(b"?!")
    realtime = controller.drain()
    assert any(line.startswith("<Run") for line in realtime)
    assert controller.plant.hold_requested
    controller.receive(b"~")
    assert not controller.plant.hold_requested

    controller.advance(2_000_000_000)
    assert controller.drain() == ("ok",)
    assert len(controller.plant.queue) + (1 if controller.plant.active is not None else 0) <= 2


def test_reset_clears_deferred_motion_without_acknowledging_it():
    controller = make_controller(planner_capacity=1)
    controller.receive(b"G1 X1 F60\nG1 X2 F60\n")
    assert controller.drain() == ("ok",)
    assert controller._deferred_lines

    controller.receive(b"\x18")
    assert controller.drain() == ("Grbl 1.1h ['$' for help]",)
    controller.advance(5_000_000_000)
    assert controller.drain() == ()
    assert not controller._deferred_lines
    assert controller.plant.state == "Idle"


def test_streaming_waits_for_authoritative_idle_and_controls_final_drain():
    controller = make_controller(planner_capacity=2)
    service = JobService(MachineSession(), controller.receive, controller.receive)
    commands = tuple(f"G1 X{index} F60" for index in range(1, 21))

    assert service.start(commands).accepted

    def pump_responses() -> None:
        while True:
            responses = controller.drain()
            if not responses:
                return
            for response in responses:
                service.handle_response(response)

    pump_responses()
    assert service.state == "running"
    assert service.active

    for _ in range(40):
        controller.advance(1_000_000_000)
        pump_responses()
        if service.state == "complete":
            break

    assert service.state == "complete"
    assert service.active
    assert controller.plant.busy
    assert service.display_state == "draining"

    service.observe_status(GrblStatus("Run"))
    assert service.pause().accepted
    assert service.display_state == "paused"
    assert controller.plant.hold_requested

    service.observe_status(GrblStatus("Hold"))
    assert service.resume().accepted
    assert service.display_state == "draining"
    assert not controller.plant.hold_requested
    service.observe_status(GrblStatus("Run"))


def test_alarm_during_final_controller_drain_fails_completed_stream():
    realtime: list[bytes] = []
    service = JobService(MachineSession(), lambda _command: None, realtime.append)
    assert service.start(("G1 X1 F60",)).accepted
    assert service.handle_response("ok")
    assert service.state == "complete"
    assert service.active

    service.observe_status(GrblStatus("Alarm"))

    assert service.state == "failed"
    assert service.restart_requires_reload
    assert realtime[-2:] == [b"!", b"\x18"]


@pytest.mark.parametrize("fault", ["missing_ack", "error", "error_ack"])
def test_ack_faults(fault):
    controller = make_controller()
    controller.install_fault(SimulationFault(fault, at_sequence=1))
    response = send(controller, "G1 X1 F60")
    if fault == "missing_ack":
        assert response == ()
    else:
        assert response[0].startswith("error:")


def test_delayed_and_duplicate_ack_and_fault_lifecycle():
    controller = make_controller()
    controller.install_fault(SimulationFault("duplicate_ack", at_sequence=1))
    assert send(controller, "G1 X1 F60") == ("ok", "ok")
    controller.clear_faults()
    controller.install_fault(SimulationFault("delayed_ack", at_sequence=2, value="bad"))
    assert send(controller, "G1 X2 F60") == ()
    controller.advance(100_000_000)
    assert controller.drain() == ("ok",)
    with pytest.raises(TypeError):
        controller.install_fault("bad")


def test_protocol_parser_word_and_line_failures():
    assert parse_line("[ESP:SETUP]").raw.startswith("[ESP")
    for raw in (b"bad", "", "G1 Q1", "G1 Xnan", "G1 X1 ???"):
        with pytest.raises((ProtocolError, TypeError)):
            parse_line(raw)
    controller = make_controller()
    assert send(controller, "[ESP:WIFI]") == ("ok", "ok")
    assert send(controller, "G1 X1 ;comment")[0] == "ok"
    assert send(controller, "G10 X1")[0].startswith("error:1")
