from __future__ import annotations

import json
import subprocess

import pytest

from ttc3018_control.tailscale import TailscaleConflict, TailscaleService


def test_tailscale_inspects_version_status_and_owned_serve_mapping() -> None:
    calls: list[list[str]] = []

    def runner(args, **_kwargs):
        calls.append(args)
        if args[1] == "version":
            return subprocess.CompletedProcess(args, 0, "1.86.2\n", "")
        if args[1:3] == ["status", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"BackendState": "Running", "Self": {"DNSName": "pine.tailnet.ts.net."}}), "")
        return subprocess.CompletedProcess(args, 0, json.dumps({"TCP": {"443": {"HTTPS": {"Port": 8443, "Target": "http://127.0.0.1:8765"}}}}), "")

    service = TailscaleService(executable="tailscale.exe", runner=runner)
    status = service.inspect()

    assert status.ready
    assert status.serve_url == "https://pine.tailnet.ts.net:8443/"
    assert status.target == "http://127.0.0.1:8765"
    assert [call[1:3] for call in calls] == [["version"], ["status", "--json"], ["serve", "status"]]


def test_tailscale_enable_only_publishes_loopback_and_refuses_foreign_mapping() -> None:
    calls: list[list[str]] = []
    serve_payload = {"https": {"Port": 8443, "Target": "http://127.0.0.1:8765"}}

    def runner(args, **_kwargs):
        calls.append(args)
        if args[1] == "version":
            return subprocess.CompletedProcess(args, 0, "1.86.2\n", "")
        if args[1:3] == ["status", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"BackendState": "Running", "Self": {"DNSName": "pine.ts.net"}}), "")
        if args[1:4] == ["serve", "status", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(serve_payload), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    service = TailscaleService(executable="tailscale.exe", runner=runner)
    service.enable(local_port=8765)
    serve_calls = [call for call in calls if call[1] == "serve" and call[2] == "--yes"]
    assert serve_calls == [["tailscale.exe", "serve", "--yes", "--bg", "--https=8443", "http://127.0.0.1:8765"]]

    foreign_payload = {"https": {"Port": 8443, "Target": "http://127.0.0.1:9999"}}
    serve_payload.clear()
    serve_payload.update(foreign_payload)
    with pytest.raises(TailscaleConflict):
        service.enable(local_port=8765)


def test_old_tailscale_is_reported_as_unsupported() -> None:
    def runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 0, "1.51.0\n", "")

    status = TailscaleService(executable="tailscale.exe", runner=runner).inspect()
    assert status.state == "Unsupported"
    assert "1.52" in status.message


def test_current_tailscale_status_shape_links_listener_to_web_proxy() -> None:
    payload = {
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {
            "pine.example.ts.net:8443": {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}
            }
        },
    }

    def runner(args, **_kwargs):
        if args[1] == "version":
            return subprocess.CompletedProcess(args, 0, "1.102.3\n", "")
        if args[1:3] == ["status", "--json"]:
            status = {"BackendState": "Running", "Self": {"DNSName": "pine.example.ts.net."}}
            return subprocess.CompletedProcess(args, 0, json.dumps(status), "")
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    status = TailscaleService(executable="tailscale.exe", runner=runner).inspect()
    assert status.ready
    assert status.target == "http://127.0.0.1:8765"
    assert status.serve_url == "https://pine.example.ts.net:8443/"
