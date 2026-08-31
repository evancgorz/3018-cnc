from pathlib import Path

from ttc3018_control.machine_catalog import MachineCatalogStore
from ttc3018_control.machine_config import MachineDefinition
from ttc3018_control.machine_state import MachineProfile


def test_catalog_migrates_legacy_profile_idempotently(tmp_path: Path) -> None:
    legacy = tmp_path / "machine-profile.json"
    legacy.write_text('{"name":"Legacy","travel_x":100,"travel_y":80,"travel_z":30,"safe_z":20}', encoding="utf-8")
    store = MachineCatalogStore(tmp_path / "machines.json", legacy)
    first = store.load()
    second = store.load()
    assert first == second
    assert first.selected().name == "Legacy"
    assert first.selected().to_profile() == MachineProfile("Legacy", 100, 80, 30, 20)


def test_catalog_crud_and_last_machine_guard(tmp_path: Path) -> None:
    store = MachineCatalogStore(tmp_path / "machines.json")
    catalog = store.load()
    second = MachineDefinition.legacy_3018(machine_id="second", profile=MachineProfile("Second", 200, 100, 35, 25))
    catalog = store.upsert(catalog, second)
    catalog = store.select(catalog, "second")
    assert catalog.selected().name == "Second"
    catalog = store.delete(catalog, "second")
    assert catalog.selected().machine_id != "second"
    try:
        store.delete(catalog, catalog.selected_machine_id)
    except ValueError as exc:
        assert "last" in str(exc)
    else:
        raise AssertionError("last profile deletion was accepted")

