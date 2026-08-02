from __future__ import annotations

import logging
import time
from threading import Thread, Timer

import keyboard

from ritual_helper.controller.application_controller import ApplicationController

LOGGER = logging.getLogger(__name__)


class HotkeyController:
    def __init__(self, controller: ApplicationController) -> None:
        self.controller = controller
        self._last_dispatch: dict[str, float] = {}

    def run(self) -> None:
        self._add_hotkey("f2", self.controller.toggle_enabled, "F2", require_active_window=False)
        self._add_hotkey("t", self.controller.analyze_current_table, "T")
        self._add_hotkey("r", self.controller.reroll_and_process, "R")
        self._add_hotkey("ctrl+c", self._remember_checked_item_after_copy, "Ctrl+C")
        self._add_hotkey("f12", self.controller.stop, "F12", require_active_window=False)
        LOGGER.info("hotkeys registered: F2 toggle, T analyze, R reroll, Ctrl+C remember item, F12 stop")
        while not self.controller.state.stopping:
            time.sleep(0.1)
        keyboard.unhook_all_hotkeys()

    def _add_hotkey(self, key: str, action, action_name: str, require_active_window: bool = True) -> None:
        keyboard.add_hotkey(
            key,
            lambda: self._dispatch_hotkey(action_name, action, require_active_window),
        )

    def _dispatch_hotkey(self, action_name: str, action, require_active_window: bool) -> None:
        now = time.monotonic()
        debounce_seconds = 0.35 if action_name == "F2" else 0.6
        if now - self._last_dispatch.get(action_name, 0.0) < debounce_seconds:
            LOGGER.info("%s ignored because hotkey debounce is active", action_name)
            return
        self._last_dispatch[action_name] = now
        Thread(
            target=self.controller.run_hotkey,
            args=(action_name, action),
            kwargs={"require_active_window": require_active_window},
            daemon=True,
        ).start()

    def _remember_checked_item_after_copy(self) -> None:
        Timer(0.12, lambda: self.controller.run_hotkey("Ctrl+C", self.controller.remember_checked_item_from_clipboard)).start()
