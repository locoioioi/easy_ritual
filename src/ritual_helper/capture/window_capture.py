from __future__ import annotations

import ctypes
import json
import logging
from pathlib import Path

from PIL import ImageGrab

from ritual_helper.capture.capture_source import CaptureSource
from ritual_helper.models import CapturedFrame
from ritual_helper.shared.files import ensure_dir

LOGGER = logging.getLogger(__name__)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        LOGGER.debug("SetProcessDpiAwarenessContext failed", exc_info=True)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        LOGGER.debug("SetProcessDpiAwareness failed", exc_info=True)

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        LOGGER.debug("SetProcessDPIAware failed", exc_info=True)


_enable_dpi_awareness()


class WindowCapture(CaptureSource):
    def capture(self, output_path: Path) -> CapturedFrame:
        ensure_dir(output_path.parent)
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("cannot find active foreground window")

        rect = RECT()
        if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("cannot read active window client rect")

        origin = POINT(0, 0)
        if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise RuntimeError("cannot map active window client origin")

        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise RuntimeError("active window client area is empty")

        image = ImageGrab.grab(bbox=(origin.x, origin.y, origin.x + width, origin.y + height))
        image.save(output_path)
        self._write_capture_metadata(output_path, hwnd, origin, rect, width, height, image.size)
        return CapturedFrame(
            image_path=output_path,
            client_width=width,
            client_height=height,
            mode="live",
            source=f"hwnd:{hwnd}",
            screen_left=origin.x,
            screen_top=origin.y,
        )

    def _write_capture_metadata(
        self,
        output_path: Path,
        hwnd: int,
        origin: POINT,
        rect: RECT,
        width: int,
        height: int,
        image_size: tuple[int, int],
    ) -> None:
        metadata_path = output_path.with_suffix(".capture.json")
        data = {
            "hwnd": hwnd,
            "client_rect": {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": width,
                "height": height,
            },
            "screen_origin": {"x": origin.x, "y": origin.y},
            "image_size": {"width": image_size[0], "height": image_size[1]},
        }
        metadata_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
