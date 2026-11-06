"""Explicit, offline migration of durable Pine machine data between roots."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from ..connection_settings import ConnectionSettings
from .discovery import (
    DISCOVERY_FILENAME,
    OWNER_FILENAME,
    ROOT_MIGRATION_LOCK_FILENAME,
    DiscoveryStore,
    default_data_root,
)


MIGRATION_SCHEMA_VERSION = 1
MIGRATION_MANIFEST = "pine-data-migration.json"
MIGRATION_LOCK = ROOT_MIGRATION_LOCK_FILENAME

# Copy only files owned by durable settings/recovery stores. Project files,
# generated jobs, logs, discovery records, owner markers and credentials are
# deliberately outside this allowlist.
DURABLE_DATA_FILES = (
    "config/machines.json",
    "config/machine-profile.json",
    "config/connection.json",
    "config/work-zero.json",
    "config/z-touch-plates.json",
    "config/step-prepare.json",
    "config/simulation.json",
    "config/ui-preferences.json",
    "config/live.json",
    "config/automatic-continuation.json",
    "config/homing-declarations.json",
    "config/commissioning.json",
    "job-recovery.json",
    "safety-input.audit.jsonl",
)


class DataMigrationError(RuntimeError):
    """The requested migration cannot be completed safely."""


class ActiveBackendError(DataMigrationError):
    """The source root still has a live or unverifiable backend marker."""


class DataRootMigrationInProgress(DataMigrationError):
    """A migration marker prevents application startup on this root."""


@dataclass(frozen=True)
class MigratedFile:
    path: str
    size: int
    source_sha256: str
    destination_sha256: str
    transformed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationReport:
    source_root: str
    destination_root: str
    files: tuple[MigratedFile, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "source_root": self.source_root,
            "destination_root": self.destination_root,
            "rollback": "The source root is retained unchanged; select it again to roll back.",
            "files": [item.as_dict() for item in self.files],
        }


def assert_data_root_not_migrating(root: Path | str) -> None:
    """Fail startup while an offline migration has reserved this root."""
    marker = default_data_root(root) / MIGRATION_LOCK
    if marker.exists():
        raise DataRootMigrationInProgress(
            f"Data root migration is in progress or was interrupted at {marker.parent}. "
            "Wait for migration to finish; if it stopped, confirm no migration process remains "
            f"and remove {MIGRATION_LOCK} before starting Pine."
        )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_source_file(root: Path, relative: str) -> Path | None:
    path = root / relative
    parts = Path(relative).parts
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise DataMigrationError(f"Refusing to migrate a symbolic link: {relative}")
    if not path.exists():
        return None
    if not path.is_file():
        raise DataMigrationError(f"Expected a regular data file at {relative}")
    return path


def _sanitize_connection_settings(data: bytes) -> bytes:
    try:
        raw = json.loads(data.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("connection settings must be a JSON object")
        known = {key: raw[key] for key in ("wifi_host", "wifi_port", "preferred_transport", "usb_port") if key in raw}
        settings = ConnectionSettings(**known)
        settings.validate()
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DataMigrationError(f"Cannot safely migrate config/connection.json: {exc}") from exc
    return (json.dumps(asdict(settings), indent=2) + "\n").encode("utf-8")


def _check_backend_markers(root: Path) -> None:
    """Reject live owners; do not expose or copy either marker's auth token."""
    for filename in (OWNER_FILENAME, DISCOVERY_FILENAME):
        marker = root / filename
        if not marker.exists():
            continue
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(record.get("pid", 0)) if isinstance(record, dict) else 0
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ActiveBackendError(
                f"Cannot verify backend ownership from {filename}; close Pine and resolve that marker before migration."
            ) from exc
        if pid <= 0:
            if filename == OWNER_FILENAME:
                raise ActiveBackendError(
                    "Cannot verify backend ownership from pine-backend.owner; close Pine and resolve that marker before migration."
                )
            continue
        if DiscoveryStore.pid_is_alive(pid):
            raise ActiveBackendError(
                f"Backend process {pid} still owns or advertises the source data root; stop it before migration."
            )


