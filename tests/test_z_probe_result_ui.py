from __future__ import annotations

import json
from pathlib import Path

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.application.machine_session import ActionOutcome
from ttc3018_control.backend.qt_adapter import BackendApplicationAdapter
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.qt.main import build_engine
from ttc3018_control.qt.view_model import ControllerViewModel
from PySide6.QtCore import QObject
from PySide6.QtCore import QPointF
from PySide6.QtQuick import QQuickItem
import pytest


class _FakeClient:
    def __init__(self, snapshot: dict[str, object] | None = None) -> None:
        self._snapshot = snapshot or {
            "schema_version": 1,
            "protocol_version": 1,
            "revision": 4,
            "backend": {"available": True, "session_id": "session-a"},
            "z_probe_completion": {
                "state": "waiting-removal",
                "message": "Probe measurement confirmed",
                "plate_thickness": 4.0,
                "measured_machine_z": 12.5,
                "target_work_z": 0.0,
                "current_work_z": 4.0,
                "transaction_id": "probe-17",
            },
        }
        self.calls: list[tuple[str, dict[str, object]]] = []

    def snapshot(self):
        return self._snapshot

    def invoke(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return {"accepted": True, "message": f"{action} accepted"}

    def events(self, *, after: int | None = None, limit: int = 100):
        return {"events": [], "next_sequence": after or 0, "latest_sequence": after or 0}


class _FakeConnection:
    connected = True


def test_result_dialog_is_manual_and_has_explicit_remove_then_continue_flow() -> None:
    root = Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml"
    main_qml = (root / "Main.qml").read_text(encoding="utf-8")
    dialog_qml = (root / "ZProbeResultDialog.qml").read_text(encoding="utf-8")

    assert "ZProbeResultDialog {" in main_qml
    assert 'continue_z_probe_to_surface(transactionId)' in main_qml
    assert 'state !== "waiting-removal"' in main_qml
    assert "zProbeDismissedTransactionKey" in main_qml
    assert "zProbeDismissedBackendSession" in main_qml
    assert "zProbeLastFailureKey" in main_qml
    assert "continuationStateOnReconnect" in main_qml
    assert "toastTimer.restart()" in main_qml
    assert "Remove the touch puck and probe clip" in dialog_qml
    assert 'text: "Continue to work Z0"' in dialog_qml
    assert "measured_machine_z" in dialog_qml
    assert "plate_thickness" in dialog_qml
    assert "spindle stays off" in dialog_qml
    assert "X/Y stay unchanged" in dialog_qml
    assert 'dialog.continueRequested(String(dialog.completionSnapshot.transaction_id || ""))' in dialog_qml
    assert "continue_z_probe_to_surface" not in dialog_qml
    assert "acknowledge_z_touch_plate_removed()" not in main_qml
    assert 'z_touch_plate_status === "remove plate"' not in main_qml
    rose = main_qml.split("id: xyJogPad", 1)[1].split("ColumnLayout { objectName: \"zJogControls\"", 1)[0]
    for name in ("jogStepYPlus", "jogStepXMinus", "jogStepXPlus", "jogStepYMinus"):
        assert f'objectName: "{name}"' in rose
    assert 'objectName: "jogStepSelectorPointOne"' in main_qml
    assert 'objectName: "jogStepSelectorOne"' in main_qml
    assert 'objectName: "jogStepSelectorPointOne"' not in rose
    assert 'objectName: "jogStepZPlus"' in main_qml
    assert 'objectName: "jogStepZMinus"' in main_qml
    assert 'objectName: "jogStepSelectorPointOne"' in main_qml.split('id: xyJogPad', 1)[0]


def test_backend_adapter_projects_result_and_forwards_explicit_continue(tmp_path: Path) -> None:
    client = _FakeClient()
    adapter = BackendApplicationAdapter(client, tmp_path)

    assert adapter.z_probe_completion_snapshot == {
        "state": "waiting-removal",
        "message": "Probe measurement confirmed",
        "plate_thickness": 4.0,
        "measured_machine_z": 12.5,
        "target_work_z": 0.0,
        "current_work_z": 4.0,
        "transaction_id": "probe-17",
    }
    probe_outcome = adapter.probe_work_z()
    assert probe_outcome.accepted is True
    assert client.calls[-1][0] == "probe-work-z"
    assert client.calls[-1][1].get("expected_revision") is None

    outcome = adapter.continue_z_probe_to_surface("probe-17")
    assert outcome.accepted is True
    assert client.calls[-1][0] == "touch-continue-to-surface"
    assert client.calls[-1][1].get("expected_revision") is None
    assert client.calls[-1][1].get("transaction_id") == "probe-17"

    before = len(client.calls)
    stale = adapter.continue_z_probe_to_surface("")
    assert stale.accepted is False
    assert len(client.calls) == before


def test_view_model_serializes_snapshot_and_continues_only_when_called(qapp, tmp_path: Path) -> None:
    client = _FakeClient()
    application = BackendApplicationAdapter(client, tmp_path)
    view_model = ControllerViewModel(application)
    try:
        assert json.loads(view_model.z_probe_completion_json) == application.z_probe_completion_snapshot
        assert client.calls == []
        notices: list[str] = []
        view_model.toast_requested.connect(notices.append)

        view_model.continue_z_probe_to_surface("probe-17")

        assert [call[0] for call in client.calls] == ["touch-continue-to-surface"]
        assert notices[-1] == "touch-continue-to-surface accepted"
    finally:
        view_model.close()


def test_view_model_shows_job_loaded_by_persistent_backend(qapp, tmp_path: Path) -> None:
    client = _FakeClient()
    client._snapshot["program_detail"] = {
        "path": str(tmp_path / "external-job.nc"),
        "commands": [],
        "segments": [],
        "command_count": 131958,
        "preview_available": False,
        "bounds": {
            "minimum": {"x": 0.0, "y": 0.0, "z": -1.0},
            "maximum": {"x": 42.0, "y": 18.0, "z": 0.0},
        },
        "estimated_seconds": 87.0,
    }
    application = BackendApplicationAdapter(client, tmp_path)
    view_model = ControllerViewModel(application)
    try:
        assert view_model.job_file == "No G-code loaded"
        view_model._poll()

        assert view_model.job_file == "external-job.nc"
        assert "131958 commands" in view_model.job_summary
        assert "42.0 × 18.0 mm" in view_model.preview_summary
        assert view_model.program is not None
        assert view_model.preview_strokes == []

        client._snapshot["program_detail"] = {
            **client._snapshot["program_detail"],
            "path": str(tmp_path / "replacement-job.nc"),
            "command_count": 12,
        }
        view_model._poll()
        assert view_model.job_file == "replacement-job.nc"
        assert "12 commands" in view_model.job_summary
    finally:
        view_model.close()


def test_probe_start_uses_the_explicit_button_and_keeps_removal_continue(qapp, tmp_path: Path) -> None:
    application = ApplicationController(tmp_path)
    starts: list[bool] = []
    application.probe_work_z = lambda: starts.append(True) or ActionOutcome(True, "Probe started")
    view_model = ControllerViewModel(application)
    confirmations: list[tuple[str, str, str]] = []
    notices: list[str] = []
    view_model.confirmation_requested.connect(lambda *args: confirmations.append(args))
    view_model.toast_requested.connect(notices.append)

    try:
        view_model.probe_work_z()

        assert starts == [True]
        assert confirmations == []
        assert view_model._pending_confirmation is None
        assert notices[-1] == "Probe started"
    finally:
        view_model.close()


def test_backend_adapter_routes_lease_token_and_renewal(tmp_path: Path) -> None:
    client = _FakeClient()
    adapter = BackendApplicationAdapter(client, tmp_path)

    assert adapter.start_live_jog("X", 1, False, 500, lease_token="press-token").accepted
    assert adapter.renew_live_jog("press-token").accepted
    assert adapter.stop_live_jog().accepted
    assert client.calls[-3][0] == "live-jog-start"
    assert client.calls[-3][1]["lease_token"] == "press-token"
    assert client.calls[-3][1]["expected_revision"] == 4
    assert client.calls[-3][1]["idempotency_key"].startswith("qt:live-jog-start:")
    assert client.calls[-2][0] == "live-jog-renew"
    assert client.calls[-2][1] == {"token": "press-token"}
    assert client.calls[-1] == ("live-jog-stop", {})


def test_live_jog_renews_only_for_the_current_local_press_and_stops_unconditionally(qapp, tmp_path: Path) -> None:
    application = ApplicationController(tmp_path)
    view_model = ControllerViewModel(application)
    view_model.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    view_model.connection = _FakeConnection()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    view_model.session.establish_reference()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 10, 10)))
    starts: list[str] = []
    renewals: list[str] = []
    stops: list[bool] = []
    application.start_live_jog = lambda axis, direction, allow, feed, *, lease_token: (
        starts.append(lease_token) or ActionOutcome(True, "started")
    )
    application.renew_live_jog = lambda token: renewals.append(token) or ActionOutcome(True, "renewed")
    application.stop_live_jog = lambda: stops.append(True) or ActionOutcome(True, "stopped")

    try:
        view_model.start_live_jog("X", 1)
        assert len(starts) == 1 and starts[0]
        assert view_model._live_jog_renew_timer.isActive()
        view_model._renew_live_jog_lease()
        assert renewals == starts

        # The stop request is sent even though a backend snapshot may report
        # no active jog; the locally pressed lease is the authority for release.
        view_model.stop_live_jog()
        assert not view_model._live_jog_renew_timer.isActive()
        assert view_model._live_jog_lease_token == ""
        assert stops == [True]
    finally:
        view_model.close()


