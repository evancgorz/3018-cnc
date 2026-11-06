import pytest
from ttc3018_control.application.machine_session import ActionOutcome
from ttc3018_control.backend.runtime import BackendRuntime
from ttc3018_control.backend.dispatcher import ActionDispatcher, ActionRejected


def test_release_never_rejects_stale_revision_or_replays_cached_stop(tmp_path):
    runtime = BackendRuntime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    calls = []
    runtime.application.stop_live_jog = lambda: (calls.append('stop') or ActionOutcome(True, 'stopped'))
    for _ in range(2):
        assert dispatcher.invoke('live-jog-stop', expected_revision=-999,
            idempotency_key='same-release')['accepted']
    assert calls == ['stop', 'stop']
    runtime.shutdown()


def test_pause_ignores_stale_revision_and_always_reaches_job_service(tmp_path):
    runtime = BackendRuntime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    calls = []
    runtime.application.pause_job = lambda: (calls.append('pause') or ActionOutcome(True, 'paused'))

    for _ in range(2):
        result = dispatcher.invoke('pause-job', expected_revision=-999,
            idempotency_key='same-pause')
        assert result['accepted']

    assert calls == ['pause', 'pause']
    runtime.shutdown()


def test_bad_confirmation_does_not_destroy_valid_pending_action(tmp_path):
    runtime = BackendRuntime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    dispatcher._pending_confirmations['current'] = 'start-job'
    with pytest.raises(ActionRejected):
        dispatcher.confirmation_response('current', 'yes')
    assert dispatcher._pending_confirmations['current'] == 'start-job'
    assert not dispatcher.confirmation_response('current', False)['accepted']
    runtime.shutdown()


def test_production_dispatcher_requires_press_token_for_continuous_jog(tmp_path):
    runtime = BackendRuntime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    with pytest.raises(ActionRejected):
        dispatcher.invoke('live-jog-start', {'axis':'X','direction':1,'feed':500,'allow_unreferenced':False})
    runtime.shutdown()


def test_backend_poll_cancels_held_jog_when_status_trust_is_lost(tmp_path):
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.grbl import GrblStatus, Position

    class Wire:
        connected = True
        def __init__(self): self.sent = []; self.realtime = []
        def send_line(self, command, display_text=None): self.sent.append(command)
        def send_realtime(self, command): self.realtime.append(command)
        def disconnect(self): self.connected = False

    app = ApplicationController(tmp_path)
    wire = Wire(); app.set_transport_for_testing(wire)
    app.apply_status(GrblStatus('Idle', Position(0,0,0), feed=0, spindle=0))
    assert app.establish_reference().accepted
    app.apply_status(GrblStatus('Idle', Position(10,10,10), feed=0, spindle=0))
    assert app.start_live_jog('X', 1, False, 500, lease_token='held').accepted
    count = len(wire.sent)
    app._last_status_received_at = 0
    app.poll_live_jog()
    assert wire.realtime[-1] == b'\x85'
    assert len(wire.sent) == count
    assert not app.renew_live_jog('held').accepted
