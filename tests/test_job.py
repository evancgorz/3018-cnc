from ttc3018_control.job import JobStreamer


def test_streams_ahead_with_character_counting() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append)
    job.start(["G21", "G1 X1", "M5"])
    assert sent == [b"G21\n", b"G1 X1\n", b"M5\n"]
    assert job.completed == 0
    job.handle_response("ok")
    assert job.completed == 1
    job.handle_response("ok")
    job.handle_response("ok")
    assert job.state == "complete"
    assert job.completed == 3


def test_pause_waits_after_current_ack() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append, buffer_capacity=7)
    job.start(["G1 X1", "G1 X2", "G1 X3"])
    job.pause()
    job.handle_response("ok")
    assert sent == [b"G1 X1\n"]
    job.resume()
    assert sent[-1] == b"G1 X2\n"


def test_refills_only_after_ack_frees_rx_capacity() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append, buffer_capacity=12)
    job.start(["G1 X1", "G1 X2", "G1 X3"])

    assert sent == [b"G1 X1\n", b"G1 X2\n"]
    assert job.buffered_bytes == 12


def test_default_streamer_never_fills_the_reserved_grbl_ring_slot() -> None:
    sent: list[bytes] = []
    commands = ["G1 X12345"] * 13  # 10 bytes each including newline.
    job = JobStreamer(sent.append)

    job.start(commands)

    assert job.buffer_capacity == 127
    assert job.buffered_bytes == 120
    assert len(sent) == 12
    job.handle_response("ok")
    assert job.buffered_bytes == 120
    assert len(sent) == 13
    job.handle_response("ok")
    assert sent[-1] == b"G1 X12345\n"
    assert job.buffered_bytes == 110


def test_error_fails_job_without_sending_more() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append)
    job.start(["G1 X1", "G1 X2"])
    sent_before_error = list(sent)
    assert job.handle_response("error:2")
    assert job.state == "failed"
    assert job.error == "error:2"
    assert sent == sent_before_error


def test_rejects_a_line_larger_than_the_grbl_rx_buffer() -> None:
    job = JobStreamer(lambda _command: None, buffer_capacity=8)

    try:
        job.start(["G1 X1234"])
    except ValueError as exc:
        assert "GRBL RX capacity" in str(exc)
    else:
        raise AssertionError("oversized line should fail before transmission")
    assert job.state == "failed"


def test_send_failure_does_not_leave_job_active() -> None:
    def fail(_command: bytes) -> None:
        raise RuntimeError("connection lost")

    job = JobStreamer(fail)
    try:
        job.start(["G1 X1"])
    except RuntimeError:
        pass
    assert job.state == "failed"
