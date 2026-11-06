from ttc3018_control.backend.runtime import BackendRuntime
from ttc3018_control.application.state import ConnectionMode


def test_production_usb_is_setup_only_at_controller_and_wire(tmp_path):
    runtime = BackendRuntime(tmp_path)
    app = runtime.application
    assert app._wifi_only_operations
    assert app.connection_service.usb_setup_only
    assert not app.operation_transport_ready
    assert not app.can_jog
    assert not app.can_home_machine
    assert not app.can_start_job
    assert not app.preflight()[0]
    assert not app.home_machine().accepted
    assert not app.start_spindle(1000).accepted
    assert not app.set_work_zero('XYZ').accepted
    assert not app.resume().accepted
    assert not app.resume_job().accepted
    assert not app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True).accepted
    runtime.shutdown()


def test_wifi_socket_without_current_status_is_not_operational(tmp_path):
    runtime = BackendRuntime(tmp_path)
    app = runtime.application
    app.connection_service.mode = ConnectionMode.WIFI
    assert not app.status_fresh
    assert not app.operation_transport_ready
    assert not app.preflight()[0]
    runtime.shutdown()


def test_backend_exposes_bootstrap_state_without_hardware(tmp_path):
    runtime = BackendRuntime(tmp_path)
    connection = runtime.snapshot()['connection']
    assert 'wifi_bootstrap' in connection
    assert connection['operation_transport_ready'] is False
    runtime.shutdown()

