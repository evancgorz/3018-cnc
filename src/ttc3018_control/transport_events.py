"""Queue for transport events with a low-cost availability notification."""

from __future__ import annotations

import queue
import threading
from typing import Any


class TransportEventQueue(queue.Queue[Any]):
    """A normal queue that can wake a polling owner when an item arrives.

    Consumers still own and drain the queue.  ``wait_for_item`` is only a wake
    hint: checking the queue before and after clearing the event closes the
    race with a producer that enqueues between those operations.
    """

    def __init__(self) -> None:
        super().__init__()
        self._item_available = threading.Event()

    def put(self, item: Any, block: bool = True, timeout: float | None = None) -> None:
        super().put(item, block=block, timeout=timeout)
        self._item_available.set()

    def get(self, block: bool = True, timeout: float | None = None) -> Any:
        item = super().get(block=block, timeout=timeout)
        if self.empty():
            self._item_available.clear()
        return item

    def wait_for_item(self, timeout: float | None = None) -> bool:
        """Wait until an event is queued or ``timeout`` expires."""

        if not self.empty():
            return True
        self._item_available.clear()
        if not self.empty():
            self._item_available.set()
            return True
        return self._item_available.wait(timeout)
