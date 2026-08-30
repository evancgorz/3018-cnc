import socket
import threading

from ttc3018_control.wifi_discovery import _is_grbl_endpoint, subnet_candidates


def test_subnet_candidates_cover_local_24_without_local_host() -> None:
    candidates = subnet_candidates(["192.168.86.31"])
    assert "192.168.86.1" in candidates
    assert "192.168.86.254" in candidates
    assert "192.168.86.31" not in candidates
    assert len(candidates) == 253


def test_subnet_candidates_deduplicate_interfaces_on_same_network() -> None:
    candidates = subnet_candidates(["192.168.86.31", "192.168.86.32"])
    assert len(candidates) == 252


def test_grbl_probe_accepts_startup_banner_before_status() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()

    def serve() -> None:
        client, _address = server.accept()
        with client:
            client.recv(8)
            client.sendall(b"Grbl 1.1h ['$' for help]\r\n")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert _is_grbl_endpoint(host, port, 0.2)
    finally:
        server.close()
        thread.join(timeout=1)
