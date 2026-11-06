"""USB bootstrap handoff tests use injected transports only; no network/hardware."""
from datetime import datetime, timedelta
import queue
import threading

import pytest

from ttc3018_control.application.connection_service import ConnectionService
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.application.wifi_bootstrap import _station_ip
from ttc3018_control.connection_settings import ConnectionSettings
from ttc3018_control.grbl import parse_status
from ttc3018_control.serial_connection import SerialEvent


IDLE = "<Idle|MPos:1,2,3|FS:0,0>"


class Transport:
    def __init__(self, status=IDLE, *, error=None, gate=None):
        self.connected = False
        self.events = queue.Queue()
        self.status = status
        self.error = error
        self.gate = gate
        self.lines = []
        self.realtime = []
        self.connects = []
        self.disconnects = 0
        self.event_age = 0

    def connect(self, *args, **kwargs):
        self.connects.append((args, kwargs))
        if self.gate:
            assert self.gate.wait(2)
        if self.error:
            raise self.error
        self.connected = True

    def send_line(self, command, display_text=None):
        self.lines.append(command)

    def send_realtime(self, command):
        self.realtime.append(command)
        if command == b"?" and self.status:
            self.events.put(SerialEvent("rx", self.status, datetime.now() - timedelta(seconds=self.event_age)))

    def disconnect(self):
        self.disconnects += 1
        self.connected = False


def setup(candidate=None, saved="192.168.86.38"):
    usb = Transport()
    tcp = candidate or Transport()
    def no_scan(_port):
        raise AssertionError("Bootstrap must not scan")
    service = ConnectionService(lambda: usb, lambda: tcp, no_scan)
    assert service.connect_usb("COM4").accepted
    settings = ConnectionSettings(saved, 23)
    return service, usb, tcp, settings


def start(service, settings):
    assert service.start_wifi_bootstrap(settings, now=0).accepted
    assert service.poll_wifi_bootstrap(usb_status=parse_status(IDLE), usb_status_age=0,
        allow_handoff=True, now=0.6) is None
    service._wifi_bootstrap.worker.join(1)


def poll(service, *, now=0.7, age=0, allowed=True, status=IDLE):
    return service.poll_wifi_bootstrap(usb_status=parse_status(status), usb_status_age=age,
        allow_handoff=allowed, now=now)


def test_success_retains_usb_until_verified_same_socket_handoff():
    service, usb, tcp, settings = setup()
    assert service.wifi_bootstrap_snapshot["state"] == "idle"
    start(service, settings)
    assert service.transport is usb and usb.connected and usb.disconnects == 0
    assert usb.lines == [b"[ESP111]"]
    result = poll(service)
    assert result.accepted and result.mode is ConnectionMode.WIFI
    assert service.transport is tcp and tcp.connected
    assert len(tcp.connects) == 1 and tcp.disconnects == 0
    assert usb.disconnects == 1
    assert service.wifi_bootstrap_snapshot["state"] == "ready"
    assert poll(service, now=0.8) is None
    service.close()
    assert tcp.disconnects == 1


@pytest.mark.parametrize("tcp_status", [
    "<Run|MPos:1,2,3|FS:0,0>", "<Idle|MPos:1,2,3|FS:0,12000>",
    "<Idle|MPos:1,2,3|FS:1,0>", "<Idle|MPos:1,2,3>",
    "<Idle|MPos:nan,2,3|FS:0,0>", "<Idle|MPos:1,2,4|FS:0,0>",
    "<Idle|MPos:oops|FS:0,0>",
])
def test_rejects_unsafe_malformed_or_different_candidate(tcp_status):
    service, usb, tcp, settings = setup(Transport(tcp_status))
    start(service, settings)
    result = poll(service)
    assert result is not None and not result.accepted
    assert service.transport is usb and usb.connected and usb.disconnects == 0
    assert tcp.disconnects >= 1
    assert service.wifi_bootstrap_snapshot["state"] == "unavailable"
    service.close()


@pytest.mark.parametrize("age,allowed,status", [
    (None, True, IDLE), (1.0, True, IDLE), (float("nan"), True, IDLE),
    (0, False, IDLE), (0, True, "<Run|MPos:1,2,3|FS:0,0>"),
])
def test_handoff_requires_fresh_safe_usb_and_application_permission(age, allowed, status):
    service, usb, tcp, settings = setup()
    start(service, settings)
    assert poll(service, age=age, allowed=allowed, status=status) is None
    assert service.transport is usb and usb.disconnects == 0
    assert poll(service, now=3) is not None
    assert service.transport is usb and usb.connected and tcp.disconnects == 1
    service.close()


