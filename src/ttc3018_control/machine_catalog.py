"""Atomic persistence and legacy migration for saved machine definitions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from .machine_config import MachineDefinition
from .machine_state import MachineProfile


@dataclass(frozen=True)
class MachineCatalog:
    machines: tuple[MachineDefinition, ...]
    selected_machine_id: str

    def selected(self) -> MachineDefinition:
        for machine in self.machines:
            if machine.machine_id == self.selected_machine_id:
                return machine
        raise ValueError("Selected machine does not exist")


class MachineCatalogStore:
    def __init__(self, path: Path, legacy_profile_path: Path | None = None) -> None:
        self.path = path
        self.legacy_profile_path = legacy_profile_path

    def load(self) -> MachineCatalog:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            machines = tuple(MachineDefinition.from_dict(item) for item in data.get("machines", []))
            selected = str(data.get("selected_machine_id", ""))
            catalog = MachineCatalog(machines, selected)
            self._validate_catalog(catalog)
            return catalog
        profile = self._load_legacy()
        machine = MachineDefinition.legacy_3018(profile=profile)
        catalog = MachineCatalog((machine,), machine.machine_id)
        self.save(catalog)
        return catalog

    def _load_legacy(self) -> MachineProfile:
        if self.legacy_profile_path is None or not self.legacy_profile_path.exists():
            return MachineProfile(travel_x=290, travel_y=170, travel_z=40, safe_z=30)
        return MachineProfile(**json.loads(self.legacy_profile_path.read_text(encoding="utf-8")))

    def save(self, catalog: MachineCatalog) -> None:
        self._validate_catalog(catalog)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema_version": 1, "selected_machine_id": catalog.selected_machine_id,
                                         "machines": [machine.to_dict() for machine in catalog.machines]}, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _validate_catalog(catalog: MachineCatalog) -> None:
        if not catalog.machines:
            raise ValueError("At least one machine profile is required")
        ids = [machine.machine_id for machine in catalog.machines]
        if len(ids) != len(set(ids)):
            raise ValueError("Machine IDs must be unique")
        if catalog.selected_machine_id not in ids:
            raise ValueError("Selected machine does not exist")

    def select(self, catalog: MachineCatalog, machine_id: str) -> MachineCatalog:
        updated = MachineCatalog(catalog.machines, machine_id)
        self._validate_catalog(updated)
        self.save(updated)
        return updated

    def upsert(self, catalog: MachineCatalog, machine: MachineDefinition) -> MachineCatalog:
        machine.validate()
        machines = tuple(machine if item.machine_id == machine.machine_id else item for item in catalog.machines)
        if all(item.machine_id != machine.machine_id for item in catalog.machines):
            machines += (machine,)
        updated = MachineCatalog(machines, catalog.selected_machine_id if catalog.selected_machine_id in {m.machine_id for m in machines} else machine.machine_id)
        self.save(updated)
        return updated

    def delete(self, catalog: MachineCatalog, machine_id: str) -> MachineCatalog:
        if len(catalog.machines) == 1:
            raise ValueError("Cannot delete the last machine profile")
        machines = tuple(item for item in catalog.machines if item.machine_id != machine_id)
        if len(machines) == len(catalog.machines):
            raise ValueError("Machine profile does not exist")
        selected = catalog.selected_machine_id if catalog.selected_machine_id != machine_id else machines[0].machine_id
        updated = MachineCatalog(machines, selected)
        self.save(updated)
        return updated

