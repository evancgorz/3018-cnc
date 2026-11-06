"""Bounded backend attachment/spawn lifecycle used by production Qt startup."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

from .client import BackendClient, BackendIncompatible, BackendUnavailable
from .discovery import DiscoveryStore, default_data_root


class BackendProcessManager:
    def __init__(self, root: Path, *, client_factory: Callable[[Path], BackendClient] = BackendClient,
                 python: str | None = None, startup_timeout: float = 5.0) -> None:
        self.root = default_data_root(root)
        self.client_factory = client_factory
        self.python = python or sys.executable
        self.startup_timeout = max(0.2, float(startup_timeout))
        self.client: BackendClient | None = None
        self.process: subprocess.Popen | None = None
        self.spawned = False

    def attach_or_spawn(self) -> BackendClient:
        client = self.client_factory(self.root)
        try:
            client.attach()
            self.client = client
            return client
        except BackendIncompatible:
            # A reachable incompatible owner must be surfaced to the operator;
            # starting another backend would hide a version/configuration fault.
            raise
        except BackendUnavailable as attach_error:
            discovery = DiscoveryStore(self.root)
            current = discovery.read()
            if current is not None:
                if discovery.pid_is_alive(current.pid):
                    # A live owner is never replaced merely because a snapshot
                    # request timed out. Probe health separately and fail closed
                    # if the owner is unhealthy or still cannot attach.
                    probe = self.client_factory(self.root)
                    probe.record = current
                    try:
                        probe.heartbeat()
                    except BackendIncompatible:
                        raise
                    except BackendUnavailable as health_error:
                        raise BackendUnavailable(
                            f"Existing backend owner {current.pid} is alive but unhealthy: {health_error}"
                        ) from attach_error
                    raise BackendUnavailable(
                        f"Existing backend owner {current.pid} is healthy but the client could not attach: {attach_error}"
                    ) from attach_error
                # A dead PID is enough to clean this exact stale record. The
                # new backend still acquires the atomic owner marker below.
                discovery.remove(current)
        self.root.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        source_root = Path(__file__).resolve().parents[2]
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(source_root), existing_pythonpath) if item
        )
        self.process = subprocess.Popen(
            [self.python, "-m", "ttc3018_control.backend.main", "--root", str(self.root)],
            close_fds=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=environment,
        )
        self.spawned = True
        deadline = time.monotonic() + self.startup_timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            candidate = self.client_factory(self.root)
            try:
                candidate.attach()
                self.client = candidate
                return candidate
            except BackendIncompatible:
                raise
            except BackendUnavailable as exc:
                last_error = exc
                if self.process.poll() is not None:
                    raise BackendUnavailable(
                        f"Backend process exited during startup (code {self.process.returncode}): {exc}"
                    ) from exc
                time.sleep(0.05)
        raise BackendUnavailable(f"Backend did not become healthy within {self.startup_timeout:g}s: {last_error}")

    def close_client(self) -> None:
        """Release frontend resources only; never stop a shared backend."""
        self.client = None
