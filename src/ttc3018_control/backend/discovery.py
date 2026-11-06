"""Atomic, owner-scoped discovery metadata for a Pine backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable

from .protocol import PROTOCOL_VERSION, SCHEMA_VERSION

DISCOVERY_FILENAME = "pine-backend.json"
OWNER_FILENAME = "pine-backend.owner"
ROOT_REGISTRATION_PREFIX = "pine-backend-root-"
ROOT_REGISTRATION_SCHEMA = 1
ROOT_MIGRATION_LOCK_FILENAME = ".pine-data-migration.lock"
_IS_WINDOWS = os.name == "nt"


def default_data_root(root: Path | str | None = None) -> Path:
    """Return the canonical application root, preserving the CWD default."""
    return Path(root if root is not None else Path.cwd()).expanduser().resolve()


def _default_registry_directory() -> Path:
    configured = os.environ.get("PINE_BACKEND_REGISTRY_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if _IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Pine" / "backend-roots"
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "pine" / "backend-roots"


class AmbiguousBackendRootError(ValueError):
    """More than one active backend is registered for this user."""


@dataclass(frozen=True)
class BackendRootRegistration:
    root: str
    pid: int
    session_id: str
    schema_version: int = ROOT_REGISTRATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", str(default_data_root(self.root)))

    def validate(self) -> None:
        path = Path(self.root)
        if (self.schema_version != ROOT_REGISTRATION_SCHEMA or not path.is_absolute()
                or self.pid <= 0 or not self.session_id):
            raise ValueError("backend root registration is incomplete or incompatible")

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "BackendRootRegistration":
        if not isinstance(value, dict):
            raise ValueError("backend root registration must be an object")
        result = cls(str(value["root"]), int(value["pid"]), str(value["session_id"]),
                     int(value["schema_version"]))
        result.validate()
        return result


class BackendRootRegistry:
    """Token-free per-user index of backend roots currently started by Pine.

    The index helps a client launched from another working directory locate an
    existing backend. The authenticated per-root discovery file remains the
    authority for network attachment; registry entries only identify roots and
    owners and never contain credentials.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory).expanduser().resolve() if directory is not None else _default_registry_directory()

    @staticmethod
    def _registration_key(registration: BackendRootRegistration) -> str:
        payload = f"{registration.root}\0{registration.pid}\0{registration.session_id}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _path(self, registration: BackendRootRegistration) -> Path:
        return self.directory / f"{ROOT_REGISTRATION_PREFIX}{self._registration_key(registration)}.json"

    def register(self, registration: BackendRootRegistration) -> Path:
        registration.validate()
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self._path(registration)
        fd, temp_name = tempfile.mkstemp(prefix=".pine-backend-root.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(registration.as_dict(), stream, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(temp_name).replace(target)
        finally:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass
        return target

    def unregister(self, registration: BackendRootRegistration) -> bool:
        """Remove only the exact root/PID/session registration."""
        path = self._path(registration)
        try:
            current = BackendRootRegistration.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False
        if current != registration:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def read(self) -> tuple[BackendRootRegistration, ...]:
        try:
            paths = tuple(self.directory.glob(f"{ROOT_REGISTRATION_PREFIX}*.json"))
        except OSError:
            return ()
        registrations: dict[tuple[str, int, str], BackendRootRegistration] = {}
        for path in paths:
            try:
                item = BackendRootRegistration.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            key = (str(default_data_root(item.root)), item.pid, item.session_id)
            registrations[key] = item
        return tuple(registrations[key] for key in sorted(registrations))


def discover_backend_root(root: Path | str | None = None, *, current_dir: Path | None = None,
                          registry: BackendRootRegistry | None = None) -> Path:
    """Resolve an explicit root, then CWD, then one registered active root.

    An explicit path always wins for isolated development. A discovery record
    in the current directory retains the historical CLI behavior. Otherwise,
    one matching live registration may supply the root; ambiguity is reported
    instead of selecting an arbitrary backend. With no registration, callers
    retain the CWD fallback and receive the ordinary missing-record diagnostic.
    """
    if root is not None:
        return default_data_root(root)
    cwd = default_data_root(current_dir)
    cwd_store = DiscoveryStore(cwd)
    cwd_record = cwd_store.read()
    if cwd_record is not None:
        cwd_owner = cwd_store.read_owner()
        owner_matches = (
            (cwd_owner is None and not cwd_store.owner_path.exists())
            or (cwd_owner is not None and cwd_owner.pid == cwd_record.pid
                and cwd_owner.session_id == cwd_record.session_id)
        )
        if cwd_store.pid_is_alive(cwd_record.pid) and owner_matches:
            return cwd

    source = registry or BackendRootRegistry()
    active_roots: dict[str, Path] = {}
    for item in source.read():
        candidate_root = default_data_root(item.root)
        store = DiscoveryStore(candidate_root)
        record = store.read()
        owner = store.read_owner()
        if (record is None or owner is None or record.pid != item.pid or record.session_id != item.session_id
                or owner.pid != item.pid or owner.session_id != item.session_id
                or not store.pid_is_alive(item.pid)):
            continue
        active_roots[str(candidate_root)] = candidate_root
    if len(active_roots) == 1:
        return next(iter(active_roots.values()))
    if len(active_roots) > 1:
        roots = sorted(active_roots)
        joined = ", ".join(roots)
        raise AmbiguousBackendRootError(
            f"Multiple active Pine backends were found ({joined}); pass --root <data-root> "
            "or BackendClient(<data-root>) to select one."
        )
    return cwd


def _windows_process_api():
    """Use query-only process handles; never signal or terminate an owner."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _windows_pid_is_alive(pid: int) -> bool:
    # PROCESS_QUERY_LIMITED_INFORMATION is sufficient for GetExitCodeProcess.
    # OpenProcess(ERROR_INVALID_PARAMETER) identifies an absent PID. Access
    # denial or any other indeterminate result is live/unknown: do not steal
    # an owner marker merely because Windows would not let us inspect it.
    api = _windows_process_api()
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() != 87
    try:
        exit_code = wintypes.DWORD()
        if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        api.CloseHandle(handle)


class BackendOwnershipError(RuntimeError):
    """The application root is already owned by another backend process."""


@dataclass(frozen=True)
class DiscoveryRecord:
    schema_version: int
    protocol_version: int
    pid: int
    host: str
    port: int
    token: str = field(repr=False)
    session_id: str

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("backend discovery version mismatch")
        if self.pid <= 0 or self.host != "127.0.0.1":
            raise ValueError("backend discovery must identify a loopback owner")
        if not 1 <= self.port <= 65535 or not self.token or not self.session_id:
            raise ValueError("backend discovery record is incomplete")

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    def public_dict(self) -> dict[str, object]:
        """Return owner/version metadata safe for human or CLI output."""
        self.validate()
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "pid": self.pid,
            "host": self.host,
            "port": self.port,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "DiscoveryRecord":
        if not isinstance(value, dict):
            raise ValueError("discovery metadata must be an object")
        result = cls(
            int(value["schema_version"]), int(value["protocol_version"]),
            int(value["pid"]), str(value["host"]), int(value["port"]),
            str(value["token"]), str(value["session_id"]),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class OwnerRecord:
    pid: int
    session_id: str

    def validate(self) -> None:
        if self.pid <= 0 or not self.session_id:
            raise ValueError("backend owner record is incomplete")

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "OwnerRecord":
        if not isinstance(value, dict):
            raise ValueError("backend owner metadata must be an object")
        result = cls(int(value["pid"]), str(value["session_id"]))
        result.validate()
        return result


class DiscoveryStore:
    """Read/write metadata under one application root.

    The backend writes a temporary sibling and atomically replaces the target.
    Removal is deliberately conditional on PID, session and token so an old
    process can never erase a newer owner's metadata.
    """

    def __init__(self, root: Path, filename: str = DISCOVERY_FILENAME) -> None:
        self.root = Path(root)
        self.path = self.root / filename
        self.owner_path = self.root / OWNER_FILENAME

    def read(self) -> DiscoveryRecord | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return DiscoveryRecord.from_dict(data)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def write(self, record: DiscoveryRecord) -> None:
        record.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record.as_dict(), stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(temp_name).replace(self.path)
        finally:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass

    def remove(self, record: DiscoveryRecord | None = None) -> bool:
        """Remove only this exact owner; return whether removal happened."""
        if record is None:
            return False
        current = self.read()
        if current is None or (
            current.pid != record.pid or current.session_id != record.session_id or current.token != record.token
        ):
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True

    def read_owner(self) -> OwnerRecord | None:
        try:
            return OwnerRecord.from_dict(json.loads(self.owner_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def pid_is_alive(pid: int) -> bool:
        try:
            pid = int(pid)
        except (TypeError, ValueError, OverflowError):
            return False
        if pid <= 0 or (_IS_WINDOWS and pid > 0xFFFFFFFF):
            return False
        if _IS_WINDOWS:
            return _windows_pid_is_alive(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except (OSError, OverflowError):
            return False
        return True

    def remove_owner(self, owner: OwnerRecord | None = None) -> bool:
        """Remove only an exact owner marker, never a newer process marker."""
        if owner is None:
            return False
        current = self.read_owner()
        if current != owner:
            return False
        try:
            self.owner_path.unlink()
        except FileNotFoundError:
            return False
        return True

    def acquire_owner(self, owner: OwnerRecord, *, live_check: Callable[[OwnerRecord], bool] | None = None) -> None:
        """Atomically claim this root, cleaning only a proven stale marker."""
        owner.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        operation_path = self.root / ROOT_MIGRATION_LOCK_FILENAME
        try:
            operation_fd = os.open(operation_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise BackendOwnershipError(
                "backend root is reserved for data migration"
            ) from exc
        try:
            os.close(operation_fd)
            for _ in range(2):
                try:
                    fd = os.open(self.owner_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    current = self.read_owner()
                    if current is not None:
                        is_live = live_check(current) if live_check is not None else self.pid_is_alive(current.pid)
                        if is_live:
                            raise BackendOwnershipError(
                                f"backend root is owned by process {current.pid}"
                            )
                        if not self.remove_owner(current):
                            continue
                        continue
                    # A malformed marker cannot identify a live owner. It is
                    # removed only at this exact, narrow path and then retried.
                    try:
                        self.owner_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                else:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(owner.as_dict(), stream, separators=(",", ":"))
                        stream.write("\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    return
            raise BackendOwnershipError("backend root ownership changed while claiming startup")
        finally:
            try:
                operation_path.unlink()
            except FileNotFoundError:
                pass

    def is_stale(self, probe: Callable[[DiscoveryRecord], bool] | None = None) -> bool:
        """Require both owner liveness and authenticated health for freshness.

        ``probe`` should perform the authenticated health request.  PID checks
        are only a cheap preliminary signal and are never sufficient by
        themselves.
        """
        record = self.read()
        if record is None:
            return True
        if probe is None:
            # A PID liveness check is not authenticated health.  Callers that
            # need to treat a record as live must supply a token-bound probe.
            return True
        if not self.pid_is_alive(record.pid):
            return True
        try:
            return not bool(probe(record))
        except Exception:
            return True


# Descriptive alias for integrations that refer to the metadata service as
# ``BackendDiscovery``.
BackendDiscovery = DiscoveryStore
