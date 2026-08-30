from __future__ import annotations

import json

import pytest

from ttc3018_control.step_prepare_settings import StepPrepareSettings, StepPrepareSettingsStore


def test_step_prepare_settings_round_trip(tmp_path) -> None:
    store = StepPrepareSettingsStore(tmp_path / "step-prepare.json")
    settings = StepPrepareSettings(
        tool_diameter=2.0,
        passes=3,
        max_stepdown=0.5,
        safe_z=4.0,
        cut_feed=450,
        plunge_feed=120,
        spindle_rpm=12000,
    )

    store.save(settings)

    assert store.load() == settings


def test_step_prepare_settings_reject_invalid_saved_values(tmp_path) -> None:
    path = tmp_path / "step-prepare.json"
    path.write_text(json.dumps({"tool_diameter": 0}), encoding="utf-8")

    with pytest.raises(ValueError, match="Tool diameter"):
        StepPrepareSettingsStore(path).load()
