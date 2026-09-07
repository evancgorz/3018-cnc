"""Canonical semantic trace, replay, and evidence export."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any, Iterable

from .models import TraceEvent


class TraceRecorder:
    def __init__(self, *, source: str = "backend") -> None:
        self.source = source
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def record(self, time_ns: int, kind: str, payload: dict[str, Any] | None = None, *, source: str | None = None) -> TraceEvent:
        with self._lock:
            event = TraceEvent(len(self._events) + 1, int(time_ns), kind, payload or {}, source or self.source)
            self._events.append(event)
            return event

    def canonical(self, *, normalize: bool = True) -> list[dict[str, Any]]:
        values = [event.to_dict() for event in self.events]
        if not normalize:
            return values
        for event in values:
            payload = event.get("payload", {})
            for key in ("pid", "port", "wall_time", "timestamp", "absolute_path", "session_id"):
                payload.pop(key, None)
            event["payload"] = payload
        return values

    def digest(self) -> str:
        data = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "events": self.canonical()}, indent=2) + "\n", encoding="utf-8")

    def export_markdown(self, path: Path, *, title: str = "Digital twin trace") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {title}", "", f"Events: {len(self.events)}", f"Canonical SHA-256: `{self.digest()}`", "", "| # | time (ns) | source | event |", "|---:|---:|---|---|"]
        lines.extend(f"| {e.sequence} | {e.time_ns} | {e.source} | {e.kind} |" for e in self.events)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_trace(path: Path) -> tuple[TraceEvent, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("events"), list):
        raise ValueError("Unsupported or malformed trace")
    events = []
    for item in data["events"]:
        if not isinstance(item, dict) or not isinstance(item.get("sequence"), int):
            raise ValueError("Malformed trace event")
        events.append(TraceEvent(int(item["sequence"]), int(item["time_ns"]), str(item["kind"]), dict(item.get("payload", {})), str(item.get("source", "unknown"))))
    if [event.sequence for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("Trace sequence is not contiguous")
    return tuple(events)


def compare_traces(left: Iterable[TraceEvent], right: Iterable[TraceEvent]) -> tuple[str, ...]:
    a, b = list(left), list(right)
    differences: list[str] = []
    if len(a) != len(b):
        differences.append(f"event count differs: {len(a)} != {len(b)}")
    for index, (one, two) in enumerate(zip(a, b), start=1):
        if one.kind != two.kind or one.source != two.source:
            differences.append(f"event {index} identity differs: {one.kind}/{one.source} != {two.kind}/{two.source}")
        if one.payload != two.payload:
            differences.append(f"event {index} payload differs")
    return tuple(differences)
