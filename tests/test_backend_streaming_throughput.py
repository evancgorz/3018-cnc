from __future__ import annotations

from threading import Event, Thread

from ttc3018_control.application.state import ApplicationState
from ttc3018_control.backend.runtime import BackendRuntime
from ttc3018_control.job import JobStreamer
from ttc3018_control.transport_events import TransportEventQueue


class _Event:
    def __init__(self, kind: str, text: str) -> None:
        self.kind = kind
        self.text = text


class _FakeApplication:
    """Immediate-ack transport for exercising only the backend sender loop."""

    def __init__(self, command_count: int) -> None:
        self.state = ApplicationState()
        self.connected = False
        self.events = TransportEventQueue()
        self.responses = 0
        self.done = Event()
        self.streamer = JobStreamer(self._send_line)
        self.streamer.start(("G1 X0.1",) * command_count)

    def _send_line(self, _command: bytes) -> None:
        self.events.put(_Event("rx", "ok"))

    def transport_events(self):
        return self.events

    def handle_transport_response(self, response: str, _feed: float):
        if self.streamer.handle_response(response):
            self.responses += 1
            if self.streamer.state == "complete":
                self.done.set()
        return None, False

    def application_events(self):
        return ()


def test_transport_event_queue_wakes_a_waiting_consumer() -> None:
    events = TransportEventQueue()
    started = Event()
    woke = Event()

    def wait() -> None:
        started.set()
        woke.set() if events.wait_for_item(1.0) else None

    thread = Thread(target=wait)
    thread.start()
    assert started.wait(0.5)
    events.put(_Event("rx", "ok"))
    thread.join(0.5)

    assert woke.is_set()
    assert events.get_nowait().text == "ok"


def test_backend_run_wakes_for_a_late_fake_controller_ack(tmp_path) -> None:
    app = _FakeApplication(command_count=1)
    app.events.get_nowait()  # The fake controller has not accepted the line yet.
    waiting = Event()
    wait_for_item = app.events.wait_for_item

    def observe_wait(timeout=None):
        waiting.set()
        return wait_for_item(timeout)

    app.events.wait_for_item = observe_wait
    runtime = BackendRuntime(tmp_path, application=app)
    stop = Event()
    runner = Thread(target=runtime.run, kwargs={"stop_event": stop, "interval": 0.5})
    runner.start()

    assert waiting.wait(0.5)
    app.events.put(_Event("rx", "ok"))
    assert app.done.wait(0.5)
    stop.set()
    runner.join(2.0)

    assert not runner.is_alive()
    assert app.streamer.state == "complete"


def test_backend_run_keeps_periodic_polling_when_disconnected(tmp_path) -> None:
    app = _FakeApplication(command_count=1)
    app.events.get_nowait()
    app.transport_events = lambda: ()
    stop = Event()
    poll_count = 0

    def poll_live_jog() -> None:
        nonlocal poll_count
        poll_count += 1
        if poll_count == 2:
            stop.set()

    app.poll_live_jog = poll_live_jog
    runtime = BackendRuntime(tmp_path, application=app)
    runtime.run(stop_event=stop, interval=0.01)

    assert poll_count == 2


def test_backend_drains_fake_stream_responses_in_bounded_batches(tmp_path) -> None:
    app = _FakeApplication(command_count=1000)
    runtime = BackendRuntime(tmp_path, application=app)

    runtime.poll_once()

    assert app.responses == runtime.MAX_TRANSPORT_EVENTS_PER_POLL
    assert app.streamer.state == "running"
    assert not app.events.empty()

    polls = 1
    while app.streamer.state == "running":
        runtime.poll_once()
        polls += 1

    assert app.responses == 1000
    assert app.streamer.state == "complete"
    assert polls == 4


def test_backend_run_keeps_draining_pending_fake_responses_without_sleep(tmp_path) -> None:
    app = _FakeApplication(command_count=10000)
    runtime = BackendRuntime(tmp_path, application=app)
    stop = Event()
    runner = Thread(target=runtime.run, kwargs={"stop_event": stop, "interval": 0.25})
    runner.start()
    assert app.done.wait(2.0)
    stop.set()
    runner.join(0.5)

    assert not runner.is_alive()
    assert app.responses == 10000
    assert app.streamer.state == "complete"
