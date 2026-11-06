"""Qt-free command line adapter for the guarded Pine backend API.

The CLI is intentionally a thin client. It never opens a transport, formats a
GRBL command, or decides whether a machine action is safe; those decisions are
made by the persistent backend after an explicit operator confirmation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .client import (BackendClient, BackendIncompatible, BackendRequestRejected,
                     BackendRootAmbiguous, BackendUnavailable)


class CliAuthorizationError(PermissionError):
    """A mutating/energizing CLI action was not explicitly confirmed."""


def _common(parser: argparse.ArgumentParser, *, confirm: bool = False) -> None:
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, dest="json_mode")
    parser.add_argument("--revision", type=int, default=argparse.SUPPRESS, help="expected backend state revision")
    parser.add_argument("--idempotency-key", default=argparse.SUPPRESS, help="stable retry key for this command")
    if confirm:
        parser.add_argument("--confirm", action="store_true",
                            help="explicitly authorize this machine-affecting action")


def _action(parser: argparse.ArgumentParser, name: str, *, confirm: bool = False) -> argparse.ArgumentParser:
    child = parser.add_parser(name)
    _common(child, confirm=confirm)
    return child


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pine-cli",
        description="Attach to an existing Pine backend; this command never starts one.",
        epilog="For offline CAM and backend examples, see docs/AGENT_CNC_JOB_WORKFLOW.md.",
    )
    parser.add_argument("--root", type=Path, default=None,
                        help=("application data directory of the running backend; default checks this "
                              "directory, then a unique registered backend, then this directory again"))
    parser.add_argument("--json", action="store_true", dest="json_mode")
    parser.add_argument("--revision", type=int, default=None)
    parser.add_argument("--idempotency-key", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("discover", "status", "capabilities", "safety-input-status", "discover-usb", "events", "job-status", "review", "preflight"):
        child = _action(sub, name)
        if name == "events":
            child.add_argument("--after", type=int, default=None)
            child.add_argument("--limit", type=int, default=100)
    _action(sub, "acknowledge-safety-input", confirm=True)
    _action(sub, "continue-to-home", confirm=True)
    _action(sub, "cancel-recovery")
    automatic = _action(sub, "automatic-continuation", confirm=True)
    automatic.add_argument("--enabled", choices=("true", "false"), required=True)

    usb = _action(sub, "connect-usb", confirm=True)
    usb.add_argument("port_pos", nargs="?")
    usb.add_argument("--port", dest="port_opt")
    wifi = _action(sub, "connect-wifi", confirm=True)
    wifi.add_argument("host_pos", nargs="?")
    wifi.add_argument("port_pos", nargs="?", type=int)
    wifi.add_argument("--host", dest="host_opt")
    wifi.add_argument("--port", dest="port_opt", type=int)
    _action(sub, "connect-simulation")
    sim_config = _action(sub, "configure-simulation")
    sim_config.add_argument("speed")
    sim_config.add_argument("workpiece", nargs="?", default="Pocket + retained island")

    jog = _action(sub, "jog", confirm=True)
    jog.add_argument("axis_pos", nargs="?")
    jog.add_argument("distance_pos", nargs="?", type=float)
    jog.add_argument("--axis", dest="axis_opt")
    jog.add_argument("--distance", dest="distance_opt", type=float)
    jog.add_argument("--feed", type=float, default=500.0)
    for name in ("home", "hold", "resume", "cancel-jog", "return-reference", "return-work-zero"):
        child = _action(sub, name, confirm=name in {"home", "return-reference", "return-work-zero"})
        if name in {"return-reference", "return-work-zero"}:
            child.add_argument("--feed", type=float, default=500.0)
    zero = _action(sub, "work-zero", confirm=True)
    zero.add_argument("--axes", default="XYZ")
    disconnect = _action(sub, "disconnect", confirm=True)
    disconnect.add_argument("--reason", default="Disconnected by operator")

    load = _action(sub, "load-job")
    load.add_argument("path", type=Path, help="G-code file or Pine CAM report.json")
    generated = _action(sub, "load-generated")
    generated.add_argument("path", type=Path, help="UTF-8 G-code file")
    generated.add_argument("--filename", default=None)
    authorize = _action(sub, "authorize-start", confirm=True)
    authorize.add_argument("--review-acknowledged", action="store_true")
    authorize.add_argument("--physical-preflight-confirmed", action="store_true")
    start = _action(sub, "start", confirm=True)
    start.add_argument("--token", required=True)
    for name in ("pause", "abort-job"):
        child = _action(sub, name, confirm=True)
        if name == "abort-job":
            child.add_argument("--reason", default="Aborted by operator")
    probe = _action(sub, "probe", confirm=True)
    probe.add_argument("axis")
    probe.add_argument("--fast-distance", type=float, required=True)
    probe.add_argument("--slow-distance", type=float, required=True)
    probe.add_argument("--retract", type=float, required=True)
    probe.add_argument("--safe-retract", type=float, required=True)
    probe.add_argument("--fast-feed", type=float, default=100.0)
    probe.add_argument("--slow-feed", type=float, default=25.0)
    probe.add_argument("--retract-feed", type=float, default=100.0)
    probe.add_argument("--wcs-slot", type=int, default=1)
    probe.add_argument("--offset-axis", default="")
    probe.add_argument("--offset-value", type=float, default=0.0)
    probe.add_argument("--purpose", default="operator")
    _action(sub, "probe-work-z", confirm=True)
    abort_probe = _action(sub, "abort-probe", confirm=True)
    abort_probe.add_argument("--reason", default="Aborted by operator")
    spindle = _action(sub, "spindle-start", confirm=True)
    spindle.add_argument("rpm", type=int)
    _action(sub, "spindle-stop", confirm=True)

    profile = _action(sub, "save-profile", confirm=True)
    profile.add_argument("--name", default="Two Trees TTC 3018")
    profile.add_argument("--travel-x", type=float, required=True)
    profile.add_argument("--travel-y", type=float, required=True)
    profile.add_argument("--travel-z", type=float, required=True)
    profile.add_argument("--safe-z", type=float, required=True)
    profile.add_argument("--apply", action="store_true", help="apply the previewed change")
    homing = _action(sub, "save-homing", confirm=True)
    homing.add_argument("--declarations", type=Path, required=True)
    homing.add_argument("--apply", action="store_true")
    plate = _action(sub, "save-z-plate", confirm=True)
    for name, kwargs in (("thickness", {"type": float, "required": True}), ("active-low", {"action": "store_true"}),
                         ("fast-feed", {"type": float, "required": True}),
                         ("slow-feed", {"type": float, "required": True}),
                         ("max-search", {"type": float, "required": True}),
                         ("retract", {"type": float, "required": True}),
                         ("safe-retract", {"type": float, "required": True}),
                         ("tolerance", {"type": float, "required": True})):
        plate.add_argument(f"--{name}", dest=name.replace("-", "_"), **kwargs)
    plate.add_argument("--apply", action="store_true")

    simulation = _action(sub, "simulation")
    simulation.add_argument("operation", choices=("connect", "configure", "estop", "release-estop", "ack-estop", "export"))
    simulation.add_argument("--speed", default="realtime")
    simulation.add_argument("--workpiece", default="Pocket + retained island")
    simulation.add_argument("--path", type=Path)
    simulation.add_argument("--reset-asserted", action="store_true")
    limit = _action(sub, "simulation-limit")
    limit.add_argument("axis")
    limit.add_argument("--active", action="store_true")
    for name in ("commission-plate", "auto-xyz-abort", "touch-input-test", "touch-commission", "touch-ack-remove"):
        _action(sub, name, confirm=name in {"commission-plate", "touch-input-test", "touch-commission", "touch-ack-remove"})
    auto = _action(sub, "auto-xyz-start", confirm=True)
    auto.add_argument("x", type=float)
    auto.add_argument("y", type=float)
    auto.add_argument("z", type=float)
    export = _action(sub, "export-simulation-evidence")
    export.add_argument("path", type=Path)
    shutdown = _action(sub, "shutdown", confirm=True)
    shutdown.add_argument("--safe-abort", action="store_true")
    return parser


def _require_confirmation(args: argparse.Namespace) -> None:
    if not getattr(args, "confirm", False):
        raise CliAuthorizationError(
            f"{args.command} requires explicit --confirm; no machine action was sent"
        )


def _invoke(client: BackendClient, args: argparse.Namespace, action: str, **payload: Any) -> Any:
    return client.invoke(action, expected_revision=getattr(args, "revision", None),
                         idempotency_key=getattr(args, "idempotency_key", None), **payload)


def _preview(snapshot: dict[str, Any], label: str, proposed: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    changed = {key: {"current": current.get(key), "proposed": value}
               for key, value in proposed.items() if current.get(key) != value}
    return {"accepted": True, "preview": True, "apply_required": bool(changed),
            "label": label, "revision": snapshot.get("revision", 0), "changes": changed}


def _result(client: BackendClient, args: argparse.Namespace) -> Any:
    command = args.command
    if command == "discover":
        record = client.record
        if record is None:
            raise BackendUnavailable("Backend attachment did not produce a discovery record")
        return {"data_root": str(client.root), "backend": record.public_dict()}
    if command == "status":
        return client.snapshot()
    if command == "capabilities":
        return client.typed_snapshot().capabilities.to_dict()
    if command == "safety-input-status":
        return _invoke(client, args, "safety-input-status")
    if command == "acknowledge-safety-input":
        _require_confirmation(args)
        return _invoke(client, args, "acknowledge-safety-input")
    if command == "continue-to-home":
        _require_confirmation(args)
        return _invoke(client, args, "continue-to-home")
    if command == "automatic-continuation":
        _require_confirmation(args)
        return _invoke(client, args, command, enabled=args.enabled == "true")
    if command == "cancel-recovery":
        return _invoke(client, args, "cancel-recovery")
    if command == "discover-usb":
        return _invoke(client, args, "discover-usb")
    if command == "events":
        return client.events(after=args.after, limit=args.limit)
    if command in {"job-status", "review", "preflight"}:
        if command == "job-status":
            snapshot = client.snapshot()
            job = snapshot.get("job", {}) if isinstance(snapshot.get("job"), dict) else {}
            return {"state": snapshot.get("job_state", job.get("state", "idle")),
                    "progress": snapshot.get("job_progress", job.get("progress", 0.0)),
                    "active": snapshot.get("job_active", False), "revision": snapshot.get("revision", 0),
                    "recovery": snapshot.get("job_recovery", {})}
        return _invoke(client, args, "review-job" if command == "review" else "preflight")
    if command == "connect-usb":
        _require_confirmation(args)
        return _invoke(client, args, "connect-usb", port=args.port_opt or args.port_pos)
    if command == "connect-wifi":
        _require_confirmation(args)
        return _invoke(client, args, "connect-wifi", host=args.host_opt or args.host_pos,
                       port=args.port_opt or args.port_pos)
    if command == "connect-simulation":
        return _invoke(client, args, "connect-simulation")
    if command == "configure-simulation":
        return _invoke(client, args, "configure-simulation", speed=args.speed, workpiece=args.workpiece)
    if command == "disconnect":
        _require_confirmation(args)
        return _invoke(client, args, "disconnect", reason=args.reason)
    if command == "jog":
        _require_confirmation(args)
        return _invoke(client, args, "jog", axis=args.axis_opt or args.axis_pos,
                       distance=args.distance_opt if args.distance_opt is not None else args.distance_pos,
                       feed=args.feed)
    if command in {"home", "hold", "resume", "cancel-jog", "return-reference", "return-work-zero"}:
        if command in {"home", "return-reference", "return-work-zero"}:
            _require_confirmation(args)
        action = command
        return _invoke(client, args, action, **({"feed": args.feed} if hasattr(args, "feed") else {}))
    if command == "work-zero":
        _require_confirmation(args)
        return _invoke(client, args, "work-zero", axes=args.axes)
    if command == "load-job":
        return _invoke(client, args, "load-job", path=str(args.path.absolute()))
    if command == "load-generated":
        gcode = args.path.read_text(encoding="utf-8")
        return _invoke(client, args, "load-generated-job", gcode=gcode,
                       filename=args.filename or args.path.name)
    if command == "authorize-start":
        _require_confirmation(args)
        return _invoke(client, args, "authorize-job-start",
                       review_acknowledged=args.review_acknowledged,
                       physical_preflight_confirmed=args.physical_preflight_confirmed)
    if command == "start":
        _require_confirmation(args)
        return _invoke(client, args, "start-job", token=args.token)
    if command in {"pause", "abort-job"}:
        _require_confirmation(args)
        return _invoke(client, args, "pause-job" if command == "pause" else "abort-job",
                       **({"reason": args.reason} if command == "abort-job" else {}))
    if command == "probe":
        _require_confirmation(args)
        return _invoke(client, args, "probe", axis=args.axis, fast_distance=args.fast_distance,
                       slow_distance=args.slow_distance, retract=args.retract,
                       safe_retract=args.safe_retract, fast_feed=args.fast_feed,
                       slow_feed=args.slow_feed, retract_feed=args.retract_feed,
                       wcs_slot=args.wcs_slot, offset_axis=args.offset_axis,
                       offset_value=args.offset_value, purpose=args.purpose)
    if command == "probe-work-z":
        _require_confirmation(args)
        return _invoke(client, args, "probe-work-z")
    if command == "abort-probe":
        _require_confirmation(args)
        return _invoke(client, args, "abort-probe", reason=args.reason)
    if command in {"spindle-start", "spindle-stop"}:
        _require_confirmation(args)
        return _invoke(client, args, command, **({"rpm": args.rpm} if command == "spindle-start" else {}))
    if command == "save-profile":
        snapshot = client.snapshot()
        current = snapshot.get("profile", {}) if isinstance(snapshot.get("profile"), dict) else {}
        proposed = {"name": args.name, "travel_x": args.travel_x, "travel_y": args.travel_y,
                    "travel_z": args.travel_z, "safe_z": args.safe_z}
        if not args.apply:
            return _preview(snapshot, "machine profile", proposed, current)
        _require_confirmation(args)
        return _invoke(client, args, "save-profile", **proposed)
    if command == "save-homing":
        declarations = json.loads(args.declarations.read_text(encoding="utf-8"))
        if not args.apply:
            snapshot = client.snapshot()
            current = snapshot.get("machine", {}).get("axes", {}) if isinstance(snapshot.get("machine"), dict) else {}
            return _preview(snapshot, "homing declarations", declarations, current)
        _require_confirmation(args)
        return _invoke(client, args, "save-homing-declarations", declarations=declarations)
    if command == "save-z-plate":
        values = {"thickness": args.thickness, "active_low": args.active_low,
                  "fast_feed": args.fast_feed, "slow_feed": args.slow_feed,
                  "max_search": args.max_search, "retract": args.retract,
                  "safe_retract": args.safe_retract, "tolerance": args.tolerance}
        if not args.apply:
            snapshot = client.snapshot()
            return _preview(snapshot, "Z touch plate settings", values,
                            snapshot.get("safety", {}) if isinstance(snapshot.get("safety"), dict) else {})
        _require_confirmation(args)
        return _invoke(client, args, "save-z-plate-settings", **values)
    if command == "simulation":
        payload = {"operation": args.operation, "speed": args.speed,
                   "workpiece": args.workpiece, "reset_asserted": args.reset_asserted}
        if args.path is not None:
            payload["path"] = str(args.path)
        return _invoke(client, args, "simulation", **payload)
    if command == "simulation-limit":
        return _invoke(client, args, "simulation-limit", axis=args.axis, active=args.active)
    if command == "commission-plate":
        _require_confirmation(args)
        return _invoke(client, args, "commission-plate")
    if command == "auto-xyz-start":
        _require_confirmation(args)
        return _invoke(client, args, "auto-xyz-start", x=args.x, y=args.y, z=args.z)
    if command == "auto-xyz-abort":
        return _invoke(client, args, "auto-xyz-abort")
    if command in {"touch-input-test", "touch-commission", "touch-ack-remove"}:
        _require_confirmation(args)
        return _invoke(client, args, command)
    if command == "export-simulation-evidence":
        return _invoke(client, args, "export-simulation-evidence", path=str(args.path))
    if command == "shutdown":
        _require_confirmation(args)
        return client.shutdown(safe_abort=args.safe_abort)
    raise ValueError(command)


def _emit(value: Any, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))
    elif isinstance(value, dict):
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    else:
        print(value)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = BackendClient(args.root)
        client.attach()
        value = _result(client, args)
    except CliAuthorizationError as exc:
        value = {"accepted": False, "error": {"code": "authorization_required", "message": str(exc), "retryable": False}, "message": str(exc)}
        _emit(value, json_mode=bool(getattr(args, "json_mode", False)))
        return 2
    except BackendRequestRejected as exc:
        detail = exc.error.to_dict()
        value = {"accepted": False, "error": detail, "message": detail["message"]}
        _emit(value, json_mode=bool(getattr(args, "json_mode", False)))
        return 2
    except BackendIncompatible as exc:
        value = {"accepted": False, "error": {"code": "incompatible_backend", "message": str(exc), "retryable": False}, "message": str(exc)}
        _emit(value, json_mode=bool(getattr(args, "json_mode", False)))
        return 2
    except BackendRootAmbiguous as exc:
        value = {"accepted": False, "error": {"code": "ambiguous_backend_root", "message": str(exc), "retryable": False}, "message": str(exc)}
        _emit(value, json_mode=bool(getattr(args, "json_mode", False)))
        return 2
    except (BackendUnavailable, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        value = {"accepted": False, "error": {"code": "backend_unavailable", "message": str(exc), "retryable": True}, "message": str(exc)}
        _emit(value, json_mode=bool(getattr(args, "json_mode", False)))
        return 2
    _emit(value, json_mode=bool(getattr(args, "json_mode", False)))
    if isinstance(value, dict) and value.get("accepted") is False and not value.get("preview"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
