from __future__ import annotations

import json
from pathlib import Path
import hashlib
import time
from types import SimpleNamespace

import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.live_settings import LiveSettingsStore
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.qt.view_model import ControllerViewModel


class _Transport:
    connected = True

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.realtime: list[bytes] = []

    def send_line(self, command: bytes, **_kwargs) -> None:
        self.lines.append(command)

    def send_realtime(self, command: bytes) -> None:
        self.realtime.append(command)

    def disconnect(self) -> None:
        self.connected = False


def test_view_model_uses_supplied_application_root_for_presentation_stores(tmp_path, monkeypatch) -> None:
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    app_root = tmp_path / "application-root"
    monkeypatch.chdir(other_cwd)
    vm = ControllerViewModel(ApplicationController(app_root))
    assert vm._ui_preferences_store.path == app_root / "config" / "ui-preferences.json"
    assert vm._live_settings_store.path == app_root / "config" / "live.json"


def test_view_model_rejects_conflicting_application_and_explicit_roots(tmp_path) -> None:
    application = ApplicationController(tmp_path / "application-root")
    with pytest.raises(ValueError, match="explicit ViewModel root"):
        ControllerViewModel(application, root=tmp_path / "different-root")


def test_root_scoped_preferences_reject_malformed_and_future_versions_without_cwd_mutation(tmp_path, monkeypatch) -> None:
    app_root = tmp_path / "application-root"
    config = app_root / "config"
    config.mkdir(parents=True)
    (config / "ui-preferences.json").write_text("not-json", encoding="utf-8")
    (config / "live.json").write_text(json.dumps({"version": 999, "port": 80}), encoding="utf-8")
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    before = Path.cwd()
    vm = ControllerViewModel(ApplicationController(app_root))
    assert Path.cwd() == before
    assert vm.expert_mode is False
    assert vm._live_settings.port == 8765


def test_all_application_and_view_model_stores_remain_under_resolved_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    relative_root = Path("application-root")
    (relative_root / "config").mkdir(parents=True)
    sentinel = relative_root / "config" / "connection.json"
    sentinel.write_text(json.dumps({
        "wifi_host": "sentinel.invalid",
        "wifi_port": 23,
        "preferred_transport": "USB serial",
        "usb_port": "SENTINEL",
    }), encoding="utf-8")
    application = ApplicationController(relative_root)
    app_root = relative_root.resolve()
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    sentinel = app_root / "config" / "connection.json"
    sentinel_hash = hashlib.sha256(sentinel.read_bytes()).hexdigest()

    monkeypatch.chdir(other_cwd)
    view_model = ControllerViewModel(application)
    paths = [
        application.machine_catalog_store.path,
        application.profile_store.path,
        application.connection_store.path,
        application.work_zero_store.path,
        application.z_touch_plate_store.records.path,
        application.step_prepare_store.path,
        application.simulation_settings_store.path,
        view_model._ui_preferences_store.path,
        view_model._live_settings_store.path,
    ]
    assert application.root == app_root
    assert all(path.resolve().is_relative_to(app_root) for path in paths)

    view_model.set_expert_mode(True)
    view_model.complete_first_run()
    view_model.close()
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == sentinel_hash
    assert not any(other_cwd.iterdir())


def test_live_preferences_reject_a_future_version_even_when_fields_are_valid(tmp_path) -> None:
    path = tmp_path / "config" / "live.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"version": 2, "port": 8765, "quality": "balanced"}), encoding="utf-8")
    settings = LiveSettingsStore(path).load()
    assert settings.version == 1
    assert settings.enabled is False
    assert settings.port == 8765


