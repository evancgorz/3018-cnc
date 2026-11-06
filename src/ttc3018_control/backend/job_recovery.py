"""Durable, deliberately non-resumable job-recovery evidence.

The controller's ``ok`` acknowledgements prove that a line was accepted into
GRBL, not that its motion was completed.  This store therefore preserves useful
restart context for people and agents without ever presenting an accepted-line
counter as an executable resume cursor.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


RECOVERY_SCHEMA_VERSION = 1


def empty_pause_fence() -> dict[str, Any]:
    """Review-only continuation constraints; these fields never authorize resume."""
    return {
        "automatic_resume_allowed": False,
        "resume_supported": False,
        "accepted_command_count_is_physical_position": False,
        "requires_same_backend_session": True,
        "requires_same_machine_id": True,
        "requires_same_run_id": True,
        "requires_same_program_sha256": True,
        "requires_fresh_controller_hold": True,
        "requires_operator_review_after_disconnect_or_restart": True,
        "requires_homing_after_disconnect_or_restart": True,
        "requires_work_zero_reconfirmation_after_disconnect_or_restart": True,
        "requires_tool_verification_before_continuation": True,
        "backend_restart_observed": False,
    }


def empty_pause_bookmark() -> dict[str, Any]:
    return {
        "state": "none",
        # `confirmed` is historical evidence that a fresh Hold followed the
        # pause request. `live_hold_confirmed` is deliberately cleared at load.
        "confirmed": False,
        "live_hold_confirmed": False,
        "current_for_active_run": False,
        "confirmed_at_utc": "",
        "confirmation_source": "",
        "run_id": "",
        "machine_id": "",
        "source_sha256": "",
        "filename": "",
        "accepted_commands": 0,
        "sent_commands": 0,
        "total_commands": 0,
        "controller_state": "",
        "session_generation": None,
        "position_context": {},
        "tool_context": {},
        "recovery_fence": empty_pause_fence(),
    }


def _restore_pause_bookmark(value: object) -> dict[str, Any]:
    """Load display evidence while refusing to restore any live/resume authority."""
    bookmark = empty_pause_bookmark()
    if not isinstance(value, dict):
        return bookmark
    for key in (
        "confirmed_at_utc", "confirmation_source", "run_id", "machine_id",
        "source_sha256", "filename", "controller_state",
    ):
        if isinstance(value.get(key), str):
            bookmark[key] = value[key][:512]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", bookmark["source_sha256"]):
        bookmark["source_sha256"] = ""
    for key in ("accepted_commands", "sent_commands", "total_commands"):
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            bookmark[key] = item
    session_generation = value.get("session_generation")
    if isinstance(session_generation, int) and not isinstance(session_generation, bool) and session_generation >= 0:
        bookmark["session_generation"] = session_generation
    position_context = value.get("position_context")
    if isinstance(position_context, dict):
        safe_position = {"position_is_resume_cursor": False}
        for name in ("machine_position", "work_position", "work_offset"):
            item = position_context.get(name)
            if not isinstance(item, dict):
                continue
            coordinates = {}
            for axis in ("x", "y", "z"):
                coordinate = item.get(axis)
                if isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool) and math.isfinite(coordinate):
                    coordinates[axis] = coordinate
            if len(coordinates) == 3:
                safe_position[name] = coordinates
        bookmark["position_context"] = safe_position
    tool_context = value.get("tool_context")
    if isinstance(tool_context, dict):
        provenance_hash = str(tool_context.get("provenance_file_sha256", ""))[:64]
        provenance_hash_valid = bool(
            bookmark["source_sha256"]
            and provenance_hash.lower() == bookmark["source_sha256"].lower()
        )
        safe_tool = {
            "program_sha256": bookmark["source_sha256"],
            "provenance_report_state": (str(tool_context.get("provenance_report_state", "unavailable"))[:64]
                                         if provenance_hash_valid else "unavailable"),
            "provenance_report_name": (str(tool_context.get("provenance_report_name", ""))[:256]
                                        if provenance_hash_valid else ""),
            "provenance_file_sha256": provenance_hash if provenance_hash_valid else "",
            "reported_tool_details": [str(item)[:256] for item in tool_context.get("reported_tool_details", [])[:4]
                                       if isinstance(item, str)]
                if provenance_hash_valid and isinstance(tool_context.get("reported_tool_details"), list) else [],
            "physical_tool_verified": False,
            "verification_required_before_continuation": True,
        }
        offset = tool_context.get("active_tool_length_offset_mm")
        if isinstance(offset, (int, float)) and not isinstance(offset, bool) and math.isfinite(offset):
            safe_tool["active_tool_length_offset_mm"] = offset
        bookmark["tool_context"] = safe_tool
    if (
        value.get("confirmed") is True
        and bookmark["source_sha256"]
        and bookmark["run_id"]
        and bookmark["machine_id"]
        and bookmark["controller_state"] in {"Hold", "Hold:0"}
        and bookmark["confirmation_source"] == "fresh_controller_status_after_pause_request"
    ):
        bookmark.update({
            "state": "historical",
            "confirmed": True,
            "live_hold_confirmed": False,
            "current_for_active_run": False,
        })
    return bookmark


def empty_recovery() -> dict[str, Any]:
    return {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "state": "none",
        "run_id": "",
        "machine_id": "",
        "source_sha256": "",
        "filename": "",
        "path": "",
        "accepted_commands": 0,
        "sent_commands": 0,
        "total_commands": 0,
        "reason": "",
        "requires_operator_review": False,
        "resume_supported": False,
        "pause_bookmark": empty_pause_bookmark(),
        "persistence_error": "",
    }


class JobRecoveryStore:
    """Atomic JSON store for last-run recovery context.

    It never stores a position, work offset, or authorization token; all of
    those are live-machine facts and must be re-established normally.
    """

    filename = "job-recovery.json"

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / self.filename

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return empty_recovery()
        if not isinstance(raw, dict) or raw.get("schema_version") != RECOVERY_SCHEMA_VERSION:
            return empty_recovery()
        record = empty_recovery()
        record.update({key: raw[key] for key in record if key in raw})
        record["pause_bookmark"] = _restore_pause_bookmark(raw.get("pause_bookmark"))
        # A backend restart cannot prove that a formerly active operation
        # continued. Preserve the evidence as review-required interruption.
        if record["state"] in {"running", "paused", "draining"}:
            record["state"] = "interrupted"
            record["reason"] = "Backend restarted while the prior job was active; physical motion is unverified"
            record["requires_operator_review"] = True
            bookmark = record["pause_bookmark"]
            if bookmark["confirmed"]:
                bookmark["state"] = "interrupted_after_restart"
                bookmark["recovery_fence"]["backend_restart_observed"] = True
        record["resume_supported"] = False
        return record

    def save(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record, sort_keys=True, indent=2) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=".job-recovery-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
