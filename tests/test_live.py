from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ttc3018_control.live.commands import RemoteCommand, RemoteCommandResult
from ttc3018_control.live.frames import FrameHub
from ttc3018_control.live.models import LiveStatusSnapshot
from ttc3018_control.live.security import PairingManager
from ttc3018_control.live.server import LiveWebServer, is_private_bind_address


def snapshot(job_nonce: str = "job-1", state: str = "running") -> LiveStatusSnapshot:
    return LiveStatusSnapshot(
        sequence=1,
        timestamp="2026-09-01T00:00:00+00:00",
        connected=True,
        grbl_state="Run" if state == "running" else "Hold",
        job_state=state,
        job_name="test.gcode",
        job_nonce=job_nonce,
        progress=25,
        can_pause=state == "running",
        can_resume=state == "paused",
        can_abort=state in {"running", "paused"},
    )


def post(url: str, payload: dict, *, cookie: str = "", csrf: str = ""):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    return urlopen(request, timeout=2)


def test_bind_policy_rejects_public_and_wildcard_addresses() -> None:
    assert is_private_bind_address("127.0.0.1")
    assert is_private_bind_address("192.168.1.20")
    assert not is_private_bind_address("0.0.0.0")
    assert not is_private_bind_address("8.8.8.8")
    with pytest.raises(ValueError):
        LiveWebServer(lambda: snapshot(), lambda command: RemoteCommandResult(True, command.action, "ok", command.request_id), host="0.0.0.0")


def test_pairing_is_one_time_and_sessions_revoke() -> None:
    manager = PairingManager()
    code = manager.pairing_code
    session = manager.pair(code)
    assert session is not None
    assert manager.authenticate(session.token) is not None
    assert manager.pair(code) is None
    manager.revoke_all()
    assert manager.authenticate(session.token) is None


def test_frame_hub_keeps_only_latest_and_unblocks_waiters() -> None:
    hub = FrameHub()
    assert hub.publish(b"one") == 1
    assert hub.publish(b"two") == 2
    assert hub.latest().jpeg == b"two"
    assert hub.wait_next(1, 0.1).jpeg == b"two"
    hub.close()
    assert hub.wait_next(2, 0.1).jpeg == b"two"


def test_http_pair_status_camera_and_exactly_once_command() -> None:
    commands: list[RemoteCommand] = []
    hub = FrameHub()
    current = [snapshot()]

    def submit(command: RemoteCommand) -> RemoteCommandResult:
        commands.append(command)
        return RemoteCommandResult(True, command.action, f"{command.action} accepted", command.request_id)

    server = LiveWebServer(lambda: current[0], submit, frame_hub=hub, host="127.0.0.1", port=0)
    server.start()
    try:
        with urlopen(server.url, timeout=1) as page:
            page_html = page.read().decode("utf-8")
            policy = page.headers["Content-Security-Policy"]
        nonce = policy.split("'nonce-", 1)[1].split("'", 1)[0]
        assert f'<script nonce="{nonce}">' in page_html
        assert "script-src 'self' 'unsafe-inline'" not in policy

        with pytest.raises(HTTPError) as unauthorized:
            urlopen(server.url + "api/v1/status/events", timeout=1)
        assert unauthorized.value.code == 401

        pair_response = post(server.url + "pair", {"code": server.pairing.pairing_code})
        pair_data = json.loads(pair_response.read())
        cookie = pair_response.headers["Set-Cookie"].split(";", 1)[0]
        csrf = pair_data["csrf_token"]
        response = post(server.url + "api/v1/jobs/job-1/pause", {"job_nonce": "job-1", "request_id": "r1"}, cookie=cookie, csrf=csrf)
        assert json.loads(response.read())["accepted"]
        duplicate = post(server.url + "api/v1/jobs/job-1/pause", {"job_nonce": "job-1", "request_id": "r1"}, cookie=cookie, csrf=csrf)
        assert json.loads(duplicate.read())["accepted"]
        assert len(commands) == 1

        hub.publish(b"fake-jpeg")
        request = Request(server.url + "api/v1/camera.mjpg", headers={"Cookie": cookie})
        with urlopen(request, timeout=2) as camera:
            data = camera.read(120)
        assert b"multipart" in camera.headers["Content-Type"].encode()
        assert b"fake-jpeg" in data
    finally:
        server.stop()


def test_abort_requires_one_use_confirmation() -> None:
    commands: list[RemoteCommand] = []
    server = LiveWebServer(lambda: snapshot(), lambda command: commands.append(command) or RemoteCommandResult(True, command.action, "ok", command.request_id), host="127.0.0.1", port=0)
    server.start()
    try:
        pair_response = post(server.url + "pair", {"code": server.pairing.pairing_code})
        data = json.loads(pair_response.read())
        cookie = pair_response.headers["Set-Cookie"].split(";", 1)[0]
        csrf = data["csrf_token"]
        confirmation_response = post(server.url + "api/v1/jobs/job-1/abort/confirm", {"request_id": "confirm"}, cookie=cookie, csrf=csrf)
        confirmation = json.loads(confirmation_response.read())["confirmation"]
        result = post(server.url + "api/v1/jobs/job-1/abort", {"job_nonce": "job-1", "request_id": "abort-1", "confirmation": confirmation}, cookie=cookie, csrf=csrf)
        assert json.loads(result.read())["accepted"]
        assert len(commands) == 1
        with pytest.raises(HTTPError) as reused:
            post(server.url + "api/v1/jobs/job-1/abort", {"job_nonce": "job-1", "request_id": "abort-2", "confirmation": confirmation}, cookie=cookie, csrf=csrf)
        assert reused.value.code == 409
    finally:
        server.stop()


def test_https_public_origin_and_secure_pairing_cookie_are_supported() -> None:
    server = LiveWebServer(
        lambda: snapshot(),
        lambda command: RemoteCommandResult(True, command.action, "ok", command.request_id),
        host="127.0.0.1",
        port=0,
        public_url="https://pine.example.ts.net:8443",
        allowed_origins=("https://pine.example.ts.net:8443",),
        secure_cookie=True,
    )
    server.start()
    try:
        request = Request(
            server.address and f"http://{server.address[0]}:{server.address[1]}/pair",
            data=json.dumps({"code": server.pairing.pairing_code}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://pine.example.ts.net:8443",
            },
            method="POST",
        )
        response = urlopen(request, timeout=2)
        assert "; Secure" in response.headers["Set-Cookie"]
        assert server.url == "https://pine.example.ts.net:8443/"
    finally:
        server.stop()