def _write_synced(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_promote(stage: Path, destination: Path) -> None:
    # The stage lives beside the destination, so this is a same-volume rename.
    # os.rename refuses an existing destination on supported desktop platforms.
    os.rename(stage, destination)


def _assert_roots_do_not_overlap(source: Path, destination: Path) -> None:
    if source == destination:
        raise DataMigrationError("Source and destination must be different data roots")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        raise DataMigrationError("Destination cannot be inside the source data root")
    try:
        source.relative_to(destination)
    except ValueError:
        pass
    else:
        raise DataMigrationError("Source cannot be inside the destination data root")


def migrate_data_root(source_root: Path | str, destination_root: Path | str) -> MigrationReport:
    """Copy durable settings/recovery into a new root without changing source.

    The source is reserved for the duration. GUI/backend startup honors this
    reservation, active backend markers are rejected, and a complete staged
    destination is promoted with one same-volume directory rename.
    """
    source = default_data_root(source_root)
    destination = default_data_root(destination_root)
    _assert_roots_do_not_overlap(source, destination)
    if not source.is_dir():
        raise DataMigrationError(f"Source data root does not exist: {source}")
    if destination.exists():
        raise DataMigrationError(f"Destination already exists; choose a new empty path: {destination}")

    lock_path = source / MIGRATION_LOCK
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise DataRootMigrationInProgress(
            f"A migration is already in progress for source root {source}."
        ) from exc

    stage: Path | None = None
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"pid": os.getpid(), "destination_root": str(destination)}, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        _check_backend_markers(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise DataMigrationError(f"Destination already exists; choose a new empty path: {destination}")
        stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.migration-", dir=destination.parent))

        snapshot: dict[str, tuple[bytes, bytes]] = {}
        for relative in DURABLE_DATA_FILES:
            source_file = _safe_source_file(source, relative)
            if source_file is None:
                continue
            source_bytes = source_file.read_bytes()
            output_bytes = (_sanitize_connection_settings(source_bytes)
                            if relative == "config/connection.json" else source_bytes)
            snapshot[relative] = (source_bytes, output_bytes)

        migrated: list[MigratedFile] = []
        for relative, (source_bytes, output_bytes) in snapshot.items():
            output = stage / relative
            _write_synced(output, output_bytes)
            migrated.append(MigratedFile(
                path=relative,
                size=len(output_bytes),
                source_sha256=_digest(source_bytes),
                destination_sha256=_digest(output_bytes),
                transformed=source_bytes != output_bytes,
            ))

        report = MigrationReport(str(source), str(destination), tuple(migrated))
        manifest_path = stage / MIGRATION_MANIFEST
        _write_synced(manifest_path, (json.dumps(report.as_dict(), sort_keys=True, indent=2) + "\n").encode("utf-8"))
        verify_migration(stage)

        # Catch source changes or a backend that raced the first ownership
        # check before exposing the new root.
        _check_backend_markers(source)
        for relative, (source_bytes, _) in snapshot.items():
            current = _safe_source_file(source, relative)
            if current is None or _digest(current.read_bytes()) != _digest(source_bytes):
                raise DataMigrationError(f"Source data changed during migration: {relative}")

        if destination.exists():
            raise DataMigrationError(f"Destination appeared during migration; source remains unchanged: {destination}")
        _atomic_promote(stage, destination)
        stage = None
        verify_migration(destination)
        return report
    except (OSError, json.JSONDecodeError) as exc:
        raise DataMigrationError(f"Migration failed; source root remains available for rollback: {exc}") from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def verify_migration(destination_root: Path | str) -> MigrationReport:
    """Verify every copied file against the manifest's destination hashes."""
    destination = default_data_root(destination_root)
    path = destination / MIGRATION_MANIFEST
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != MIGRATION_SCHEMA_VERSION:
            raise ValueError("unsupported migration manifest")
        files = tuple(MigratedFile(
            path=str(item["path"]),
            size=int(item["size"]),
            source_sha256=str(item["source_sha256"]),
            destination_sha256=str(item["destination_sha256"]),
            transformed=bool(item.get("transformed", False)),
        ) for item in raw["files"])
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise DataMigrationError(f"Cannot read a supported migration manifest at {path}") from exc

    for item in files:
        relative = Path(item.path)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() not in DURABLE_DATA_FILES:
            raise DataMigrationError(f"Migration manifest contains an unexpected path: {item.path}")
        file_path = destination / relative
        try:
            data = file_path.read_bytes()
        except OSError as exc:
            raise DataMigrationError(f"Migrated file is missing: {item.path}") from exc
        if len(data) != item.size or _digest(data) != item.destination_sha256:
            raise DataMigrationError(f"Migrated file hash does not match: {item.path}")
    return MigrationReport(str(raw.get("source_root", "")), str(raw.get("destination_root", destination)), files)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pine-migrate-data")
    commands = parser.add_subparsers(dest="command", required=True)
    migrate = commands.add_parser("migrate", help="copy durable data into a new root")
    migrate.add_argument("source_root", type=Path)
    migrate.add_argument("destination_root", type=Path)
    verify = commands.add_parser("verify", help="check a migration's destination hashes")
    verify.add_argument("destination_root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = (migrate_data_root(args.source_root, args.destination_root)
                  if args.command == "migrate" else verify_migration(args.destination_root))
    except (DataMigrationError, OSError) as exc:
        parser.exit(2, f"pine-migrate-data: {exc}\n")
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
