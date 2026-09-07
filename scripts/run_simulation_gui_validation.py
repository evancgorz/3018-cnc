"""Launch one isolated, visibly tagged Pine instance for manual twin validation.

This launcher deliberately does not perform the GUI checklist itself.  It gives
the operator a fresh application root, inert physical factories, and a manifest
that identifies only the process and children owned by this validation run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.machine_config import MachineDefinition
from ttc3018_control.qt.main import _configure_logging, build_engine
from ttc3018_control.machine_state import MachineProfile


def _write_sentinel_config(root: Path) -> dict[str, str]:
    """Create valid-or-safely-ignored config sentinels in the isolated root."""
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    payloads = {
        "connection.json": {"wifi_host": "sentinel.invalid", "wifi_port": 1,
                             "preferred_transport": "USB serial", "usb_port": "SENTINEL"},
        # These two physical-profile sentinels must remain valid so the
        # isolated controller has the authoritative 3018 travel envelope.
        # Their hashes still prove the launcher never changes them.
        "machines.json": {
            "schema_version": 1,
            "selected_machine_id": MachineDefinition.legacy_3018().machine_id,
            "machines": [MachineDefinition.legacy_3018(
                profile=MachineProfile(travel_x=290, travel_y=170, travel_z=40, safe_z=30)
            ).to_dict()],
        },
        "machine-profile.json": {"name": "Two Trees TTC 3018", "travel_x": 290.0,
                                  "travel_y": 170.0, "travel_z": 40.0, "safe_z": 30.0},
        "work-zero.json": {"sentinel": "digital-twin-gui-validation"},
        "z-touch-plates.json": {"sentinel": "digital-twin-gui-validation"},
        "step-prepare.json": {"sentinel": "digital-twin-gui-validation"},
        # Simulation preferences are intentionally mutable during the twin
        # session (the public speed/workpiece selectors persist here). They
        # are isolated under this temporary root, but are not physical
        # configuration sentinels and must not make the physical-integrity
        # check fail after a valid GUI run.
        "simulation.json": {},
    }
    sentinels: dict[str, str] = {}
    for name, payload in payloads.items():
        path = config / name
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if name in {"connection.json", "machines.json", "machine-profile.json", "work-zero.json", "z-touch-plates.json"}:
            sentinels[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sentinels


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_validation_application() -> tuple[QApplication, object, dict[str, object], Path, list[str]]:
    """Build the isolated GUI and return its app, view model, and manifest state."""
    marker = f"pine-twin-gui-{uuid.uuid4().hex[:12]}"
    temp_root = Path(tempfile.mkdtemp(prefix=marker + "-"))
    log_path = temp_root / "logs" / "pine.log"
    _configure_logging(temp_root)
    sentinels = _write_sentinel_config(temp_root)
    mutable_isolated_settings = {
        str(temp_root / "config" / "step-prepare.json"): hashlib.sha256(
            (temp_root / "config" / "step-prepare.json").read_bytes()
        ).hexdigest(),
        str(temp_root / "config" / "simulation.json"): hashlib.sha256(
            (temp_root / "config" / "simulation.json").read_bytes()
        ).hexdigest(),
    }
    physical_factory_calls: list[str] = []

    def forbidden_usb():
        physical_factory_calls.append("usb")
        raise RuntimeError("Physical USB factory is disabled in GUI validation")

    def forbidden_wifi():
        physical_factory_calls.append("wifi")
        raise RuntimeError("Physical Wi-Fi factory is disabled in GUI validation")

    controller = ApplicationController(
        temp_root,
        usb_factory=forbidden_usb,
        wifi_factory=forbidden_wifi,
        usb_ports=lambda: [],
    )
    manifest: dict[str, object] = {
        "main_pid": os.getpid(),
        "temp_root": str(temp_root),
        "session_marker": marker,
        "log_path": str(log_path),
        "physical_config_sentinels": sentinels,
        "mutable_isolated_settings": mutable_isolated_settings,
        "owned_child_pids": [],
        "loopback_endpoint": None,
    }
    manifest_path = temp_root / "gui-validation-manifest.json"
    _write_manifest(manifest_path, manifest)
    app = QApplication.instance() or QApplication([marker])
    app.setApplicationName(marker)
    engine, view_model = build_engine(visible=True, auto_connect=False, application=controller)
    root = engine.rootObjects()[0]
    root.setProperty("title", f"Pine — {marker}")
    engine._simulation_validation_manifest = manifest  # type: ignore[attr-defined]
    engine._simulation_validation_manifest_path = manifest_path  # type: ignore[attr-defined]
    engine._simulation_validation_physical_calls = physical_factory_calls  # type: ignore[attr-defined]

    def refresh_manifest() -> None:
        runtime = controller.simulation_runtime
        if runtime is not None:
            manifest["owned_child_pids"] = [process.pid for process in (runtime.backend, runtime.supervisor)
                                             if process is not None and process.pid is not None]
            manifest["loopback_endpoint"] = list(runtime.endpoint) if runtime.endpoint else None
        _write_manifest(manifest_path, manifest)

    refresh_timer = QTimer()
    refresh_timer.setInterval(250)
    refresh_timer.timeout.connect(refresh_manifest)
    refresh_timer.start()

    def cleanup() -> None:
        refresh_timer.stop()
        refresh_manifest()
        logging.getLogger("pine.qt").info("Simulation GUI validation physical factory calls: %s", physical_factory_calls)

    app.aboutToQuit.connect(cleanup)
    app.aboutToQuit.connect(view_model.close)
    root.show()
    return app, engine, manifest, manifest_path, physical_factory_calls


def main() -> int:
    app, _engine, _manifest, manifest_path, _physical_calls = create_validation_application()
    print(f"Digital-twin GUI validation session: {manifest_path}", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
