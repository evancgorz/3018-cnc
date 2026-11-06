from __future__ import annotations

from pathlib import Path
import time

import pytest

from ttc3018_control.backend import BackendClient, BackendRuntime, BackendServer, BackendUnavailable
from ttc3018_control.backend.discovery import DiscoveryStore
from ttc3018_control.backend.process import BackendProcessManager
from ttc3018_control.backend.qt_adapter import BackendApplicationAdapter


def _wait_for(client: BackendClient, predicate, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = client.snapshot()
        if predicate(last):
            return last
        time.sleep(0.05)
    raise AssertionError(f"backend state did not reach expected condition: {last}")


def _full_homing_declarations() -> dict[str, dict[str, object]]:
    return {
        axis: {
            "enabled": True,
            "end": "min",
            "pin": f"{axis}1",
            "active_low": False,
            "hard_limit": True,
            "debounce_ms": 0,
        }
        for axis in "XYZ"
    }


def test_active_twin_job_survives_frontend_close_and_reconnect(tmp_path: Path) -> None:
    server = BackendServer(BackendRuntime(tmp_path), root=tmp_path)
    server.start(poll=True)
    try:
        client = BackendClient(tmp_path)
        client.attach()
        client.invoke("configure-simulation", speed="realtime", workpiece="Pocket + retained island")
        assert client.invoke("save-homing-declarations", declarations=_full_homing_declarations())["accepted"] is True
        assert client.invoke("connect-simulation")["accepted"] is True
        _wait_for(client, lambda item: item.get("connected") and item.get("status_fresh"))
        assert client.invoke("home")["accepted"] is True
        _wait_for(client, lambda item: item.get("reference_trusted"))
        assert client.invoke("work-zero", axes="XYZ")["accepted"] is True
        _wait_for(client, lambda item: item.get("work_zero_confirmed"))
        client.invoke("load-generated-job", gcode="G21 G90\nG1 X100 Y100 Z3 F60\n", filename="long.nc")
        assert client.invoke("review-job")["accepted"] is True
        authorized = client.invoke("authorize-job-start", review_acknowledged=True,
                                   physical_preflight_confirmed=True)
        assert authorized["accepted"] is True, authorized
        assert client.invoke("start-job", token=authorized["token"])["accepted"] is True
        active = _wait_for(client, lambda item: item.get("job_active"), timeout=3.0)
        session_id = active["backend"]["session_id"]

        adapter = BackendApplicationAdapter(client, tmp_path)
        adapter.close()
        observer = BackendClient(tmp_path)
        reattached = observer.attach()
        assert reattached["health"]["session_id"] == session_id
        assert reattached["snapshot"]["job_active"] is True
        assert observer.invoke("abort-job", reason="end-to-end frontend close test")["accepted"] is True
        _wait_for(observer, lambda item: not item.get("job_active", False), timeout=3.0)
    finally:
        server.stop()


def test_explicit_backend_relaunch_after_crash_has_new_session_and_no_auto_motion(tmp_path: Path) -> None:
    manager = BackendProcessManager(tmp_path, startup_timeout=10.0)
    relaunched: BackendProcessManager | None = None
    try:
        client = manager.attach_or_spawn()
        assert manager.spawned is True
        first = client.health()
        first_session = first["session_id"]
        manager.close_client()
        observer = BackendClient(tmp_path)
        assert observer.attach()["health"]["session_id"] == first_session

        process = manager.process
        assert process is not None and process.poll() is None
        process.kill()
        process.wait(timeout=5.0)
        with pytest.raises(BackendUnavailable):
            observer.snapshot()
        assert DiscoveryStore(tmp_path).read() is not None

        relaunched = BackendProcessManager(tmp_path, startup_timeout=10.0)
        replacement = relaunched.attach_or_spawn()
        replacement_session = replacement.health()["session_id"]
        assert replacement_session != first_session
        snapshot = replacement.snapshot()
        assert snapshot["job_active"] is False
        assert snapshot["connected"] is False
        replacement.shutdown()
    finally:
        if relaunched is not None and relaunched.process is not None and relaunched.process.poll() is None:
            relaunched.process.kill()
            relaunched.process.wait(timeout=5.0)
        elif manager.process is not None and manager.process.poll() is None:
            manager.process.kill()
            manager.process.wait(timeout=5.0)
