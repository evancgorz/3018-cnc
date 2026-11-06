from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ttc3018_control.backend.auto_continuation import AutomaticContinuation, continuation
from ttc3018_control.gcode import parse_gcode
from ttc3018_control.grbl import Position
from ttc3018_control.work_zero_settings import SavedWorkZero


def program(tmp_path):
    text = 'G21 G17 G90 G94 G54\nG0 Z3\nM3 S1000\nG4 P2\n'
    for i in range(8):
        text += f'G0 Z3\nG0 X{i+10} Y10\nG0 Z0.2\nG1 Z-0.6 F120\n'
        text += ''.join(f'G1 X{i+10} Y{10+j/10} F675\n' for j in range(20))
    text += 'G0 Z3\nM5\nM2\n'
    path = tmp_path / 'source.nc'
    path.write_text(text, newline='\n')
    return parse_gcode(text, path)


def app_for(p):
    app = NS(program=p, machine_id='machine', work_zero_confirmed=True, reference_trusted=True,
             _saved_work_zero=SavedWorkZero(1, 2, 3), job_state='running',
             job=NS(streamer=NS(error='', acknowledged_count=140)),
             status=NS(state='Idle', spindle=0), status_fresh=True,
             state=NS(work_position=Position(0, 0, 0), active_operation=''),
             work_offset=Position(1, 2, 3))
    app.return_to_work_zero = lambda: NS(accepted=True)
    app.load_program = lambda path: setattr(app, 'program', parse_gcode(Path(path).read_text(), path))
    app.authorize_job_start = lambda **kwargs: NS(accepted=True, token='one-use')
    app.start_authorized_job = lambda token: NS(accepted=True)
    return app


def test_boundary_is_before_uncertain_queue_and_suffix_exact(tmp_path):
    p = program(tmp_path)
    text, index, preamble = continuation(p, 140)
    output = parse_gcode(text)
    assert index < 140 - 32
    assert output.commands[preamble:] == p.commands[index:]
    assert output.commands[-2:] == ('M5', 'M2')


@pytest.mark.parametrize('extra', ['G91', 'G20', 'G2 X10 Y10 I1 J0', 'M3 S2000', 'G92 X0'])
def test_rejects_non_replayable_modes_and_spindle_changes(tmp_path, extra):
    p = program(tmp_path)
    with pytest.raises(ValueError):
        p = parse_gcode('\n'.join(p.commands[:-2]) + '\n' + extra + '\nM5\nM2\n')
        continuation(p, 140)


def test_recovered_home_waits_for_new_idle_zero_before_start(tmp_path):
    app = app_for(program(tmp_path))
    auto = AutomaticContinuation(tmp_path, lambda: 10)
    runtime = NS(application=app, safety_input_blocks_motion=False,
                 _job_watchdog_recovery=NS(snapshot=lambda: {'state': 'recovered'}))
    auto.enable(app)
    app.job_state = 'failed'
    app.job.streamer.error = 'controller produced no responses for 3.0 seconds'
    auto.poll(runtime)
    assert auto.state == 'returning'
    auto.poll(runtime)
    assert auto.state == 'returning'  # old status must not complete a return
    app.status = NS(state='Idle', spindle=0)
    app.state.work_position = Position(0, 0, 1)
    auto.poll(runtime)
    assert auto.state == 'returning'
    app.state.work_position = Position(0, 0, 0)
    auto.poll(runtime)
    assert auto.state == 'armed'
    assert auto.policy['attempts'] == 1
    assert app.program.path.parent.name == 'automatic-continuations'
    assert auto.policy['original_sha256'] != auto.policy['current_sha256']


@pytest.mark.parametrize('change', ['abort', 'safety', 'zero', 'source', 'tool'])
def test_operator_change_or_hazard_cancels_policy(tmp_path, change):
    app = app_for(program(tmp_path))
    auto = AutomaticContinuation(tmp_path)
    runtime = NS(application=app, safety_input_blocks_motion=False)
    auto.enable(app)
    if change == 'abort': app.job_state = 'aborted'
    if change == 'safety': runtime.safety_input_blocks_motion = True
    if change == 'zero': app._saved_work_zero = SavedWorkZero(2, 2, 3)
    if change == 'source': app.program = None
    if change == 'tool': app.machine_definition = 'different tool configuration'
    auto.poll(runtime)
    assert auto.policy is None


def test_policy_requires_explicit_reenable_after_backend_restart(tmp_path):
    auto = AutomaticContinuation(tmp_path)
    auto.enable(app_for(program(tmp_path)))
    restored = AutomaticContinuation(tmp_path)
    assert not restored.snapshot()['enabled']
    assert restored.snapshot()['restart_requires_reenable']


def test_real_controller_state_is_used_for_return_completion(tmp_path, monkeypatch):
    from ttc3018_control.application.controller import ApplicationController
    app = ApplicationController(tmp_path)
    app.load_program(program(tmp_path).path)
    app._saved_work_zero = SavedWorkZero(1, 2, 3)
    from ttc3018_control.grbl import GrblStatus
    app.session.status = GrblStatus(state='Idle', machine_position=Position(1, 2, 3), spindle=0)
    app.session.work_offset = Position(1, 2, 3)
    app.session.confirm_work_zero_axes('XYZ')
    monkeypatch.setattr(ApplicationController, 'reference_trusted', property(lambda self: True))
    monkeypatch.setattr(ApplicationController, 'status_fresh', property(lambda self: True))
    app.status = GrblStatus(state='Idle', machine_position=Position(1, 2, 3), spindle=0)
    auto = AutomaticContinuation(tmp_path)
    auto.enable(app)
    auto.state = 'returning'
    auto.deadline = auto.clock() + 100
    monkeypatch.setattr(auto, '_start', lambda runtime: setattr(auto, 'state', 'started'))
    auto.poll(NS(application=app, safety_input_blocks_motion=False))
    assert auto.state == 'started'


def test_repeated_loss_preserves_root_mapping_and_attempt_limit(tmp_path):
    original = program(tmp_path)
    app = app_for(original)
    auto = AutomaticContinuation(tmp_path)
    runtime = NS(application=app, safety_input_blocks_motion=False,
                 _job_watchdog_recovery=NS(snapshot=lambda: {'state': 'recovered'}))
    auto.enable(app)
    app.job_state = 'failed'
    app.job.streamer.error = 'connection lost'
    for attempt in range(3):
        auto.poll(runtime)
        assert auto.state == 'returning'
        app.status = NS(state='Idle', spindle=0)
        auto.poll(runtime)
        assert auto.policy['attempts'] == attempt + 1
        mapped = auto.policy['source_offset']
        preamble = auto.policy['preamble_commands']
        assert app.program.commands[preamble:] == original.commands[mapped:]
        app.job.streamer.acknowledged_count = min(140, len(app.program.commands) - 1)
    auto.poll(runtime)
    assert auto.policy is None
    assert 'retry limit' in auto.message


def test_return_timeout_cancels_without_start(tmp_path):
    app = app_for(program(tmp_path))
    auto = AutomaticContinuation(tmp_path, lambda: 1000)
    auto.enable(app)
    auto.state = 'returning'
    auto.deadline = 999
    auto.poll(NS(application=app, safety_input_blocks_motion=False))
    assert auto.policy is None
    assert '120 seconds' in auto.message
