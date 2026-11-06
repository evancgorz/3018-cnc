from __future__ import annotations

import ast
from pathlib import Path

from ttc3018_control.backend.dispatcher import ActionDispatcher


ROOT = Path(__file__).parents[1]


def _function(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return next(node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def test_production_qt_main_uses_backend_manager_and_keeps_legacy_seam_explicit() -> None:
    source = (ROOT / "src" / "ttc3018_control" / "qt" / "main.py").read_text(encoding="utf-8")
    main = _function(source, "main")
    calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)]
    assert any(isinstance(node.func, ast.Name) and node.func.id == "BackendProcessManager" for node in calls)
    assert "build_engine(backend_client=backend_client" in source
    build = _function(source, "build_engine")
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "ApplicationController" for node in ast.walk(build))
    assert "application is not None and backend_client is not None" in source


def test_viewmodel_has_no_direct_transport_bytes() -> None:
    source = (ROOT / "src" / "ttc3018_control" / "qt" / "view_model.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    direct_transport_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"send_line", "send_realtime"}
    ]
    assert not direct_transport_calls


def test_backend_viewmodel_poll_is_snapshot_driven_and_adapter_is_disposable() -> None:
    view_source = (ROOT / "src" / "ttc3018_control" / "qt" / "view_model.py").read_text(encoding="utf-8")
    poll = _function(view_source, "_poll")
    poll_text = ast.get_source_segment(view_source, poll) or ""
    assert "poll_backend" in poll_text
    assert "backend_unavailable" in poll_text
    assert "return" in poll_text
    adapter_source = (ROOT / "src" / "ttc3018_control" / "backend" / "qt_adapter.py").read_text(encoding="utf-8")
    close = _function(adapter_source, "close")
    close_text = ast.get_source_segment(adapter_source, close) or ""
    assert "shutdown" not in close_text
    assert "poll_backend" in adapter_source and "backend_session_id" in adapter_source


def test_physical_safety_snapshot_reaches_gui_and_cli_without_local_decisions() -> None:
    adapter_source = (ROOT / "src" / "ttc3018_control" / "backend" / "qt_adapter.py").read_text(encoding="utf-8")
    view_source = (ROOT / "src" / "ttc3018_control" / "qt" / "view_model.py").read_text(encoding="utf-8")
    qml_source = (ROOT / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "physical_safety_input_status" in adapter_source
    assert "acknowledge-safety-input" in adapter_source
    assert "physical_safety_input_status_text" in view_source
    assert "physical_safety_input_power_removal" in view_source
    assert "physicalSafetyInputStatus" in qml_source
    assert "reviewPhysicalSafetyFacts" in qml_source
    assert "acknowledgePhysicalSafetyInput" in qml_source


def test_dispatcher_is_finite_and_excludes_raw_transport_operations() -> None:
    assert ActionDispatcher.ACTIONS
    assert not {"send-line", "send-realtime", "raw-command"} & ActionDispatcher.ACTIONS
    assert ActionDispatcher.ACTIONS == frozenset(ActionDispatcher._KEYS)


def test_audit_matrix_is_checked_in_with_required_authority_and_gap_sections() -> None:
    text = (ROOT / "docs" / "BACKEND_FRONTEND_SEPARATION_AUDIT.md").read_text(encoding="utf-8")
    for heading in ("## Reconciled topology", "## Authority and lifecycle contract",
                    "## GUI call inventory", "## Gap matrix and sequencing",
                    "## C-007 targeted gates"):
        assert heading in text
    for term in ("lease/orphan", "loopback-only", "Live bridge", "C-008", "C-009", "C-010", "C-011", "C-012"):
        assert term in text