def test_stale_confirmation_reports_canceled_or_replaced_action(qapp, tmp_path: Path) -> None:
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)
    try:
        view_model.confirm_pending_action("old-token")
        assert notices[-1] == "This action was canceled or replaced; choose it again."
    finally:
        view_model.close()


def test_expired_live_jog_lease_stops_without_retry_or_heartbeat(qapp, tmp_path: Path) -> None:
    application = ApplicationController(tmp_path)
    view_model = ControllerViewModel(application)
    view_model.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    view_model.connection = _FakeConnection()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    view_model.session.establish_reference()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 10, 10)))
    renewal_calls: list[str] = []
    stop_calls: list[bool] = []
    application.start_live_jog = lambda *args, **kwargs: ActionOutcome(True, "started")
    application.renew_live_jog = lambda token: (
        renewal_calls.append(token) or ActionOutcome(False, "lease expired")
    )
    application.stop_live_jog = lambda: stop_calls.append(True) or ActionOutcome(True, "stopped")

    try:
        view_model.start_live_jog("Y", -1)
        token = view_model._live_jog_lease_token
        view_model._renew_live_jog_lease()
        assert renewal_calls == [token]
        assert stop_calls == [True]
        assert view_model._live_jog_lease_token == ""
        assert not view_model._live_jog_renew_timer.isActive()
        view_model._renew_live_jog_lease()
        assert renewal_calls == [token]
    finally:
        view_model.close()


