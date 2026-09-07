from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.z_touch_plate import ZTouchPlateRecord


class Transport:
    connected = True

    def __init__(self):
        self.sent = []

    def send_line(self, command, display_text=None):
        self.sent.append(command)

    def send_realtime(self, command):
        pass

    def disconnect(self):
        self.connected = False

    @property
    def events(self):
        return []


def test_visible_z_plate_save_preserves_hidden_capabilities(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    assert controller.save_capabilities(
        limit_switches=True, z_plate=False, tool_setter=True,
        movable_xyz=True, fixed_fixture=True,
    ).accepted
    before = controller.machine_definition.probes

    assert controller.save_z_plate_capability(True).accepted
    after = controller.machine_definition.probes

    assert {probe.kind for probe in after} == {probe.kind for probe in before} | {next(
        probe.kind for probe in after if probe.kind.value == "movable_z_plate"
    )}
    for kind in ("fixed_tool_setter", "movable_xyz", "fixed_xyz"):
        assert next(probe for probe in after if probe.kind.value == kind) == next(
            probe for probe in before if probe.kind.value == kind
        )


def test_z_probe_updates_only_z_offset_and_requires_removal_ack(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    assert controller.save_z_plate_capability(True).accepted
    assert controller.save_z_touch_plate_settings(
        plate_thickness=1.5, active_low=False, fast_feed=100, slow_feed=25,
        max_search=5, retract=1, safe_retract=2, tolerance=0.05,
    ).accepted
    transport = Transport()
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 0), work_offset=Position(5, 6, 7)))
    assert controller.establish_reference().accepted
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 20), work_offset=Position(5, 6, 7)))
    controller.session.work_zero_confirmed = True
    record = ZTouchPlateRecord.commissioned_record(
        controller.machine_id or "", (1.0, 1.01, 1.02), 0.05,
        controller.z_touch_plate_fingerprint,
    )
    controller.z_touch_plate_store.save(record)
    controller._z_touch_plate_record = record

    assert controller.probe_work_z().accepted
    assert transport.sent[-1] == b"G91 G21 G38.2 Z-5 F100\n"
    controller.handle_response("[PRB:0,0,15:1]")
    controller.handle_response("ok")
    controller.handle_response("ok")
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 19), pins=""))
    controller.handle_response("[PRB:0,0,15:1]")
    controller.handle_response("ok")
    assert transport.sent[-1] == b"G10 L20 P1 Z1.5\n"
    controller.handle_response("ok")
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 15), work_offset=Position(5, 6, 13.5)))
    controller.handle_response("ok")

    assert any(command == b"G10 L20 P1 Z1.5\n" for command in transport.sent)
    assert not any(command.startswith(b"G10") and b"X" in command for command in transport.sent)
    assert controller.z_touch_plate_status == "remove_plate"
    assert controller.acknowledge_z_touch_plate_removed().accepted


def test_connected_plate_polarity_save_applies_grbl_setting_six(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    assert controller.save_z_plate_capability(True).accepted
    transport = Transport()
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 0)))

    outcome = controller.save_z_touch_plate_settings(
        plate_thickness=19.37, active_low=True, fast_feed=100, slow_feed=25,
        max_search=5, retract=2, safe_retract=2, tolerance=0.05,
    )

    assert outcome.accepted
    assert transport.sent[-1] == b"$6=1\n"
    assert controller.z_touch_plate_definition.active_low


def test_connected_idle_allows_machine_capability_changes(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    transport = Transport()
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 0)))

    outcome = controller.save_capabilities(
        limit_switches=False, z_plate=True, tool_setter=False,
        movable_xyz=False, fixed_fixture=False,
    )

    assert outcome.accepted
    assert controller.z_touch_plate_definition is not None


def test_connected_non_idle_blocks_machine_capability_changes(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    transport = Transport()
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Run", Position(0, 0, 0)))

    outcome = controller.save_z_plate_capability(True)

    assert not outcome.accepted
    assert "must be Idle" in outcome.message


def test_three_supervised_samples_complete_commissioning_automatically(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    assert controller.save_z_plate_capability(True).accepted
    transport = Transport()
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 0), work_offset=Position(0, 0, 0)))
    assert controller.establish_reference().accepted
    controller.apply_status(GrblStatus("Idle", Position(0, 0, 20), work_offset=Position(0, 0, 0)))
    definition = controller.z_touch_plate_definition
    controller._z_touch_plate_record = ZTouchPlateRecord(
        controller.machine_id or "", (), definition.tolerance,
        controller.z_touch_plate_fingerprint, input_tested=True,
    )

    for sample_index, trigger_z in enumerate((15.0, 15.01, 15.02), start=1):
        assert controller.start_z_touch_plate_commissioning_sample().accepted
        controller.handle_response(f"[PRB:0,0,{trigger_z + 1}:1]")
        controller.handle_response("ok")
        assert transport.sent[-1] == b"G91 G21 G1 Z2 F100\n"
        controller.handle_response("ok")
        controller.apply_status(GrblStatus("Idle", Position(0, 0, trigger_z + 2), pins=""))
        controller.handle_response(f"[PRB:0,0,{trigger_z}:1]")
        controller.handle_response("ok")
        assert transport.sent[-1] == b"G91 G21 G1 Z2 F100\n"
        controller.handle_response("ok")
        assert controller.z_touch_plate_sample_count == sample_index

    assert controller.z_touch_plate_status == "ready"
    assert controller.z_touch_plate_record is not None
    assert controller.z_touch_plate_record.commissioned
