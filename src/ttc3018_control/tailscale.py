"""Small, safe adapter for the optional Tailscale Serve integration.

Pine owns the local HTTP server; this module only asks the installed Tailscale
CLI to publish one explicit HTTPS Serve mapping to that loopback server.  It
never enables Funnel, changes firewall rules, or resets a user's Serve config.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


class TailscaleError(RuntimeError):
    """Base error for an unavailable or unsafe Tailscale operation."""


class TailscaleNotInstalled(TailscaleError):
    """The Tailscale executable was not found."""


class TailscaleConflict(TailscaleError):
    """The requested HTTPS port is already owned by another Serve mapping."""


@dataclass(frozen=True)
class TailscaleStatus:
    state: str = "Unavailable"
    version: str = ""
    dns_name: str = ""
    backend_online: bool = False
    serve_url: str = ""
    target: str = ""
    message: str = "Tailscale is not available"

    @property
    def ready(self) -> bool:
        return self.state == "Ready" and self.backend_online and bool(self.serve_url)


def _normalise_target(target: str) -> str:
    parsed = urlparse(str(target).strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return ""
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return ""
    return f"http://127.0.0.1:{parsed.port or 80}"


def _find_port(value: Any) -> int | None:
    if isinstance(value, int) and 1 <= value <= 65535:
        return value
    if isinstance(value, str):
        parsed = urlparse(value if "://" in value else f"http://{value}")
        if parsed.port:
            return parsed.port
        if value.isdigit() and 1 <= int(value) <= 65535:
            return int(value)
    return None


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _serve_mapping(payload: Any, *, https_port: int) -> tuple[str, int] | None:
    """Find the requested HTTPS listener and its local HTTP target.

    Tailscale has used a few JSON shapes for ``serve status`` over time.  The
    parser intentionally accepts only mappings that visibly contain both an
    HTTPS port and a loopback target.
    """
    if isinstance(payload, Mapping):
        # Current Tailscale JSON separates listeners and web handlers:
        # {"TCP":{"8443":{"HTTPS":true}},
        #  "Web":{"node.ts.net:8443":{"Handlers":{"/":{"Proxy":...}}}}}
        tcp = payload.get("TCP")
        web = payload.get("Web")
        listener = tcp.get(str(https_port), {}) if isinstance(tcp, Mapping) else {}
        if isinstance(listener, Mapping) and listener.get("HTTPS") is True and isinstance(web, Mapping):
            for address, handlers in web.items():
                if _find_port(str(address)) != https_port:
                    continue
                target = _find_loopback_target(handlers)
                if target:
                    return target, https_port
        values = list(payload.items())
        text = " ".join(f"{key} {value}" for key, value in values).lower()
        port = next((_find_port(value) for key, value in values if "port" in str(key).lower()), None)
        if port is None:
            port = next((int(key) for key, _value in values if str(key).isdigit() and 1 <= int(key) <= 65535), None)
        if port is None and "https" in text:
            port = next((_find_port(value) for _key, value in values), None)
        target = next((
            _normalise_target(str(value))
            for key, value in values
            if any(word in str(key).lower() for word in ("target", "proxy", "backend", "handler"))
        ), "")
        if not target:
            target = next((_normalise_target(str(value)) for _key, value in values), "")
        if port == https_port and target:
            return target, port
        for value in payload.values():
            found = _serve_mapping(value, https_port=https_port)
            if found:
                return found
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            found = _serve_mapping(value, https_port=https_port)
            if found:
                return found
    return None


def _find_loopback_target(payload: Any) -> str:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if any(word in str(key).lower() for word in ("target", "proxy", "backend", "handler")):
                target = _normalise_target(str(value))
                if target:
                    return target
            target = _find_loopback_target(value)
            if target:
                return target
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            target = _find_loopback_target(value)
            if target:
                return target
    else:
        return _normalise_target(str(payload))
    return ""


class TailscaleService:
    """Run a narrowly scoped subset of the Tailscale CLI with injection hooks."""

    def __init__(
        self,
        *,
        executable: str | Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.executable = str(executable) if executable else self.discover_executable()
        self._runner = runner or subprocess.run

    @staticmethod
    def discover_executable() -> str | None:
        candidates = [
            shutil.which("tailscale"),
            shutil.which("tailscale.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Tailscale", "tailscale.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Tailscale", "tailscale.exe"),
        ]
        return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)

    @property
    def installed(self) -> bool:
        return bool(self.executable)

    def _run(self, *args: str, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
        if not self.executable:
            raise TailscaleNotInstalled("Install and sign in to Tailscale before enabling Pine Live.")
        try:
            return self._runner(
                [self.executable, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TailscaleError(f"Tailscale did not respond: {exc}") from exc

    def _json(self, *args: str) -> Any:
        result = self._run(*args)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise TailscaleError(detail or f"tailscale {' '.join(args)} failed")
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise TailscaleError("Tailscale returned invalid status JSON") from exc

    def inspect(self, *, https_port: int = 8443) -> TailscaleStatus:
        if not self.installed:
            return TailscaleStatus()
        try:
            version_result = self._run("version")
            version = (version_result.stdout or "").splitlines()[0].strip() if version_result.returncode == 0 else ""
            if _version_tuple(version) and _version_tuple(version) < (1, 52):
                return TailscaleStatus("Unsupported", version, message="Upgrade Tailscale to version 1.52 or newer for Serve support")
            status = self._json("status", "--json")
            self_info = status.get("Self", {}) if isinstance(status, Mapping) else {}
            backend = status.get("BackendState", "") if isinstance(status, Mapping) else ""
            dns_name = str(self_info.get("DNSName", "")).rstrip(".") if isinstance(self_info, Mapping) else ""
            serve = self._json("serve", "status", "--json")
            mapping = _serve_mapping(serve, https_port=https_port)
            if mapping and dns_name:
                return TailscaleStatus("Ready", version, dns_name, backend == "Running", f"https://{dns_name}:{https_port}/", mapping[0], "Tailscale Serve is active")
            return TailscaleStatus("Signed in" if backend == "Running" else "Needs attention", version, dns_name, backend == "Running", "", "", "Tailscale is signed in but Pine Live is not published")
        except TailscaleError as exc:
            return TailscaleStatus("Error", message=str(exc))

    def enable(self, *, local_port: int, https_port: int = 8443) -> TailscaleStatus:
        current = self.inspect(https_port=https_port)
        expected = f"http://127.0.0.1:{local_port}"
        if current.target and current.target != expected:
            raise TailscaleConflict(f"Tailscale HTTPS {https_port} is already mapped to another service.")
        # --yes prevents first-use Serve/HTTPS consent from leaving Pine's
        # background worker blocked on an interactive CLI prompt.
        result = self._run("serve", "--yes", "--bg", f"--https={https_port}", expected)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise TailscaleError(detail or "Tailscale Serve could not be enabled")
        return self.inspect(https_port=https_port)

    def disable(self, *, https_port: int = 8443) -> None:
        current = self.inspect(https_port=https_port)
        if not current.target:
            return
        if not current.target.startswith("http://127.0.0.1:"):
            raise TailscaleConflict("Refusing to disable a Serve mapping Pine does not own.")
        result = self._run("serve", f"--https={https_port}", "off")
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise TailscaleError(detail or "Tailscale Serve could not be disabled")
