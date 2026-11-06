from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ttc3018_control.backend import data_migration
from ttc3018_control.backend.data_migration import (
    ActiveBackendError,
    DataMigrationError,
    DataRootMigrationInProgress,
    MIGRATION_LOCK,
    MIGRATION_MANIFEST,
    assert_data_root_not_migrating,
    migrate_data_root,
    verify_migration,
)
from ttc3018_control.backend.discovery import default_data_root
from ttc3018_control.backend.discovery import BackendOwnershipError, DiscoveryStore, OwnerRecord
from ttc3018_control.qt.main import parse_startup_arguments


def _put(root: Path, relative: str, payload: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_migration_copies_durable_state_and_omits_ephemeral_tokens(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "pine-data"
    profile = b'{"name":"Bench 3018","travel_x":290,"travel_y":170,"travel_z":40,"safe_z":30}\n'
    work_zero = b'{"x":12.5,"y":7.25,"z":0.0,"confirmed_axes":["X","Y","Z"]}\n'
    recovery = b'{"schema_version":1,"state":"interrupted","requires_operator_review":true}\n'
    _put(source, "config/machine-profile.json", profile)
    _put(source, "config/work-zero.json", work_zero)
    _put(source, "job-recovery.json", recovery)
    _put(source, "config/connection.json", json.dumps({
        "wifi_host": "192.168.4.1",
        "wifi_port": 23,
        "preferred_transport": "Wi-Fi TCP",
        "usb_port": "COM7",
        "auth_token": "connection-secret-token",
        "password": "connection-password",
    }).encode("utf-8"))
    _put(source, "pine-backend.json", b'{"pid":2147483647,"token":"discovery-secret-token"}\n')
    _put(source, "pine-backend.owner", b'{"pid":2147483647,"token":"owner-secret-token"}\n')
    _put(source, "config/credentials.json", b'{"token":"credentials-secret-token"}\n')
    _put(source, "artifacts/review.nc", b"G21 G90\n")

    report = migrate_data_root(source, destination)

    assert destination.is_dir()
    assert (destination / "config/machine-profile.json").read_bytes() == profile
    assert (destination / "config/work-zero.json").read_bytes() == work_zero
    assert (destination / "job-recovery.json").read_bytes() == recovery
    assert not (destination / "pine-backend.json").exists()
    assert not (destination / "pine-backend.owner").exists()
    assert not (destination / "config/credentials.json").exists()
    assert not (destination / "artifacts/review.nc").exists()
    connection = json.loads((destination / "config/connection.json").read_text(encoding="utf-8"))
    assert connection == {
        "wifi_host": "192.168.4.1",
        "wifi_port": 23,
        "preferred_transport": "Wi-Fi TCP",
        "usb_port": "COM7",
    }
    assert "token" not in (destination / "config/connection.json").read_text(encoding="utf-8")
    assert "password" not in (destination / "config/connection.json").read_text(encoding="utf-8")
    manifest_text = (destination / MIGRATION_MANIFEST).read_text(encoding="utf-8")
    assert "secret-token" not in manifest_text
    assert "connection-password" not in manifest_text
    assert {item.path for item in report.files} == {
        "config/machine-profile.json", "config/work-zero.json", "job-recovery.json", "config/connection.json"
    }
    verified = verify_migration(destination)
    for item in verified.files:
        content = (destination / item.path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item.destination_sha256
        assert len(content) == item.size
    assert not (source / MIGRATION_LOCK).exists()
    # Migration is copy-only so the old root remains a complete rollback path.
    assert (source / "config/machine-profile.json").read_bytes() == profile
    assert (source / "config/work-zero.json").read_bytes() == work_zero


def test_migration_refuses_a_live_backend_owner_without_creating_destination(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    destination = tmp_path / "external"
    source.mkdir()
    owner = _put(source, "pine-backend.owner", json.dumps({
        "pid": __import__("os").getpid(), "session_id": "test-session", "token": "do-not-print"
    }).encode("utf-8"))

    with pytest.raises(ActiveBackendError, match="stop it before migration"):
        migrate_data_root(source, destination)

    assert owner.exists()
    assert not destination.exists()
    assert not (source / MIGRATION_LOCK).exists()


def test_migration_refuses_unreadable_owner_marker(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    _put(source, "pine-backend.owner", b"not valid json")

    with pytest.raises(ActiveBackendError, match="Cannot verify backend ownership"):
        migrate_data_root(source, tmp_path / "external")


def test_migration_requires_a_new_non_overlapping_destination(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(DataMigrationError, match="Destination already exists"):
        migrate_data_root(source, existing)
    with pytest.raises(DataMigrationError, match="inside the source"):
        migrate_data_root(source, source / "nested")
    with pytest.raises(DataMigrationError, match="different data roots"):
        migrate_data_root(source, source)


def test_failed_promotion_removes_stage_and_preserves_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "new-root"
    original = b'{"x":4,"y":5,"z":6,"confirmed_axes":["X","Y","Z"]}\n'
    _put(source, "config/work-zero.json", original)

    def fail_promotion(stage: Path, target: Path) -> None:
        assert (stage / MIGRATION_MANIFEST).is_file()
        assert not target.exists()
        raise OSError("simulated interrupted rename")

    monkeypatch.setattr(data_migration, "_atomic_promote", fail_promotion)
    with pytest.raises(DataMigrationError, match="source root remains available for rollback"):
        migrate_data_root(source, destination)

    assert (source / "config/work-zero.json").read_bytes() == original
    assert not destination.exists()
    assert not (source / MIGRATION_LOCK).exists()
    assert list(destination.parent.iterdir()) == []


def test_verifier_detects_changed_destination_bytes(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    destination = tmp_path / "external"
    _put(source, "config/work-zero.json", b'{"x":1,"y":2,"z":3}\n')
    migrate_data_root(source, destination)
    (destination / "config/work-zero.json").write_bytes(b"changed\n")

    with pytest.raises(DataMigrationError, match="hash does not match"):
        verify_migration(destination)


def test_startup_accepts_explicit_root_and_preserves_cwd_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.chdir(legacy)
    explicit = tmp_path / "external"
    root, check, qt_args = parse_startup_arguments([
        "--data-root", str(explicit), "--check", "--platform", "offscreen"
    ])
    assert root == explicit
    assert check is True
    assert qt_args == ["--platform", "offscreen"]
    assert default_data_root(root) == explicit.resolve()
    assert default_data_root() == legacy.resolve()

    alias_root, _, _ = parse_startup_arguments(["--root", str(explicit)])
    assert alias_root == explicit


def test_application_startup_refuses_a_migration_marker(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    _put(root, MIGRATION_LOCK, b'{"pid":123}\n')

    with pytest.raises(DataRootMigrationInProgress, match="remove .pine-data-migration.lock"):
        assert_data_root_not_migrating(root)


def test_backend_owner_claim_cannot_race_a_migration(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    _put(root, MIGRATION_LOCK, b'{"pid":123}\n')

    with pytest.raises(BackendOwnershipError, match="reserved for data migration"):
        DiscoveryStore(root).acquire_owner(OwnerRecord(123, "test-session"))

    assert not (root / "pine-backend.owner").exists()
    assert (root / MIGRATION_LOCK).exists()