def test_discovery_and_connect_are_separate_lazy_injected_boundaries(tmp_path) -> None:
    calls: list[str] = []

    def ports():
        calls.append("discover")
        return [("COM-test", "loopback fake")]

    class FakeUsbTransport:
        connected = False

        def connect(self, port: str) -> None:
            calls.append(f"connect:{port}")
            self.connected = True

        def disconnect(self) -> None:
            self.connected = False

    def usb_factory():
        calls.append("factory")
        return FakeUsbTransport()

    application = ApplicationController(tmp_path, usb_factory=usb_factory, usb_ports=ports)
    view_model = ControllerViewModel(application)
    assert calls == []
    view_model.refresh_ports()
    assert calls == ["discover"]
    outcome = application.connect_usb("COM-test")
    assert outcome.accepted
    assert calls == ["discover", "factory", "connect:COM-test"]
    view_model.close()


def test_view_model_does_not_discover_usb_until_explicit_refresh(tmp_path) -> None:
    calls: list[int] = []

    def ports():
        calls.append(1)
        return [("COM-test", "loopback fake")]

    vm = ControllerViewModel(ApplicationController(tmp_path, usb_ports=ports))
    assert calls == []
    assert vm.ports == []
    vm.refresh_ports()
    assert calls == [1]
    assert vm.ports == ["COM-test — loopback fake"]


def test_job_authorization_is_single_use_and_bound_to_program_contents(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=0))
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nG1 X1 F100\n", "same-name.nc")

    assert not app.start_job().accepted
    issued = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
    assert issued.accepted and issued.token
    app.load_generated("G21 G90\nG1 X2 F100\n", "same-name.nc")
    before = list(transport.lines)
    stale = app.start_authorized_job(issued.token)
    assert not stale.accepted
    assert transport.lines == before

    fresh = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
    assert fresh.accepted
    started = app.start_authorized_job(fresh.token)
    assert started.accepted
    command_count = len(transport.lines)
    replay = app.start_authorized_job(fresh.token)
    assert not replay.accepted
    assert len(transport.lines) == command_count


@pytest.mark.parametrize(
    ("spindle", "stale", "allowed", "reason"),
    [
        (0, False, True, ""),
        (1000, False, False, "Turn the spindle off"),
        (None, False, False, "confirming the spindle is off"),
        (0, True, False, "fresh GRBL status report"),
    ],
)
def test_job_start_requires_fresh_idle_status_confirming_zero_rpm(tmp_path, spindle, stale, allowed, reason):
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus(
        "Idle",
        machine_position=Position(0, 0, 0),
        work_offset=Position(0, 0, 0),
        spindle=spindle,
    ))
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nG1 X1 F100\n", "spindle-gated.nc")
    if stale:
        app._last_status_received_at = time.monotonic() - app.STATUS_FRESHNESS_SECONDS - 1

    assert app.can_start_job is allowed
    if allowed:
        assert app.spindle_off_confirmed
        authorization = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
        assert authorization.accepted
        assert app.start_authorized_job(authorization.token).accepted
        assert transport.lines
    else:
        assert not app.spindle_off_confirmed
        authorization = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
        assert not authorization.accepted
        if reason:
            assert reason.lower() in authorization.message.lower()
        assert transport.lines == []


def test_job_start_waits_for_first_fresh_status_report(tmp_path):
    app = ApplicationController(tmp_path)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.load_generated("G21 G90\nG1 X1 F100\n", "no-status.nc")
    assert not app.status_fresh
    assert not app.spindle_off_confirmed
    assert not app.can_start_job
    authorization = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
    assert not authorization.accepted
    assert "fresh GRBL status report" in authorization.message
    assert transport.lines == []


def test_job_start_authorization_is_invalidated_when_spindle_starts(tmp_path):
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus(
        "Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=0,
    ))
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nM3 S1000\nG1 X1 F100\n", "spindle-gated.nc")
    authorization = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
    assert authorization.accepted

    app.apply_status(GrblStatus(
        "Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=1000,
    ))
    started = app.start_authorized_job(authorization.token)

    assert not started.accepted
    assert transport.lines == []


