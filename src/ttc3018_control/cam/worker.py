"""Isolated background execution for offline CAM review bundles."""

from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


DEFAULT_TIMEOUT_SECONDS = 15 * 60
WORKER_STALE_SECONDS = 30
MAX_CONCURRENT_JOBS = 4
MAX_SPEC_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_ALLOWED_STATES = {"queued", "running", "cancelled", "failed", "completed"}


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    try:
        for attempt in range(50):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)
    finally:
        temporary.unlink(missing_ok=True)


def _read_state(path: Path) -> dict:
    for attempt in range(50):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)
    if not isinstance(value, dict) or value.get("state") not in _ALLOWED_STATES:
        raise ValueError(f"Invalid CAM worker state at {path}")
    return value


def _alive(pid: object) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_generator(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(child.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5, check=False,
                           creationflags=creationflags)
        except (OSError, subprocess.TimeoutExpired):
            child.terminate()
    else:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except OSError:
            child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()


def _job_path(root: Path, job_id: str) -> Path:
    try:
        canonical = str(uuid.UUID(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid CAM job ID") from exc
    if canonical != job_id.lower():
        raise ValueError("Invalid CAM job ID")
    return root.resolve() / "jobs" / canonical


def _source_from_spec(spec_path: Path, spec: dict) -> tuple[dict, bytes | None]:
    if not isinstance(spec, dict):
        raise ValueError("Design spec must contain a JSON object")
    source = spec.get("source")
    source_data = None
    copied = dict(spec)
    if source is not None:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Design source must be a relative file path")
        source_path = Path(source)
        if source_path.is_absolute():
            raise ValueError("Design source must be relative to the spec")
        resolved = (spec_path.parent / source_path).resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Source must be a regular file under 64 MiB")
        extension = resolved.suffix.lower()
        if not extension or len(extension) > 12:
            raise ValueError("Source file must have a short extension")
        source_data = resolved.read_bytes()
        copied["source"] = "source" + extension
    return copied, source_data


def _active_jobs(root: Path) -> int:
    jobs = root / "jobs"
    if not jobs.exists():
        return 0
    count = 0
    for state_path in jobs.glob("*/state.json"):
        try:
            if _read_state(state_path).get("state") in {"queued", "running"}:
                count += 1
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return count


def submit(spec_path: Path, root: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Snapshot inputs and queue a detached, machine-independent CAM process."""
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be between 1 and 3600")
    source_path = spec_path.resolve(strict=True)
    raw_spec = source_path.read_bytes()
    if len(raw_spec) > MAX_SPEC_BYTES:
        raise ValueError("Design spec exceeds the 1 MiB limit")
    from .build import resolve_design_setup

    spec = resolve_design_setup(source_path, json.loads(raw_spec.decode("utf-8-sig")))
    snapshot, source_bytes = _source_from_spec(source_path, spec)
    root = root.resolve()
    if _active_jobs(root) >= MAX_CONCURRENT_JOBS:
        raise ValueError("CAM queue is full; wait for a job to finish before submitting another")
    job_id = str(uuid.uuid4())
    job = _job_path(root, job_id)
    job.mkdir(parents=True, exist_ok=False)
    inputs = job / "input"
    inputs.mkdir()
    _write_json(inputs / "design.json", snapshot)
    if source_bytes is not None:
        (inputs / snapshot["source"]).write_bytes(source_bytes)
    record = {
        "job_id": job_id,
        "state": "queued",
        "phase": "waiting for worker",
        "progress_percent": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "timeout_seconds": timeout_seconds,
        "spec_sha256": __import__("hashlib").sha256(raw_spec).hexdigest(),
        "source_sha256": (__import__("hashlib").sha256(source_bytes).hexdigest()
                          if source_bytes is not None else None),
        "bundle_path": None,
        "error": None,
        "worker_pid": None,
    }
    _write_json(job / "state.json", record)
    command = [sys.executable, "-m", "ttc3018_control.cam.worker", "run", job_id, "--root", str(root)]
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command, cwd=str(Path(__file__).resolve().parents[2]), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        record.update(state="failed", phase="worker could not start", error=str(exc),
                      updated_at=time.time())
        _write_json(job / "state.json", record)
        raise
    record["worker_pid"] = process.pid
    record["updated_at"] = time.time()
    _write_json(job / "state.json", record)
    (job / "start.signal").touch()
    return record


def status(root: Path, job_id: str) -> dict:
    job = _job_path(root, job_id)
    record = _read_state(job / "state.json")
    if (record["state"] in {"queued", "running"} and
            (time.time() - record.get("updated_at", 0) > WORKER_STALE_SECONDS or
             not _alive(record.get("worker_pid")))):
        record.update(state="failed", phase="worker stopped unexpectedly",
                      error="Background CAM worker exited before publishing a complete bundle.",
                      updated_at=time.time())
        _write_json(job / "state.json", record)
    return record


def cancel(root: Path, job_id: str) -> dict:
    job = _job_path(root, job_id)
    record = status(root, job_id)
    if record["state"] in {"completed", "cancelled", "failed"}:
        return record
    (job / "cancel.requested").write_text("cancel\n", encoding="ascii")
    record["phase"] = "cancellation requested"
    record["updated_at"] = time.time()
    _write_json(job / "state.json", record)
    return record


def retry(root: Path, job_id: str) -> dict:
    """Retry a failed/cancelled job from its immutable input snapshot as a new ID."""
    job = _job_path(root, job_id)
    record = status(root, job_id)
    if record["state"] not in {"failed", "cancelled"}:
        raise ValueError("Only failed or cancelled CAM jobs can be retried")
    return submit(job / "input" / "design.json", root,
                  timeout_seconds=int(record["timeout_seconds"]))


def _run(job_id: str, root: Path) -> int:
    job = _job_path(root, job_id)
    state_path = job / "state.json"
    start_signal = job / "start.signal"
    startup_deadline = time.monotonic() + 10
    while not start_signal.exists() and not (job / "cancel.requested").exists():
        if time.monotonic() >= startup_deadline:
            return 2
        time.sleep(0.02)
    record = _read_state(state_path)
    if (job / "cancel.requested").exists():
        record.update(state="cancelled", phase="cancelled before generation",
                      updated_at=time.time(), worker_pid=os.getpid())
        _write_json(state_path, record)
        return 0
    if record["state"] != "queued":
        return 2
    record.update(state="running", phase="generating and verifying candidate",
                  progress_percent=10, worker_pid=os.getpid(), updated_at=time.time())
    _write_json(state_path, record)
    command = [sys.executable, "-m", "ttc3018_control.cam.build",
               str(job / "input" / "design.json"), str(job / ".building")]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    child = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[2]),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, creationflags=creationflags,
                             start_new_session=(os.name != "nt"))
    deadline = time.monotonic() + int(record["timeout_seconds"])
    last_heartbeat = time.monotonic()
    try:
        while child.poll() is None:
            if time.monotonic() - last_heartbeat >= 5:
                record["updated_at"] = time.time()
                _write_json(state_path, record)
                last_heartbeat = time.monotonic()
            if (job / "cancel.requested").exists():
                _terminate_generator(child)
                child.communicate(timeout=5)
                (job / ".building").exists() and shutil.rmtree(job / ".building")
                record.update(state="cancelled", phase="cancelled by request", progress_percent=0,
                              error=None, updated_at=time.time(), bundle_path=None)
                _write_json(state_path, record)
                return 0
            if time.monotonic() >= deadline:
                _terminate_generator(child)
                _, stderr = child.communicate(timeout=5)
                record.update(state="failed", phase="time limit exceeded", progress_percent=0,
                              error=f"CAM generation exceeded {record['timeout_seconds']} seconds. "
                                    f"{stderr[-2000:]}".strip(), updated_at=time.time())
                _write_json(state_path, record)
                return 1
            time.sleep(0.1)
        stdout, stderr = child.communicate()
        if child.returncode != 0:
            if (job / ".building").exists():
                shutil.rmtree(job / ".building")
            record.update(state="failed", phase="generation rejected",
                          error=(stderr or stdout)[-4000:].strip() or
                                f"CAM generator exited with code {child.returncode}",
                          updated_at=time.time())
            _write_json(state_path, record)
            return 1

        if (job / "cancel.requested").exists():
            shutil.rmtree(job / ".building")
            record.update(state="cancelled", phase="cancelled by request", progress_percent=0,
                          error=None, updated_at=time.time(), bundle_path=None)
            _write_json(state_path, record)
            return 0
        record.update(phase="publishing immutable review bundle",
                      progress_percent=90, updated_at=time.time())
        _write_json(state_path, record)
        final = job / "bundle"
        if final.exists():
            raise FileExistsError(final)
        (job / ".building").replace(final)
        manifest = json.loads((final / "report.json").read_text(encoding="utf-8"))
        record.update(state="completed", phase="ready for review", progress_percent=100,
                      bundle_path=str(final), gcode_sha256=manifest["sha256"]["candidate-review-only.nc"],
                      error=None, updated_at=time.time())
        _write_json(state_path, record)
        return 0
    except BaseException as exc:
        if child.poll() is None:
            _terminate_generator(child)
            child.communicate()
        if (job / ".building").exists():
            shutil.rmtree(job / ".building", ignore_errors=True)
        record.update(state="failed", phase="worker error", progress_percent=0,
                      error=f"{type(exc).__name__}: {exc}"[:4000], updated_at=time.time())
        _write_json(state_path, record)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Queue and manage offline CAM jobs.")
    sub = parser.add_subparsers(dest="command", required=True)
    queued = sub.add_parser("submit", help="snapshot inputs and queue a CAM job")
    queued.add_argument("spec", type=Path)
    queued.add_argument("--root", type=Path, default=Path("artifacts/cam-runs"))
    queued.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    poll = sub.add_parser("status", help="read job progress or result")
    poll.add_argument("job_id")
    poll.add_argument("--root", type=Path, default=Path("artifacts/cam-runs"))
    stop = sub.add_parser("cancel", help="request cancellation")
    stop.add_argument("job_id")
    stop.add_argument("--root", type=Path, default=Path("artifacts/cam-runs"))
    again = sub.add_parser("retry", help="retry from saved inputs with a new output ID")
    again.add_argument("job_id")
    again.add_argument("--root", type=Path, default=Path("artifacts/cam-runs"))
    worker = sub.add_parser("run", help=argparse.SUPPRESS)
    worker.add_argument("job_id")
    worker.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            result = submit(args.spec, args.root, timeout_seconds=args.timeout)
        elif args.command == "status":
            result = status(args.root, args.job_id)
        elif args.command == "cancel":
            result = cancel(args.root, args.job_id)
        elif args.command == "retry":
            result = retry(args.root, args.job_id)
        else:
            return _run(args.job_id, args.root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Offline CAM worker: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
