from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ttc3018_control.backend.client import BackendClient, BackendRootAmbiguous
from ttc3018_control.backend.discovery import (
    AmbiguousBackendRootError,
    BackendRootRegistration,
    BackendRootRegistry,
    DiscoveryRecord,
    DiscoveryStore,
    OwnerRecord,
    default_data_root,
    discover_backend_root,
)
from ttc3018_control.backend.protocol import PROTOCOL_VERSION, SCHEMA_VERSION


def _active_root(root: Path, *, session_id: str = "session-a", token: str = "hidden-token") -> DiscoveryRecord:
    root.mkdir(parents=True, exist_ok=True)
    store = DiscoveryStore(root)
    owner = OwnerRecord(os.getpid(), session_id)
    store.acquire_owner(owner)
    record = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), "127.0.0.1",
                            43123, token, session_id)
    store.write(record)
    return record


def _register(registry: BackendRootRegistry, root: Path, *, session_id: str = "session-a") -> BackendRootRegistration:
    record = _active_root(root, session_id=session_id)
    registration = BackendRootRegistration(str(root.resolve()), record.pid, record.session_id)
    registry.register(registration)
    return registration


def test_data_root_normalizer_preserves_cwd_and_explicit_override(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    assert default_data_root() == cwd.resolve()
    assert default_data_root(Path("isolated")) == (cwd / "isolated").resolve()


def test_discovery_prefers_current_directory_and_explicit_root(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    other = tmp_path / "other"
    _active_root(cwd, session_id="cwd-session")
    registry = BackendRootRegistry(tmp_path / "registry")
    _register(registry, other, session_id="other-session")

    assert discover_backend_root(current_dir=cwd, registry=registry) == cwd.resolve()
    assert discover_backend_root(other, current_dir=cwd, registry=registry) == other.resolve()


def test_discovery_finds_one_registered_root_from_another_directory(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "caller"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    app_root = tmp_path / "pine-data"
    registry = BackendRootRegistry(tmp_path / "registry")
    _register(registry, app_root)

    assert discover_backend_root(current_dir=cwd, registry=registry) == app_root.resolve()
    assert BackendClient(registry=registry).root == app_root.resolve()


def test_discovery_reports_ambiguous_roots_and_explicit_override_wins(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "caller"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    first, second = tmp_path / "first", tmp_path / "second"
    registry = BackendRootRegistry(tmp_path / "registry")
    _register(registry, first, session_id="first-session")
    _register(registry, second, session_id="second-session")

    with pytest.raises(AmbiguousBackendRootError, match="pass --root"):
        discover_backend_root(current_dir=cwd, registry=registry)
    with pytest.raises(BackendRootAmbiguous, match="pass --root"):
        BackendClient(registry=registry)
    assert discover_backend_root(second, current_dir=cwd, registry=registry) == second.resolve()


def test_missing_and_stale_registrations_fall_back_to_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "caller"
    cwd.mkdir()
    registry = BackendRootRegistry(tmp_path / "registry")
    dead_pid = os.getpid() + 1000000
    while DiscoveryStore.pid_is_alive(dead_pid):
        dead_pid += 1
    stale_root = tmp_path / "stale"
    stale_root.mkdir()
    stale = BackendRootRegistration(str(stale_root.resolve()), dead_pid, "stale-session")
    registry.register(stale)

    assert discover_backend_root(current_dir=cwd, registry=registry) == cwd.resolve()


def test_stale_cwd_record_does_not_mask_a_live_registered_root(tmp_path: Path) -> None:
    cwd = tmp_path / "caller"
    cwd.mkdir()
    dead_pid = os.getpid() + 1000000
    while DiscoveryStore.pid_is_alive(dead_pid):
        dead_pid += 1
    cwd_store = DiscoveryStore(cwd)
    stale_owner = OwnerRecord(dead_pid, "stale-session")
    cwd_store.acquire_owner(stale_owner, live_check=lambda _owner: False)
    cwd_store.write(DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, dead_pid, "127.0.0.1",
                                    43123, "stale-token", "stale-session"))

    active_root = tmp_path / "live"
    registry = BackendRootRegistry(tmp_path / "registry")
    _register(registry, active_root, session_id="live-session")

    assert discover_backend_root(current_dir=cwd, registry=registry) == active_root.resolve()


def test_owner_mismatch_in_cwd_does_not_mask_a_registered_root(tmp_path: Path) -> None:
    cwd = tmp_path / "caller"
    cwd.mkdir()
    cwd_store = DiscoveryStore(cwd)
    cwd_store.acquire_owner(OwnerRecord(os.getpid(), "stale-owner-session"))
    cwd_store.write(DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), "127.0.0.1",
                                    43123, "stale-token", "different-discovery-session"))

    active_root = tmp_path / "live"
    registry = BackendRootRegistry(tmp_path / "registry")
    _register(registry, active_root, session_id="live-session")

    assert discover_backend_root(current_dir=cwd, registry=registry) == active_root.resolve()


def test_registration_is_token_free_and_removal_is_exact(tmp_path: Path) -> None:
    registry = BackendRootRegistry(tmp_path / "registry")
    root = tmp_path / "data"
    registration = _register(registry, root)
    entry_path = registry._path(registration)
    serialized = entry_path.read_text(encoding="utf-8")

    assert "hidden-token" not in serialized
    assert json.loads(serialized) == registration.as_dict()
    assert registry.unregister(BackendRootRegistration(str(root.resolve()), registration.pid, "other-session")) is False
    assert registry.unregister(registration) is True
    assert not entry_path.exists()


def test_registry_normalizes_root_aliases_and_keeps_sessions_separate(tmp_path: Path) -> None:
    root = tmp_path / "data"
    alias = tmp_path / "data" / "not-created" / ".."
    first = BackendRootRegistration(str(root.resolve()), os.getpid(), "session-a")
    same_root_alias = BackendRootRegistration(str(alias), os.getpid(), "session-a")
    next_session = BackendRootRegistration(str(root.resolve()), os.getpid(), "session-b")
    registry = BackendRootRegistry(tmp_path / "registry")

    assert first == same_root_alias
    assert registry._path(first) == registry._path(same_root_alias)
    assert registry._path(first) != registry._path(next_session)
    registry.register(first)
    registry.register(next_session)
    assert registry.unregister(first) is True
    assert registry.read() == (next_session,)


def test_discovery_record_public_summary_and_repr_redact_token() -> None:
    record = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), "127.0.0.1",
                            43123, "never-print-this", "session-a")

    assert record.as_dict()["token"] == "never-print-this"  # private discovery-file serialization
    assert "token" not in record.public_dict()
    assert "never-print-this" not in repr(record)