def test_job_start_authorization_is_invalidated_when_status_goes_stale(tmp_path):
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus(
        "Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=0,
    ))
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nM3 S1000\nG1 X1 F100\n", "stale-status.nc")
    authorization = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
    assert authorization.accepted

    app._last_status_received_at = time.monotonic() - app.STATUS_FRESHNESS_SECONDS - 1
    started = app.start_authorized_job(authorization.token)

    assert not started.accepted
    assert transport.lines == []


def test_job_authorization_invalidates_on_reference_wco_and_safety_change(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=0))
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nG1 X1 F100\n", "job.nc")
    for mutate in (
        lambda: app.session.envelope.invalidate("changed"),
        lambda: setattr(app.session, "work_offset", Position(1, 0, 0)),
        lambda: app.apply_status(GrblStatus("Hold", machine_position=Position(0, 0, 0))),
    ):
        app.session.envelope.establish(Position(0, 0, 0), app.profile)
        app.session.work_offset = Position(0, 0, 0)
        app.session.work_zero_confirmed = True
        app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=0))
        issued = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
        assert issued.accepted
        before = list(transport.lines)
        mutate()
        assert not app.start_authorized_job(issued.token).accepted
        assert transport.lines == before


def test_public_job_confirmation_rejects_replaced_program_without_commands(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0), spindle=0))
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nG1 X1 F100\n", "same-name.nc")
    vm = ControllerViewModel(app)
    vm.select_guided_step(5)
    vm.acknowledge_review()
    vm.guided_continue()
    vm.confirm_guided_preflight()
    vm.guided_start_job()
    token = vm.confirmation_token
    assert token.startswith("job_start:")

    app.load_generated("G21 G90\nG1 X2 F100\n", "same-name.nc")
    before = list(transport.lines)
    vm.confirm_pending_action(token)
    assert transport.lines == before
    vm.close()


def test_status_generation_and_supervisor_states_fail_closed_for_authorization(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0)))
    assert app.status_state == "fresh"
    app._last_status_received_at = time.monotonic() - 3.0
    assert app.status_state == "stale"
    assert not app.can_start_job

    app.connection_service.mode = ConnectionMode.SIMULATION
    app.connection_service.simulation_runtime = SimpleNamespace(
        started=True, supervisor_healthy=False, active_hazards=(), estop_status={}
    )
    assert app.supervisor_state == "unhealthy"
    app.connection_service.simulation_runtime.supervisor_healthy = True
    app.connection_service.simulation_runtime.active_hazards = (object(),)
    assert app.supervisor_state == "healthy"
    app.session.envelope.establish(Position(0, 0, 0), app.profile)
    app.session.work_offset = Position(0, 0, 0)
    app.session.work_zero_confirmed = True
    app.load_generated("G21 G90\nG1 X1 F100\n", "job.nc")
    issued = app.authorize_job_start(review_acknowledged=True, physical_preflight_confirmed=True)
    assert not issued.accepted
    assert "hazard" in issued.message.lower()

    generation = app.session_generation
    app.disconnect("session changed")
    assert app.session_generation != generation
    app.close()


def test_view_model_start_requires_review_and_preflight_before_confirmation(tmp_path) -> None:
    vm = ControllerViewModel(ApplicationController(tmp_path))
    vm.start_job()
    assert vm._pending_confirmation is None


def test_review_and_run_no_longer_use_filename_only_green_checks() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    review = qml[qml.index('objectName: "guidedReviewPage"'):qml.index('// Run — physical preflight')]
    run = qml[qml.index('// Run — physical preflight'):qml.index('// Machine\n')]
    assert "review_facts" in review and "review_facts" in run
    assert 'job_file !== "No G-code loaded"' not in review
    assert 'job_file !== "No G-code loaded"' not in run


def test_review_facts_are_typed_and_unknown_collision_is_not_green(tmp_path) -> None:
    vm = ControllerViewModel(ApplicationController(tmp_path))
    facts = vm.review_facts
    assert facts["validation"] == "not_run"
    assert facts["collision_analysis"] == "not_run"
    assert facts["bounds_checked"] is False
    assert facts["supervisor"] == "not_applicable"
