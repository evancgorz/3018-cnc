from __future__ import annotations

import os
from pathlib import Path

import pytest

from ttc3018_control.backend import (BackendClient, BackendIncompatible, BackendOwnershipError,
                                     BackendRuntime, BackendServer)
from ttc3018_control.backend.discovery import DiscoveryRecord, DiscoveryStore, OwnerRecord
from ttc3018_control.backend.process import BackendProcessManager
from ttc3018_control.backend.protocol import PROTOCOL_VERSION, SCHEMA_VERSION


def _server(tmp_path: Path) -> BackendServer:
    server = BackendServer(BackendRuntime(tmp_path), root=tmp_path)
    server.start(poll=False)
    return server


def test_backend_root_has_one_owner_and_releases_exact_marker(tmp_path: Path) -> None:
    store = DiscoveryStore(tmp_path)
    owner = OwnerRecord(os.getpid(), "session-a")
    store.acquire_owner(owner)
    try:
        # The authenticated health endpoint itself is covered by the client
        # contract tests; this gate isolates the atomic owner decision.
        with pytest.raises(BackendOwnershipError, match="owned by process"):
            store.acquire_owner(OwnerRecord(os.getpid(), "another-session"))
        assert store.read_owner() == owner
    finally:
        store.remove_owner(owner)
    assert store.read_owner() is None


def test_dead_discovery_record_is_cleaned_before_startup(tmp_path: Path) -> None:
    store = DiscoveryStore(tmp_path)
    dead_pid = os.getpid() + 1_000_000
    while store.pid_is_alive(dead_pid):
        dead_pid += 1
    stale = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, dead_pid, "127.0.0.1",
                            1234, "stale-token", "stale-session")
    store.write(stale)
    server = _server(tmp_path)
    try:
        assert server.record is not None
        assert server.record.session_id != stale.session_id
        assert store.read() == server.record
    finally:
        server.stop(shutdown_runtime=False)


def test_dropped_client_heartbeat_and_reconnect_keep_backend_session(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        first = BackendClient(tmp_path)
        attached = first.attach()
        assert first.heartbeat()["session_id"] == attached["health"]["session_id"]
        session_id = first.record.session_id if first.record is not None else ""
        second = BackendClient(tmp_path)
        assert second.attach()["health"]["session_id"] == session_id
    finally:
        server.stop(shutdown_runtime=False)


def test_process_manager_attaches_to_live_owner_without_spawning(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        manager = BackendProcessManager(tmp_path)
        client = manager.attach_or_spawn()
        assert manager.spawned is False
        assert client.health()["session_id"] == server.session_id
        manager.close_client()
    finally:
        server.stop(shutdown_runtime=False)


def test_process_manager_surfaces_incompatible_owner_without_spawning(tmp_path: Path) -> None:
    class IncompatibleClient:
        def __init__(self, root: Path):
            self.root = root

        def attach(self):
            raise BackendIncompatible("protocol version mismatch")

    manager = BackendProcessManager(tmp_path, client_factory=IncompatibleClient)
    with pytest.raises(BackendIncompatible):
        manager.attach_or_spawn()
    assert manager.spawned is False


def test_backend_shutdown_requires_explicit_safe_abort_when_active(tmp_path: Path, monkeypatch) -> None:
    server = _server(tmp_path)
    try:
        client = BackendClient(tmp_path)
        client.attach()
        active = {"value": True}
        monkeypatch.setattr(type(server.runtime.application), "job_active",
                            property(lambda _application: active["value"]))
        rejected = client.shutdown()
        assert rejected["accepted"] is False
        assert server.running
        active["value"] = False
        accepted = client.shutdown()
        assert accepted["accepted"] is True
    finally:
        server.stop(shutdown_runtime=False)
