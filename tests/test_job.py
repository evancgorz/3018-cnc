from ttc3018_control.job import JobStreamer


def test_streams_one_line_per_ack() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append)
    job.start(["G21", "G1 X1", "M5"])
    assert sent == [b"G21\n"]
    assert job.completed == 0
    job.handle_response("ok")
    assert sent[-1] == b"G1 X1\n"
    job.handle_response("ok")
    job.handle_response("ok")
    assert job.state == "complete"
    assert job.completed == 3


def test_pause_waits_after_current_ack() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append)
    job.start(["G1 X1", "G1 X2"])
    job.pause()
    job.handle_response("ok")
    assert sent == [b"G1 X1\n"]
    job.resume()
    assert sent[-1] == b"G1 X2\n"


def test_error_fails_job_without_sending_more() -> None:
    sent: list[bytes] = []
    job = JobStreamer(sent.append)
    job.start(["G1 X1", "G1 X2"])
    assert job.handle_response("error:2")
    assert job.state == "failed"
    assert job.error == "error:2"
    assert len(sent) == 1


def test_send_failure_does_not_leave_job_active() -> None:
    def fail(_command: bytes) -> None:
        raise RuntimeError("connection lost")

    job = JobStreamer(fail)
    try:
        job.start(["G1 X1"])
    except RuntimeError:
        pass
    assert job.state == "failed"
