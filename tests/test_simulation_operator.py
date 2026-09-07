from pathlib import Path

from ttc3018_control.simulation.geometry import AABB
from ttc3018_control.simulation.models import Hazard, HazardKind, PlantSnapshot, SimulationProfile, MotionSnapshot
from ttc3018_control.simulation.operator import IndependentVirtualOperator, OperatorFixture


def _snapshot(sequence: int, time_ns: int, position=(10.0, 10.0, 12.0), *, state="Idle", motion=None):
    return PlantSnapshot(time_ns, state, position, (0.0, 0.0, 0.0), 100.0, 0.0, 0.0, motion=motion, sequence=sequence)


def test_operator_recomputes_independently_and_reports_disagreement() -> None:
    operator = IndependentVirtualOperator(SimulationProfile.default_3018())
    operator.observe(_snapshot(1, 1))
    backend = Hazard(HazardKind.TRAVEL_LIMIT, "backend verdict", 2, (10.0, 10.0, 12.0))
    result = operator.observe(_snapshot(2, 2), expected_hazards=(backend,))
    assert result.disagreement
    assert [item.kind for item in result.hazards] == [HazardKind.DIVERGENCE]
    assert result.intents[-1].action == "interlock"
    assert "CollisionWorld" not in Path(__file__).parents[1].joinpath(
        "src/ttc3018_control/simulation/supervisor.py").read_text(encoding="utf-8")

    fixture_operator = IndependentVirtualOperator(
        fixtures=(OperatorFixture("fixture", AABB(0, 0, 5, 20, 20, 10)),)
    )
    fixture_operator.observe(_snapshot(1, 1))
    detected = fixture_operator.observe(
        _snapshot(2, 2, (10, 10, 6), state="Run",
                  motion=MotionSnapshot(start=(10, 10, 12), target=(10, 10, 6), feed=100, progress=.5)),
        expected_hazards=(),
    )
    assert detected.disagreement
    assert any(item.kind is HazardKind.DIVERGENCE for item in detected.hazards)


def test_operator_intents_are_ordered_hold_then_interlock_for_first_contact() -> None:
    fixture = OperatorFixture("fixture", AABB(0, 0, 5, 20, 20, 10))
    operator = IndependentVirtualOperator(fixtures=(fixture,))
    operator.observe(_snapshot(1, 1))
    moving = _snapshot(2, 2, (10.0, 10.0, 6.0), state="Run",
                       motion=MotionSnapshot(start=(10, 10, 12), target=(10, 10, 6), feed=100, progress=.5))
    result = operator.observe(moving)
    assert any(item.kind is HazardKind.TOOL_FIXTURE for item in result.hazards)
    actions = [item.action for item in result.intents]
    assert actions[:2] == ["hold", "interlock"]


def test_operator_consumes_user_intents_in_order_and_rejects_stale_events() -> None:
    operator = IndependentVirtualOperator()
    assert operator.consume_intent({"name": "establish_reference", "sequence": 1}) == ()
    assert [item.action for item in operator.consume_intent({"name": "pause_job", "sequence": 2})] == ["hold"]
    stale = operator.consume_intent({"name": "abort_job", "sequence": 2})
    assert [item.action for item in stale] == ["abort", "interlock"]


def test_operator_rejects_stale_snapshot_and_fails_closed() -> None:
    operator = IndependentVirtualOperator()
    operator.observe(_snapshot(1, 1))
    result = operator.observe(_snapshot(1, 1))
    assert result.stale
    assert result.hazards[0].kind is HazardKind.PROTOCOL
    assert [item.action for item in result.intents] == ["hold", "abort", "interlock"]


def test_operator_supervisor_failure_requires_explicit_recovery_authorization() -> None:
    operator = IndependentVirtualOperator(recovery_token="approve")
    operator.observe(_snapshot(1, 1))
    failure = operator.report_failure("supervisor heartbeat expired")
    assert [item.action for item in failure.intents] == ["hold", "abort", "interlock"]

    denied = operator.authorize_recovery("wrong", _snapshot(2, 2))
    assert denied.intents[0].action == "recovery_denied"

    recovered = operator.authorize_recovery("approve", _snapshot(3, 3))
    assert recovered.intents[0].action == "recover"
