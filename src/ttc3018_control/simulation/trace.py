"""Canonical semantic trace, replay, and evidence export."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import threading
from typing import Any, Iterable

from .models import TraceEvent

TRACE_SCHEMA_VERSION = 1
# These are the only fields deliberately removed from semantic payloads.
# Everything else—including commands, responses, status, motion, hazards,
# faults, intents, and final state—remains evidence-bearing.
DECLARED_NOISE_FIELDS = frozenset({
    "pid", "port", "wall_time", "timestamp", "absolute_path", "session_id",
})


class TraceRecorder:
    def __init__(self, *, source: str = "backend", max_events: int | None = None) -> None:
        if max_events is not None and max_events <= 0:
            raise ValueError("Trace max_events must be positive")
        self.source = source
        self.max_events = max_events
        self.truncated = False
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def record(self, time_ns: int, kind: str, payload: dict[str, Any] | None = None, *, source: str | None = None) -> TraceEvent:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("Trace event kind must be non-empty text")
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("Trace event payload must be a mapping")
        if int(time_ns) < 0:
            raise ValueError("Trace event time must be nonnegative")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            raise ValueError("Trace event source must be non-empty text")
        _validate_json_value(payload or {})
        with self._lock:
            if self.max_events is not None and len(self._events) >= self.max_events:
                self.truncated = True
                return self._events[-1]
            event = TraceEvent(len(self._events) + 1, int(time_ns), kind.strip(), _canonical_value(payload or {}, normalize=False), source or self.source)
            self._events.append(event)
            return event

    def canonical(self, *, normalize: bool = True) -> list[dict[str, Any]]:
        values = [event.to_dict() for event in self.events]
        if not normalize:
            return values
        values = _canonical_value(values, normalize=True)
        return values

    def digest(self) -> str:
        data = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": TRACE_SCHEMA_VERSION, "events": self.canonical()}, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    def export_markdown(self, path: Path, *, title: str = "Digital twin trace") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {title}", "", f"Events: {len(self.events)}", f"Canonical SHA-256: `{self.digest()}`", "", "| # | time (ns) | source | event |", "|---:|---:|---|---|"]
        lines.extend(f"| {e.sequence} | {e.time_ns} | {e.source} | {e.kind} |" for e in self.events)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_trace(path: Path) -> tuple[TraceEvent, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON constant {value}")))
    except json.JSONDecodeError as exc:
        raise ValueError("Truncated or malformed trace JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != TRACE_SCHEMA_VERSION or not isinstance(data.get("events"), list):
        raise ValueError("Unsupported or malformed trace")
    events = []
    previous_time = -1
    for item in data["events"]:
        if not isinstance(item, dict) or not isinstance(item.get("sequence"), int) or isinstance(item.get("sequence"), bool):
            raise ValueError("Malformed trace event")
        if not isinstance(item.get("time_ns"), int) or isinstance(item.get("time_ns"), bool) or item["time_ns"] < 0:
            raise ValueError("Malformed trace event time")
        if item["time_ns"] < previous_time:
            raise ValueError("Trace time is not monotonic")
        if not isinstance(item.get("kind"), str) or not item["kind"].strip():
            raise ValueError("Malformed trace event kind")
        if not isinstance(item.get("source", "unknown"), str) or not str(item.get("source", "unknown")).strip():
            raise ValueError("Malformed trace event source")
        if not isinstance(item.get("payload", {}), dict):
            raise ValueError("Malformed trace event payload")
        _validate_json_value(item.get("payload", {}))
        events.append(TraceEvent(int(item["sequence"]), int(item["time_ns"]), item["kind"].strip(),
                                 _canonical_value(item.get("payload", {}), normalize=False), item.get("source", "unknown")))
        previous_time = item["time_ns"]
    if [event.sequence for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("Trace sequence is not contiguous")
    return tuple(events)


def compare_traces(left: Iterable[TraceEvent], right: Iterable[TraceEvent]) -> tuple[str, ...]:
    a, b = list(left), list(right)
    differences: list[str] = []
    if len(a) != len(b):
        differences.append(f"event count differs: {len(a)} != {len(b)}")
    for index, (one, two) in enumerate(zip(a, b), start=1):
        if one.time_ns != two.time_ns:
            differences.append(f"event {index} time differs: {one.time_ns} != {two.time_ns}")
        if one.kind != two.kind or one.source != two.source:
            differences.append(f"event {index} identity differs: {one.kind}/{one.source} != {two.kind}/{two.source}")
        if _canonical_value(one.payload, normalize=True) != _canonical_value(two.payload, normalize=True):
            differences.append(f"event {index} payload differs")
    return tuple(differences)


def first_trace_difference(left: Iterable[TraceEvent], right: Iterable[TraceEvent]) -> str | None:
    """Return the first semantic divergence, or ``None`` when traces match."""
    left_events, right_events = list(left), list(right)
    if len(left_events) != len(right_events):
        return f"event count differs: {len(left_events)} != {len(right_events)}"
    for index, (one, two) in enumerate(zip(left_events, right_events), start=1):
        if one.time_ns != two.time_ns:
            return f"event {index} time differs: {one.time_ns} != {two.time_ns}"
        if one.kind != two.kind or one.source != two.source:
            return f"event {index} identity differs: {one.kind}/{one.source} != {two.kind}/{two.source}"
        if _canonical_value(one.payload, normalize=True) != _canonical_value(two.payload, normalize=True):
            return f"event {index} payload differs"
    return None


def _canonical_value(value: Any, *, normalize: bool) -> Any:
    if isinstance(value, dict):
        return {key: _canonical_value(item, normalize=normalize)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if not (normalize and key in DECLARED_NOISE_FIELDS)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, normalize=normalize) for item in value]
    return value


def _validate_json_value(value: Any) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Trace payload keys must be text")
        for item in value.values():
            _validate_json_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Trace payload values must be finite")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ValueError("Trace payload contains unsupported value")


def replay_scenario_trace(trace: Path | Iterable[TraceEvent], *, scenario_name: str | None = None):
    """Replay a stored built-in scenario and report its first divergence."""
    from .scenarios import built_in_scenarios, run_headless_scenario
    expected = load_trace(trace) if isinstance(trace, Path) else tuple(trace)
    if scenario_name is None and expected:
        scenario_name = str(expected[0].payload.get("name", ""))
    scenario = next((item for item in built_in_scenarios() if item.name == scenario_name), None)
    if scenario is None:
        raise ValueError(f"Unknown replay scenario: {scenario_name or '<missing>'}")
    actual_result = run_headless_scenario(scenario)
    actual = tuple(TraceEvent(**item) for item in actual_result.trace_events)
    difference = first_trace_difference(expected, actual)
    return {
        "scenario": scenario.name,
        "seed": scenario.seed,
        "matched": difference is None,
        "expected_digest": hashlib.sha256(json.dumps(_canonical_value([event.to_dict() for event in expected], normalize=True), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "actual_digest": actual_result.trace_digest,
        "first_difference": difference,
    }
