"""Stable machine-status facts used to bind operator confirmations.

GRBL status reports contain both safety-relevant state and volatile telemetry
such as planner/RX buffer counts and overrides.  This module projects only the
facts that should invalidate a confirmation when they change.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import math
from typing import Any

from ttc3018_control.grbl import GrblStatus


_MISSING = object()


def _type_name(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _numeric_fact(value: Any) -> dict[str, object]:
    if value is _MISSING or value is None:
        return {"kind": "missing"}
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"kind": "unknown", "type": _type_name(value)}
    if isinstance(value, float) and not math.isfinite(value):
        return {"kind": "nonfinite", "value": str(value)}
    decimal_value = Decimal(str(value))
    if decimal_value == 0:
        canonical = "0"
    else:
        canonical = format(decimal_value.normalize(), "f")
    return {"kind": "finite", "value": canonical}


def _position_axes(position: Any) -> list[dict[str, object]] | None:
    if position is None:
        return None
    try:
        values = (position.x, position.y, position.z)
    except AttributeError:
        return None
    return [_numeric_fact(value) for value in values]


def _canonical_machine_position(status: Any) -> dict[str, object]:
    machine_position = getattr(status, "machine_position", _MISSING)
    if machine_position is not _MISSING and machine_position is not None:
        axes = _position_axes(machine_position)
        if axes is None:
            return {"kind": "unknown", "type": _type_name(machine_position)}
        return {"kind": "position", "axes": axes}

    work_position = getattr(status, "work_position", _MISSING)
    work_offset = getattr(status, "work_offset", _MISSING)
    work_axes = _position_axes(work_position) if work_position is not _MISSING else None
    offset_axes = _position_axes(work_offset) if work_offset is not _MISSING else None
    if work_axes is None and offset_axes is None:
        return {"kind": "missing"}

    if work_axes is not None and offset_axes is not None:
        sums: list[dict[str, object]] = []
        for work_axis, offset_axis in zip(work_axes, offset_axes, strict=True):
            if work_axis.get("kind") == "finite" and offset_axis.get("kind") == "finite":
                total = Decimal(str(work_axis["value"])) + Decimal(str(offset_axis["value"]))
                canonical = "0" if total == 0 else format(total.normalize(), "f")
                sums.append({"kind": "finite", "value": canonical})
            else:
                sums.append({"kind": "unknown_sum", "work": work_axis, "offset": offset_axis})
        if all(axis.get("kind") == "finite" for axis in sums):
            # Match direct MPos facts so changing the controller's report mask
            # between MPos and WPos+WCO does not invalidate an unchanged pose.
            return {"kind": "position", "axes": sums}
        return {"kind": "derived_unknown", "axes": sums}

    return {
        "kind": "incomplete",
        "work_position": work_axes if work_axes is not None else {"kind": "missing"},
        "work_offset": offset_axes if offset_axes is not None else {"kind": "missing"},
    }


def _text_fact(value: Any) -> dict[str, object]:
    if value is _MISSING or value is None:
        return {"kind": "missing"}
    if not isinstance(value, str):
        return {"kind": "unknown", "type": _type_name(value)}
    return {"kind": "value", "value": value}


def _pins_fact(status: Any) -> dict[str, object]:
    pins = getattr(status, "pins", _MISSING)
    fields = getattr(status, "fields", _MISSING)

    # GrblStatus uses an empty string as its default for Pn, but the parser
    # retains the original field map. An omitted Pn is unknown, while an
    # explicit empty Pn means the controller reported no active pins.
    if isinstance(fields, Mapping) and "Pn" not in fields and (pins is _MISSING or pins == ""):
        return {"kind": "missing"}
    if pins is _MISSING and isinstance(fields, Mapping) and "Pn" in fields:
        pins = fields["Pn"]
    pin_fact = _text_fact(pins)
    if pin_fact.get("kind") != "value":
        return pin_fact
    text = str(pin_fact["value"]).strip().upper()
    return {"kind": "value", "value": "".join(sorted(text))}


def meaningful_status_facts(status: GrblStatus | None) -> dict[str, object]:
    """Return stable, JSON-safe status facts relevant to a confirmation.

    The projection deliberately excludes raw ``fields`` and does not include
    work position or WCO separately. Position is represented in machine space
    using MPos, or derived from WPos+WCO when MPos is unavailable. Missing,
    malformed, and non-finite values remain explicit markers instead of being
    treated as safe numeric defaults.
    """
    if status is None:
        return {
            "state": {"kind": "missing"},
            "machine_position": {"kind": "missing"},
            "feed": {"kind": "missing"},
            "spindle": {"kind": "missing"},
            "pins": {"kind": "missing"},
        }

    return {
        "state": _text_fact(getattr(status, "state", _MISSING)),
        "machine_position": _canonical_machine_position(status),
        "feed": _numeric_fact(getattr(status, "feed", _MISSING)),
        "spindle": _numeric_fact(getattr(status, "spindle", _MISSING)),
        "pins": _pins_fact(status),
    }
