from dataclasses import replace
import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.z_touch_plate import ZTouchPlateRecord


class Wire:
    connected = True
    def __init__(self): self.sent = []; self.realtime = []
    def send_line(self, command, display_text=None): self.sent.append(command)
    def send_realtime(self, command): self.realtime.append(command)
    def disconnect(self): self.connected = False


def status(z, *, state='Idle', spindle=0, pins='', wco_z=13.5):
    return GrblStatus(state, Position(0,0,z), work_offset=Position(5,6,wco_z), feed=0, spindle=spindle, pins=pins)


def completed_probe(tmp_path, *, confirm_offset=True, initial_wco_z=13.5):
    app = ApplicationController(tmp_path)
    assert app.save_z_plate_capability(True).accepted
    assert app.save_z_touch_plate_settings(plate_thickness=1.5, active_low=False,
        fast_feed=100, slow_feed=25, max_search=5, retract=1, safe_retract=2, tolerance=.05).accepted
    wire = Wire(); app.set_transport_for_testing(wire)
    app.apply_status(status(0, wco_z=initial_wco_z)); assert app.establish_reference().accepted
    app.apply_status(status(20, wco_z=initial_wco_z))
    app._z_touch_plate_record = ZTouchPlateRecord.commissioned_record(
        app.machine_id or '', (1,1.01,1.02), .05, app.z_touch_plate_fingerprint)
    assert app.probe_work_z().accepted
    app.handle_response('[PRB:0,0,15:1]'); app.handle_response('ok'); app.handle_response('ok')
    app.apply_status(status(19, wco_z=initial_wco_z))
    app.handle_response('[PRB:0,0,15:1]'); app.handle_response('ok'); app.handle_response('ok')
    if confirm_offset:
        app.apply_status(status(15)); app.handle_response('ok')
    assert app.z_probe_completion_snapshot['state'] == 'probing'
    return app, wire


def test_z_probe_needs_no_xy_zero_and_preserves_xy_work_offsets(tmp_path):
    app, wire = completed_probe(tmp_path, confirm_offset=False, initial_wco_z=20)
    assert not app.work_zero_confirmed
    assert not app.session.confirmed_work_zero_axes
    offset_command = next(command for command in wire.sent if command.startswith(b"G10 L2 P1"))
    assert offset_command == b"G10 L2 P1 Z13.5\n"

    app.handle_response("ok")
    app.apply_status(status(15, wco_z=13.5))
    app.handle_response("ok")

    assert app.session.work_offset == Position(5, 6, 13.5)
    assert app.session.confirmed_work_zero_axes == frozenset("Z")
    assert not app.work_zero_confirmed


def test_success_waits_for_idle_then_explicit_removal_and_target_confirmation(tmp_path):
    app, wire = completed_probe(tmp_path)
    before = len(wire.sent)
    assert not app.continue_z_probe_to_surface().accepted
    app.apply_status(status(17))
    result = app.z_probe_completion_snapshot
    assert result['state'] == 'waiting-removal'
    assert result['measured_machine_z'] == 15
    assert result['plate_thickness'] == 1.5
    assert len(wire.sent) == before
    assert app.continue_z_probe_to_surface(result['transaction_id']).accepted
    assert wire.sent[-1] == b'$J=G91 G21 Z-3.5 F25\n'
    assert not app.continue_z_probe_to_surface().accepted
    assert not app.can_start_job
    app.handle_response('ok')
    assert app.z_probe_completion_snapshot['state'] == 'lowering'
    app.apply_status(status(15, state='Jog'))
    assert app.z_probe_completion_snapshot['state'] == 'lowering'
    app.apply_status(status(13.5))
    assert app.z_probe_completion_snapshot['state'] == 'complete'
    assert not app._z_plate_removal_required


@pytest.mark.parametrize('change', ['spindle','probe','offset','xy','nan','stale'])
def test_continue_rejects_changed_or_unknown_machine_facts(tmp_path, change):
    app, wire = completed_probe(tmp_path); app.apply_status(status(17))
    changed = status(17)
    if change == 'spindle': changed = replace(changed, spindle=100)
    if change == 'probe': changed = replace(changed, pins='P')
    if change == 'offset': changed = replace(changed, work_offset=Position(5,6,12))
    if change == 'xy': changed = replace(changed, machine_position=Position(1,0,17))
    if change == 'nan': changed = replace(changed, machine_position=Position(0,0,float('nan')))
    app.apply_status(changed)
    if change == 'stale': app._last_status_received_at = 0
    before = len(wire.sent)
    assert not app.continue_z_probe_to_surface().accepted
    assert len(wire.sent) == before


def test_error_and_reset_never_report_surface_completion(tmp_path):
    app, wire = completed_probe(tmp_path); app.apply_status(status(17))
    assert app.continue_z_probe_to_surface().accepted
    app.handle_response('error:15')
    assert app.z_probe_completion_snapshot['state'] == 'failed'
    assert wire.realtime
    assert not app.continue_z_probe_to_surface().accepted
    app.reset()
    assert not app.continue_z_probe_to_surface().accepted


def test_work_offset_mismatch_from_status_fails_the_probe_completion(tmp_path):
    app, wire = completed_probe(tmp_path, confirm_offset=False)
    sent_before = len(wire.sent)

    # A mismatching fresh WCO fails the probing service during status
    # observation; the public completion state must expose that failure too.
    app.apply_status(status(14.972, wco_z=13.528))

    result = app.z_probe_completion_snapshot
    assert result['state'] == 'failed'
    assert 'offset confirmation did not match' in result['message'].lower()
    assert app.probing.state.value == 'failed'
    assert not app._z_probe_pending
    assert not app.work_zero_confirmed
    assert len(wire.sent) == sent_before


def test_continue_rejects_a_replaced_probe_transaction(tmp_path):
    app, wire = completed_probe(tmp_path)
    app.apply_status(status(17))
    before = len(wire.sent)

    outcome = app.continue_z_probe_to_surface("old-probe-transaction")

    assert not outcome.accepted
    assert "no longer current" in outcome.message
    assert len(wire.sent) == before
    assert app.z_probe_completion_snapshot['state'] == 'waiting-removal'
