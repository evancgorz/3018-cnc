"""Strict machine-scoped persistence for commissioning and fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MachineRecordStore:
    """Store arbitrary validated JSON records under stable machine IDs."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, machine_id: str) -> dict[str, Any] | None:
        data = self._read()
        record = data.get("machines", {}).get(machine_id)
        return dict(record) if record is not None else None

    def save(self, machine_id: str, record: dict[str, Any]) -> None:
        if not machine_id.strip():
            raise ValueError("Machine ID cannot be empty")
        if not isinstance(record, dict):
            raise ValueError("Machine record must be an object")
        data = self._read()
        data.setdefault("machines", {})[machine_id] = record
        self._write(data)

    def clear(self, machine_id: str) -> None:
        data = self._read()
        if machine_id in data.get("machines", {}):
            del data["machines"][machine_id]
            self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "machines": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version", 1) != 1 or not isinstance(data.get("machines", {}), dict):
            raise ValueError("Invalid machine record store")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
