"""Entry point for the persistent, headless Pine backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import sys
import threading

from .runtime import BackendRuntime
from .server import BackendServer
from .discovery import BackendRootRegistration, BackendRootRegistry, default_data_root
from .data_migration import assert_data_root_not_migrating


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pine-backend")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="application data root")
    parser.add_argument("--no-poll", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = default_data_root(args.root)
    assert_data_root_not_migrating(root)
    runtime = BackendRuntime(root)
    server = BackendServer(runtime, root=root)
    stop = threading.Event()

    def request_stop(*_args):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, request_stop)
        except (ValueError, OSError):
            pass
    record = server.start(poll=not args.no_poll)
    registration = BackendRootRegistration(str(root), record.pid, record.session_id)
    registry = None
    registered = False
    try:
        registry = BackendRootRegistry()
        registry.register(registration)
        registered = True
    except (OSError, ValueError) as exc:
        # The per-root record still works with an explicit --root. Keep the
        # server available but explain why cross-directory lookup is absent.
        print(f"Pine backend root locator unavailable: {exc}", file=sys.stderr, flush=True)
    print(json.dumps({"data_root": str(root), **record.public_dict()}, separators=(",", ":")), flush=True)
    try:
        stop.wait()
    finally:
        server.stop()
        if registered and registry is not None:
            registry.unregister(registration)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
