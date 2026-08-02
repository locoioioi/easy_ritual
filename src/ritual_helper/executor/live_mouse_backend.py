from __future__ import annotations

import ctypes
import time
from pathlib import Path
from typing import Any, Callable

from ritual_helper.executor.click_backend import ClickBackend
from ritual_helper.models import BackendResult, RecordedClick, RitualPlan
from ritual_helper.shared.window_guard import active_window_description, active_window_is_allowed


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_MOUSE = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


class LiveMouseBackend(ClickBackend):
    name = "live_mouse"

    def __init__(self, application_config: dict[str, Any], should_cancel: Callable[[], bool] | None = None) -> None:
        self.application_config = application_config
        self.should_cancel = should_cancel or (lambda: False)

    def execute(self, plan: RitualPlan, output_dir: Path) -> BackendResult:
        clicks: list[RecordedClick] = []
        clicked_points: set[tuple[int, int]] = set()
        mouse_down_up_ms = int(self.application_config.get("delays", {}).get("mouse_down_up_ms", 35))
        for action in plan.actions:
            if self.should_cancel():
                return BackendResult(
                    backend=self.name,
                    status="blocked",
                    clicks=clicks,
                    message="execution cancelled",
                )
            if not active_window_is_allowed(self.application_config):
                return BackendResult(
                    backend=self.name,
                    status="blocked",
                    clicks=clicks,
                    message=f"active window is not PoE 2: {active_window_description()}",
                )
            if action.delay_before_ms:
                if self._sleep(action.delay_before_ms):
                    return BackendResult(
                        backend=self.name,
                        status="blocked",
                        clicks=clicks,
                        message="execution cancelled",
                    )
            x, y = action.position.to_pixels(plan.source.client_width, plan.source.client_height)
            point_key = (round(x / 4), round(y / 4))
            if point_key in clicked_points:
                continue
            clicked_points.add(point_key)
            screen_x = plan.source.screen_left + x
            screen_y = plan.source.screen_top + y
            if self.should_cancel():
                return BackendResult(
                    backend=self.name,
                    status="blocked",
                    clicks=clicks,
                    message="execution cancelled",
                )
            ctypes.windll.user32.SetCursorPos(screen_x, screen_y)
            self._send_mouse_button(MOUSEEVENTF_LEFTDOWN)
            if self._sleep(mouse_down_up_ms):
                return BackendResult(
                    backend=self.name,
                    status="blocked",
                    clicks=clicks,
                    message="execution cancelled",
                )
            self._send_mouse_button(MOUSEEVENTF_LEFTUP)
            clicks.append(RecordedClick(target=action.target, x=x, y=y))
            if action.delay_after_ms:
                if self._sleep(action.delay_after_ms):
                    return BackendResult(
                        backend=self.name,
                        status="blocked",
                        clicks=clicks,
                        message="execution cancelled",
                    )
        return BackendResult(
            backend=self.name,
            status="clicked",
            clicks=clicks,
        )

    def _sleep(self, milliseconds: int) -> bool:
        deadline = time.monotonic() + milliseconds / 1000
        while time.monotonic() < deadline:
            if self.should_cancel():
                return True
            time.sleep(min(0.03, max(0, deadline - time.monotonic())))
        return self.should_cancel()

    @staticmethod
    def _send_mouse_button(flags: int) -> None:
        extra = ctypes.c_ulong(0)
        event = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=0,
                    dy=0,
                    mouseData=0,
                    dwFlags=flags,
                    time=0,
                    dwExtraInfo=ctypes.pointer(extra),
                )
            ),
        )
        ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