def test_late_live_jog_start_response_does_not_restart_heartbeat(qapp, tmp_path: Path) -> None:
    application = ApplicationController(tmp_path)
    view_model = ControllerViewModel(application)
    view_model.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    view_model.connection = _FakeConnection()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    view_model.session.establish_reference()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 10, 10)))
    stop_calls: list[bool] = []
    application.stop_live_jog = lambda: stop_calls.append(True) or ActionOutcome(True, "stopped")
    application.renew_live_jog = lambda token: ActionOutcome(True, "renewed")

    def late_start(*args, **kwargs):
        view_model.stop_live_jog()
        return ActionOutcome(True, "started")

    application.start_live_jog = late_start
    try:
        view_model.start_live_jog("X", 1)
        assert stop_calls == [True, True]
        assert view_model._live_jog_lease_token == ""
        assert not view_model._live_jog_renew_timer.isActive()
    finally:
        view_model.close()


def test_shell_loads_new_result_dialog_component(qapp, tmp_path: Path) -> None:
    engine, view_model = build_engine(visible=False, root=tmp_path)
    try:
        root_object = engine.rootObjects()[0]
        assert root_object.findChild(QObject, "zProbeResultDialog") is not None
    finally:
        view_model.close()
        engine.deleteLater()


@pytest.mark.parametrize("connected", [False, True])
def test_pending_removal_dialog_is_shown_from_backend_snapshot(qapp, tmp_path: Path, connected: bool) -> None:
    snapshot = {
        "schema_version": 1,
        "protocol_version": 1,
        "revision": 4,
        "backend": {"available": True, "session_id": "session-a"},
        "connected": connected,
        "z_probe_completion": {
            "state": "waiting-removal",
            "message": "Z zero verified. Remove the puck and clip, then Continue to lower to work Z0.",
            "plate_thickness": 4.0,
            "measured_machine_z": 12.5,
            "target_work_z": 0.0,
            "current_work_z": 4.0,
            "transaction_id": "probe-17",
        },
    }
    engine, view_model = build_engine(visible=False, backend_client=_FakeClient(snapshot), root=tmp_path)
    view_model._timer.stop()
    try:
        root_object = engine.rootObjects()[0]
        dialog = root_object.findChild(QObject, "zProbeResultDialog")
        assert dialog is not None
        qapp.processEvents()
        root_object.setProperty("visible", True)
        qapp.processEvents()
        assert dialog.property("visible") is True
        assert root_object.property("zProbeDismissedTransactionKey") == ""
    finally:
        view_model.close()
        engine.deleteLater()


