from __future__ import annotations

import json
from pathlib import Path

from ttc3018_control.backend import CapabilitySnapshot
from ttc3018_control.backend import cli


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.__class__.instances.append(self)

    def attach(self):
        return {"health": {"session_id": "s"}, "snapshot": self.snapshot()}

    def snapshot(self):
        return {
            "schema_version": 1, "protocol_version": 1, "revision": 7,
            "backend": {"available": True, "session_id": "s"},
            "machine": {"name": "Two Trees TTC 3018", "axes": {}},
            "profile": {"name": "Two Trees TTC 3018", "travel_x": 290.0,
                        "travel_y": 170.0, "travel_z": 40.0, "safe_z": 30.0},
            "capabilities": CapabilitySnapshot(actions=("status",)).to_dict(),
        }

    def typed_snapshot(self):
        from ttc3018_control.backend import BackendSnapshot
        return BackendSnapshot.from_dict(self.snapshot())

    def invoke(self, action, **arguments):
        self.calls.append((action, arguments))
        return {"accepted": True, "message": "ok"}


def test_cli_status_and_capabilities_are_read_only_json(monkeypatch, tmp_path: Path, capsys) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(cli, "BackendClient", _FakeClient)
    assert cli.main(["--root", str(tmp_path), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 7
    assert cli.main(["--root", str(tmp_path), "capabilities", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["actions"] == ["status"]
    assert _FakeClient.instances[-1].calls == []


def test_cli_exposes_safety_input_status_and_requires_acknowledgement(monkeypatch, tmp_path: Path, capsys) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(cli, "BackendClient", _FakeClient)
    assert cli.main(["--root", str(tmp_path), "safety-input-status", "--json"]) == 0
    assert _FakeClient.instances[-1].calls[-1][0] == "safety-input-status"
    assert cli.main(["--root", str(tmp_path), "acknowledge-safety-input", "--json"]) == 2
    assert "authorization_required" in capsys.readouterr().out
    assert cli.main(["--root", str(tmp_path), "acknowledge-safety-input", "--confirm", "--json"]) == 0
    assert _FakeClient.instances[-1].calls[-1][0] == "acknowledge-safety-input"


def test_cli_motion_requires_confirmation_and_forwards_revision_metadata(monkeypatch, tmp_path: Path, capsys) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(cli, "BackendClient", _FakeClient)
    assert cli.main(["--root", str(tmp_path), "jog", "X", "1", "--confirm",
                     "--revision", "7", "--idempotency-key", "retry-1", "--json"]) == 0
    action, arguments = _FakeClient.instances[-1].calls[-1]
    assert action == "jog"
    assert arguments["expected_revision"] == 7
    assert arguments["idempotency_key"] == "retry-1"
    assert cli.main(["--root", str(tmp_path), "jog", "X", "1", "--json"]) == 2
    assert "authorization_required" in capsys.readouterr().out


def test_cli_exposes_explicit_watchdog_recovery_actions(monkeypatch, tmp_path: Path, capsys) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(cli, "BackendClient", _FakeClient)

    assert cli.main(["--root", str(tmp_path), "continue-to-home", "--json"]) == 2
    assert _FakeClient.instances[-1].calls == []
    assert "authorization_required" in capsys.readouterr().out

    assert cli.main(["--root", str(tmp_path), "continue-to-home", "--confirm", "--json"]) == 0
    assert _FakeClient.instances[-1].calls[-1][0] == "continue-to-home"
    assert _FakeClient.instances[-1].calls[-1][1] == {
        "expected_revision": None, "idempotency_key": None,
    }

    assert cli.main(["--root", str(tmp_path), "cancel-recovery", "--json"]) == 0
    assert _FakeClient.instances[-1].calls[-1][0] == "cancel-recovery"


def test_cli_configuration_preview_precedes_explicit_apply(monkeypatch, tmp_path: Path, capsys) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(cli, "BackendClient", _FakeClient)
    args = ["--root", str(tmp_path), "save-profile", "--travel-x", "291",
            "--travel-y", "170", "--travel-z", "40", "--safe-z", "30", "--json"]
    assert cli.main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["preview"] is True and preview["apply_required"] is True
    assert _FakeClient.instances[-1].calls == []
    assert cli.main(args + ["--apply"]) == 2
    assert "authorization_required" in capsys.readouterr().out
    assert cli.main(args + ["--apply", "--confirm"]) == 0
    assert _FakeClient.instances[-1].calls[-1][0] == "save-profile"


def test_cli_wrong_root_explains_how_to_attach(tmp_path: Path, capsys) -> None:
    assert cli.main(["--root", str(tmp_path), "status", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "backend_unavailable"
    assert str(tmp_path / "pine-backend.json") in result["message"]
    assert "application data directory" in result["message"]
    assert not list(tmp_path.iterdir())
