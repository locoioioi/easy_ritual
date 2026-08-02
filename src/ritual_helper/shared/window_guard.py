from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class ActiveWindowInfo:
    hwnd: int
    title: str
    process_id: int
    process_name: str
    process_path: str


def get_active_window_info() -> ActiveWindowInfo | None:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None

    title = _window_title(hwnd)
    process_id = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process_path = _process_path(process_id.value)
    return ActiveWindowInfo(
        hwnd=hwnd,
        title=title,
        process_id=process_id.value,
        process_name=Path(process_path).name if process_path else "",
        process_path=process_path,
    )


def active_window_is_allowed(application: dict[str, Any]) -> bool:
    if application.get("mode", "test") == "test":
        return True
    info = get_active_window_info()
    return info is not None and window_info_matches(info, application.get("target_window", {}))


def active_window_description() -> str:
    info = get_active_window_info()
    if info is None:
        return "no active window"
    return f"title={info.title!r}, process={info.process_name!r}"


def window_info_matches(info: ActiveWindowInfo, target_window: dict[str, Any]) -> bool:
    title_keywords = [str(value).lower() for value in target_window.get("title_keywords", [])]
    process_names = [str(value).lower() for value in target_window.get("process_names", [])]
    title = info.title.lower()
    process_name = info.process_name.lower()

    title_matches = not title_keywords or any(keyword in title for keyword in title_keywords)
    process_matches = not process_names or process_name in process_names
    return title_matches and process_matches


def _window_title(hwnd: int) -> str:
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _process_path(process_id: int) -> str:
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

