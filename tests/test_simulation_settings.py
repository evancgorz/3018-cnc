from __future__ import annotations

import json

import pytest

from ttc3018_control.simulation.models import SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.settings import SimulationSettings, SimulationSettingsStore


def test_simulation_settings_round_trip_isolated(tmp_path) -> None:
    path = tmp_path / "config" / "simulation.json"
    settings = SimulationSettings(speed="10x", workpiece=SimulationWorkpiece(stock_width=20, stock_height=10, stock_thickness=3), profile=SimulationProfile(stock_resolution=0.25))
    store = SimulationSettingsStore(path)
    store.save(settings)
    assert store.load() == settings
    assert path.exists()


@pytest.mark.parametrize("payload", [None, {"schema_version": 9}, {"speed": "physical"}, {"profile": {"travel_z": 0}}])
def test_simulation_settings_malformed_or_future_data_fails_closed(tmp_path, payload) -> None:
    path = tmp_path / "simulation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ValueError, TypeError, KeyError)):
        SimulationSettingsStore(path).load()
