from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock


@dataclass
class ApplicationState:
    enabled: bool = False
    stopping: bool = False
    target_window: str | None = None
    cancel_requested: Event = field(default_factory=Event)


class BusyGuard:
    def __init__(self) -> None:
        self._lock = Lock()
        self.busy = False

    def acquire(self) -> bool:
        with self._lock:
            if self.busy:
                return False
            self.busy = True
            return True

    def release(self) -> None:
        with self._lock:
            self.busy = False
