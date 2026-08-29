import queue
import socket
import threading
import time

from ttc3018_control.tcp_connection import TcpGrblConnection


def test_tcp_connection_sends_and_receives_grbl_data() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    received = bytearray()

    def serve() -> None:
        client, _ = server.accept()
        with client:
            client.settimeout(1)
            received.extend(client.recv(32))
            client.sendall(b"<Idle|MPos:1.000,2.000,3.000|FS:0,0>\r\n")
            while b"$I\n" not in received:
                try:
                    chunk = client.recv(32)
                except TimeoutError:
                    break
                if not chunk:
                    break
                received.extend(chunk)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    connection = TcpGrblConnection()
    try:
        connection.connect(host, port)
        connection.send_line(b"$I", display_text="<redacted command>")
        deadline = time.monotonic() + 2
        events = []
        while time.monotonic() < deadline:
            try:
                events.append(connection.events.get(timeout=0.05))
            except queue.Empty:
                pass
            if any(event.kind == "rx" for event in events) and any(
                event.text == "<redacted command>" for event in events
            ):
                break
        assert any(event.text.startswith("<Idle") for event in events)
        assert any(event.text == "<redacted command>" for event in events)
        assert not any(event.text == "$I" for event in events)
        thread.join(timeout=1)
        assert b"?" in received
        assert b"$I\n" in received
    finally:
        connection.disconnect()
        server.close()
        thread.join(timeout=1)


def test_tcp_connection_rejects_invalid_endpoint() -> None:
    connection = TcpGrblConnection()
    for host, port in (("", 23), ("localhost", 0), ("localhost", 65536)):
        try:
            connection.connect(host, port)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid endpoint was accepted")
