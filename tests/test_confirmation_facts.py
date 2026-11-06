import math
import json

import pytest

from ttc3018_control.application.confirmation_facts import meaningful_status_facts
from ttc3018_control.grbl import GrblStatus, Position


def _status(**overrides) -> GrblStatus:
    values = {
        "state": "Idle",
        "machine_position": Position(10.0, 20.0, 30.0),
        "work_position": Position(0.0, 0.0, 0.0),
        "work_offset": Position(10.0, 20.0, 30.0),
        "feed": 0.0,
        "spindle": 0.0,
        "pins": "",
        "fields": {"Pn": "", "Bf": "15,1200", "Ov": "100,100,100"},
    }
    values.update(overrides)
    return GrblStatus(**values)


def test_status_facts_ignore_raw_telemetry_and_redundant_work_coordinates() -> None:
    direct = _status(
        machine_position=Position(10.3, 20.0, 30.0),
        work_position=Position(0.1, 1.0, 2.0),
        work_offset=Position(10.2, 19.0, 28.0),
        fields={"Pn": "", "Bf": "15,1200", "Ov": "100,100,100"},
    )
    derived = _status(
        machine_position=None,
        work_position=Position(0.3, 2.0, 3.0),
        work_offset=Position(10.0, 18.0, 27.0),
        fields={"Pn": "", "Bf": "2,64", "Ov": "90,80,70", "WCO": "ignored raw value"},
    )

    assert meaningful_status_facts(direct) == meaningful_status_facts(derived)


@pytest.mark.parametrize(
    "change",
    [
        {"state": "Run"},
        {"machine_position": Position(10.0, 20.0, 30.001)},
        {"feed": 1.0},
        {"spindle": 1.0},
        {"pins": "X", "fields": {"Pn": "X"}},
    ],
)
def test_status_facts_change_with_safety_relevant_state(change: dict[str, object]) -> None:
    assert meaningful_status_facts(_status()) != meaningful_status_facts(_status(**change))


def test_missing_nonfinite_and_unknown_values_are_not_safe_defaults() -> None:
    missing = _status(machine_position=None, work_position=None, work_offset=None, feed=None, spindle=None)
    zero = _status(
        machine_position=Position(0.0, 0.0, 0.0),
        feed=0.0,
        spindle=0.0,
    )
    nonfinite = _status(feed=math.nan)
    unknown = _status(feed="not reported")  # type: ignore[arg-type]
    absent_status = meaningful_status_facts(None)

    missing_facts = meaningful_status_facts(missing)
    assert missing_facts != meaningful_status_facts(zero)
    assert missing_facts != meaningful_status_facts(nonfinite)
    assert meaningful_status_facts(nonfinite) != meaningful_status_facts(unknown)
    assert absent_status != missing_facts
    assert missing_facts["feed"] == {"kind": "missing"}
    assert meaningful_status_facts(nonfinite)["feed"] == {"kind": "nonfinite", "value": "nan"}
    assert meaningful_status_facts(unknown)["feed"] == {
        "kind": "unknown",
        "type": "builtins.str",
    }
    json.dumps(missing_facts, sort_keys=True)


def test_explicit_empty_pin_report_differs_from_omitted_pin_field() -> None:
    omitted = _status(fields={"Bf": "15,1200"})
    reported_empty = _status(fields={"Pn": ""})

    assert meaningful_status_facts(omitted)["pins"] == {"kind": "missing"}
    assert meaningful_status_facts(reported_empty)["pins"] == {"kind": "value", "value": ""}


def test_equivalent_pin_order_has_same_fact() -> None:
    xyz = _status(pins="XYZ", fields={"Pn": "XYZ"})
    zyx = _status(pins="ZYX", fields={"Pn": "ZYX"})

    assert meaningful_status_facts(xyz) == meaningful_status_facts(zyx)
