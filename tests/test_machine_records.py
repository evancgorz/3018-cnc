from pathlib import Path

from ttc3018_control.grbl import Position
from ttc3018_control.machine_records import MachineRecordStore
from ttc3018_control.work_zero_settings import SavedWorkZero, WorkZeroStore


def test_work_zero_store_supports_independent_machine_records(tmp_path: Path) -> None:
    store = WorkZeroStore(tmp_path / "work-zero.json")
    store.save(SavedWorkZero.from_position(Position(1, 2, 3)), "a")
    store.save(SavedWorkZero.from_position(Position(4, 5, 6)), "b")
    assert store.load("a") == SavedWorkZero(1, 2, 3)
    assert store.load("b") == SavedWorkZero(4, 5, 6)
    store.clear("a")
    assert store.load("a") is None
    assert store.load("b") == SavedWorkZero(4, 5, 6)


def test_legacy_work_zero_is_read_and_only_migrated_on_explicit_save(tmp_path: Path) -> None:
    path = tmp_path / "work-zero.json"
    legacy = SavedWorkZero(1, 2, 3)
    WorkZeroStore(path).save(legacy)
    store = WorkZeroStore(path)
    assert store.load("new-machine") == legacy
    assert store.load() == legacy
    store.save(legacy, "new-machine")
    assert store.load("new-machine") == legacy


def test_generic_machine_record_store_isolated_and_atomic(tmp_path: Path) -> None:
    store = MachineRecordStore(tmp_path / "commissioning.json")
    store.save("a", {"status": "commissioned"})
    store.save("b", {"status": "stale"})
    assert store.load("a") == {"status": "commissioned"}
    assert store.load("b") == {"status": "stale"}
    store.clear("a")
    assert store.load("a") is None
    assert store.load("b") == {"status": "stale"}