def test_pending_removal_dialog_opens_when_backend_snapshot_changes(qapp, tmp_path: Path) -> None:
    snapshot = {
        "schema_version": 1,
        "protocol_version": 1,
        "revision": 4,
        "backend": {"available": True, "session_id": "session-a"},
        "connected": True,
        "status_state": "fresh",
        "z_probe_completion": {"state": "probing", "transaction_id": "probe-17"},
    }
    client = _FakeClient(snapshot)
    engine, view_model = build_engine(visible=True, backend_client=client, root=tmp_path)
    view_model._timer.stop()
    try:
        root_object = engine.rootObjects()[0]
        dialog = root_object.findChild(QObject, "zProbeResultDialog")
        assert dialog is not None
        assert dialog.property("visible") is False

        client._snapshot["z_probe_completion"] = {
            "state": "waiting-removal",
            "message": "Remove the puck and clip, then continue.",
            "plate_thickness": 4.0,
            "measured_machine_z": 12.5,
            "target_work_z": 0.0,
            "current_work_z": 4.0,
            "transaction_id": "probe-17",
        }
        view_model._poll()
        qapp.processEvents()

        assert dialog.property("visible") is True
    finally:
        view_model.close()
        engine.deleteLater()


def test_precision_jog_buttons_fit_inside_rose_without_overlapping_hold_buttons(qapp, tmp_path: Path) -> None:
    xy_step_names = ("jogStepYPlus", "jogStepXMinus", "jogStepXPlus", "jogStepYMinus")
    xy_hold_names = ("jogHoldYPlus", "jogHoldXMinus", "jogHoldXPlus", "jogHoldYMinus")
    for window_width, window_height in ((1180, 720), (1500, 920)):
        engine, view_model = build_engine(visible=False, root=tmp_path / str(window_width))
        try:
            root_object = engine.rootObjects()[0]
            root_object.setProperty("width", window_width)
            root_object.setProperty("height", window_height)
            root_object.setProperty("guidedIndex", 2)
            root_object.setProperty("visible", True)
            for _ in range(3):
                qapp.processEvents()

            rose = root_object.findChild(QQuickItem, "xyJogPad")
            assert rose is not None

            def item_rect_in(item_name: str, parent: QQuickItem) -> tuple[float, float, float, float]:
                item = root_object.findChild(QQuickItem, item_name)
                assert item is not None, item_name
                point = item.mapToItem(parent, QPointF(0, 0))
                return point.x(), point.y(), item.width(), item.height()

            def intersects(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> bool:
                ax, ay, aw, ah = first
                bx, by, bw, bh = second
                return min(ax + aw, bx + bw) > max(ax, bx) and min(ay + ah, by + bh) > max(ay, by)

            xy_steps = {name: item_rect_in(name, rose) for name in xy_step_names}
            xy_holds = {name: item_rect_in(name, rose) for name in xy_hold_names}
            for name, (x, y, width, height) in xy_steps.items():
                assert x >= 0 and y >= 0 and x + width <= rose.width() and y + height <= rose.height(), name
                assert width > 0 and height > 0, name
                assert not any(intersects((x, y, width, height), held) for held in xy_holds.values()), name

            z_controls = root_object.findChild(QQuickItem, "zJogControls")
            assert z_controls is not None
            z_plus_hold = item_rect_in("jogHoldZPlus", z_controls)
            z_minus_hold = item_rect_in("jogHoldZMinus", z_controls)
            z_steps = [item_rect_in(name, z_controls) for name in ("jogStepZPlus", "jogStepZMinus")]
            for step in z_steps:
                assert step[0] >= 0 and step[1] >= z_plus_hold[1] + z_plus_hold[3]
                assert step[1] + step[3] <= z_minus_hold[1]
                assert not intersects(step, z_plus_hold)
                assert not intersects(step, z_minus_hold)
        finally:
            view_model.close()
            engine.deleteLater()