def test_cli_default_root_is_discovery_based_and_discover_output_is_redacted(tmp_path: Path, monkeypatch, capsys) -> None:
    from ttc3018_control.backend import cli

    cwd = tmp_path / "caller"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    assert cli.build_parser().parse_args(["discover"]).root is None
    record = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), "127.0.0.1",
                            43123, "never-print-this", "session-a")

    class FakeClient:
        def __init__(self, root):
            self.root = Path.cwd() if root is None else Path(root)
            self.record = record

        def attach(self):
            return {"health": {}, "snapshot": {}}

    monkeypatch.setattr(cli, "BackendClient", FakeClient)
    assert cli.main(["discover", "--json"]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["data_root"] == str(Path.cwd().resolve())
    assert result["backend"]["session_id"] == "session-a"
    assert "never-print-this" not in output
    assert "token" not in result["backend"]


def test_cli_reports_ambiguous_registered_roots_as_actionable_error(monkeypatch, capsys) -> None:
    from ttc3018_control.backend import cli

    class AmbiguousClient:
        def __init__(self, _root):
            raise BackendRootAmbiguous("Multiple active roots; pass --root <data-root>.")

    monkeypatch.setattr(cli, "BackendClient", AmbiguousClient)
    assert cli.main(["discover", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "ambiguous_backend_root"
    assert "pass --root" in result["message"]


def test_backend_startup_stdout_omits_token_and_registration_is_cleaned(tmp_path: Path, monkeypatch, capsys) -> None:
    from ttc3018_control.backend import main as backend_main

    token = "startup-secret-token"
    record = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), "127.0.0.1",
                            43123, token, "session-a")
    registry = BackendRootRegistry(tmp_path / "registry")

    class FakeEvent:
        def wait(self):
            return None

        def set(self):
            return None

    class FakeServer:
        def __init__(self, runtime, *, root):
            self.root = root

        def start(self, *, poll):
            return record

        def stop(self):
            return None

    monkeypatch.setattr(backend_main, "BackendRuntime", lambda root: object())
    monkeypatch.setattr(backend_main, "BackendServer", FakeServer)
    monkeypatch.setattr(backend_main, "BackendRootRegistry", lambda: registry)
    monkeypatch.setattr(backend_main.threading, "Event", FakeEvent)
    monkeypatch.setattr(backend_main.signal, "signal", lambda *_args: None)

    root = tmp_path / "explicit-root"
    assert backend_main.main(["--root", str(root)]) == 0
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["data_root"] == str(root.resolve())
    assert summary["session_id"] == "session-a"
    assert token not in output
    assert registry.read() == ()


def test_qt_build_engine_preserves_preconstructed_application_root(tmp_path: Path, monkeypatch, qapp) -> None:
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.qt import main as qt_main

    qml_dir = tmp_path / "qml"
    qml_dir.mkdir()
    (qml_dir / "Main.qml").write_text(
        "import QtQuick\nimport QtQuick.Controls\nApplicationWindow { visible: false }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(qt_main, "QML_ROOT", qml_dir)
    controller = ApplicationController(tmp_path)

    engine, view_model = qt_main.build_engine(application=controller)
    try:
        assert view_model._application_root == tmp_path.resolve()
    finally:
        view_model.close()
        engine.deleteLater()
        qapp.processEvents()