def test_stale_candidate_status_cannot_authorize_handoff():
    tcp = Transport()
    tcp.event_age = 5
    service, usb, tcp, settings = setup(tcp)
    start(service, settings)
    assert poll(service) is None
    assert service.transport is usb
    assert not poll(service, now=3).accepted
    service.close()


def test_connect_timeout_preserves_usb_and_reports_endpoint_error():
    service, usb, tcp, settings = setup(Transport(error=TimeoutError("timed out")))
    start(service, settings)
    outcome = poll(service)
    assert not outcome.accepted and "192.168.86.38:23" in outcome.message
    assert "TimeoutError" in outcome.message
    assert service.transport is usb and usb.connected
    service.close()


def test_usb_reported_ip_preferred_over_saved_and_no_scan():
    service, usb, tcp, settings = setup()
    assert service.start_wifi_bootstrap(settings, now=0).accepted
    service.note_wifi_bootstrap_usb_line("IP=192.168.86.41")
    assert poll(service, now=0.6) is None
    service._wifi_bootstrap.worker.join(1)
    assert poll(service).accepted
    assert tcp.connects[0][0] == ("192.168.86.41", 23)
    service.close()


def test_missing_address_needs_setup_without_provisioning_or_reboot():
    service, usb, tcp, settings = setup(saved="not-an-ip")
    assert service.start_wifi_bootstrap(settings, now=0).accepted
    outcome = poll(service, now=0.6)
    assert not outcome.accepted
    assert service.wifi_bootstrap_snapshot["state"] == "needs-setup"
    assert usb.lines == [b"[ESP111]"] and tcp.connects == []
    assert usb.connected
    service.close()


def test_cancel_inflight_connection_closes_late_candidate_and_keeps_usb():
    gate = threading.Event()
    service, usb, tcp, settings = setup(Transport(gate=gate))
    assert service.start_wifi_bootstrap(settings, now=0).accepted
    assert poll(service, now=0.6) is None
    worker = service._wifi_bootstrap.worker
    service.cancel_wifi_bootstrap()
    gate.set()
    worker.join(1)
    assert not worker.is_alive()
    assert tcp.disconnects == 1 and not tcp.connected
    assert usb.connected and service.transport is usb
    service.close()


def test_disconnect_cancels_pending_candidate():
    service, usb, tcp, settings = setup()
    start(service, settings)
    service.disconnect()
    assert not usb.connected and not tcp.connected
    assert tcp.disconnects == 1
    assert service.transport is None


@pytest.mark.parametrize("line,expected", [
    ("192.168.86.41", "192.168.86.41"),
    ("IP: 192.168.86.41", "192.168.86.41"),
    ("[MSG:Mode=STA:Status=Connected:IP=192.168.86.41]", "192.168.86.41"),
    ("[MSG:Mode=STA:Status=Disconnected:IP=192.168.86.41]", None),
    ("[MSG:Mode=AP:IP=192.168.4.1]", None),
    ("0.0.0.0", None), ("127.0.0.1", None), ("255.255.255.255", None),
    ("169.254.1.1", None), ("224.0.0.1", None), ("GW=192.168.86.1", None),
    ("SSID=password192.168.86.41", None),
])
def test_controller_ip_recognition(line, expected):
    assert _station_ip(line) == expected


@pytest.mark.parametrize("command", [b"G1 X1", b"$H", b"M3 S12000", b"G10 L20 P1 X0", b"M6", b"$$\nG1 X1", b"[ESP444]RESTART", b"$X"])
def test_strict_usb_line_gate_blocks_physical_or_reconfiguration_commands(command):
    service, usb, tcp, settings = setup()
    service.usb_setup_only = True
    with pytest.raises(RuntimeError, match="bootstrap only"):
        service.send_line(command)
    assert usb.lines == []
    service.close()


@pytest.mark.parametrize("command", [b"[ESP111]", b"$$", b"$I", b"$G", b"$#", b"$N", b"M5"])
def test_strict_usb_allows_only_documented_reads_and_stop(command):
    service, usb, tcp, settings = setup()
    service.usb_setup_only = True
    service.send_line(command)
    assert usb.lines == [command]
    service.close()


def test_strict_usb_realtime_gate_preserves_emergency_commands_denies_resume():
    service, usb, tcp, settings = setup()
    service.usb_setup_only = True
    for command in (b"?", b"!", b"\x18", b"\x85"):
        service.send_realtime(command)
    with pytest.raises(RuntimeError, match="bootstrap only"):
        service.send_realtime(b"~")
    assert usb.realtime == [b"?", b"!", b"\x18", b"\x85"]
    service.close()
