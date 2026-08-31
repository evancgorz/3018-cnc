"""Small Qt thread-pool bridge for CPU and file work.

Workers return values only.  ViewModel and controller state is always updated
by the queued signal on the GUI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


@dataclass(frozen=True)
class TaskResult:
    token: int
    value: Any = None
    error: BaseException | None = None


class _TaskSignals(QObject):
    completed = Signal(object)


class _Task(QRunnable):
    def __init__(self, token: int, function: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.token = token
        self.function = function
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = TaskResult(self.token, value=self.function())
        except BaseException as exc:  # returned to GUI thread for formatting
            result = TaskResult(self.token, error=exc)
        self.signals.completed.emit(result)


class TaskRunner(QObject):
    """Submit immutable-input tasks and route completion back to Qt."""

    completed = Signal(object)

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self.pool = pool or QThreadPool.globalInstance()
        self._next_token = 0
        self._tasks: dict[int, _Task] = {}

    def submit(self, function: Callable[[], Any]) -> int:
        self._next_token += 1
        token = self._next_token
        task = _Task(token, function)
        task.signals.completed.connect(self._on_completed)
        self._tasks[token] = task
        self.pool.start(task)
        return token

    @Slot(object)
    def _on_completed(self, result: TaskResult) -> None:
        self._tasks.pop(result.token, None)
        self.completed.emit(result)

    def active_count(self) -> int:
        return len(self._tasks)
