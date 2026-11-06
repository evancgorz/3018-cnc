"""Pure projection of an authoritative machine position into a travel envelope."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from ..grbl import Position


@dataclass(frozen=True)
class EnvelopeMarker:
    """A truthful marker projection for the machine-envelope preview.

    ``x``/``y`` retain the normalized machine coordinate even when it is out
    of bounds.  ``render_x``/``render_y`` are the safe edge location used by
    a renderer, and ``direction`` explains which side is out of bounds.
    """

    state: str
    reason: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    render_x: float | None = None
    render_y: float | None = None
    direction: str = ""
    session_id: str = ""

    @property
    def visible(self) -> bool:
        return self.state in {"visible", "out_of_bounds"}

    @property
    def known(self) -> bool:
        return self.state != "unknown"

    @property
    def out_of_bounds(self) -> bool:
        return self.state == "out_of_bounds"

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "visible": self.visible,
            "known": self.known,
            "out_of_bounds": self.out_of_bounds,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "render_x": self.render_x,
            "render_y": self.render_y,
            "direction": self.direction,
            "session_id": self.session_id,
        }


def project_machine_position(
    position: Position | None,
    travel_x: float,
    travel_y: float,
    travel_z: float,
    *,
    connected: bool,
    status_fresh: bool,
    session_id: str = "",
    expected_session_id: str = "",
) -> EnvelopeMarker:
    """Project fresh backend ``MPos`` into a stable envelope coordinate.

    Missing, disconnected, stale, or session-mismatched facts are unknown.
    The helper deliberately does not clamp the authoritative normalized
    values; only the separate render coordinates are edge-clamped.
    """

    if not connected:
        return EnvelopeMarker("unknown", "Controller disconnected", session_id=session_id)
    if expected_session_id and session_id != expected_session_id:
        return EnvelopeMarker("unknown", "Backend session changed; waiting for fresh MPos", session_id=session_id)
    if not status_fresh:
        return EnvelopeMarker("unknown", "MPos is stale; waiting for a fresh status", session_id=session_id)
    if position is None:
        return EnvelopeMarker("unknown", "MPos is unavailable", session_id=session_id)
    if not all(math.isfinite(float(value)) for value in (travel_x, travel_y, travel_z, position.x, position.y, position.z)):
        return EnvelopeMarker("unknown", "Envelope coordinates are invalid", session_id=session_id)
    if travel_x <= 0 or travel_y <= 0 or travel_z <= 0:
        return EnvelopeMarker("unknown", "Machine travel envelope is unavailable", session_id=session_id)

    x = float(position.x) / float(travel_x)
    y = float(position.y) / float(travel_y)
    out: list[str] = []
    if x < 0:
        out.append("X−")
    elif x > 1:
        out.append("X+")
    if y < 0:
        out.append("Y−")
    elif y > 1:
        out.append("Y+")
    direction = " / ".join(out)
    state = "out_of_bounds" if out else "visible"
    reason = f"MPos X{position.x:.2f} Y{position.y:.2f} Z{position.z:.2f}"
    if out:
        reason += f" · outside envelope ({direction})"
    return EnvelopeMarker(
        state,
        reason,
        x=x,
        y=y,
        z=float(position.z),
        render_x=min(1.0, max(0.0, x)),
        render_y=min(1.0, max(0.0, y)),
        direction=direction,
        session_id=session_id,
    )


__all__ = ["EnvelopeMarker", "project_machine_position"]
