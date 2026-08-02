from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ritual_helper.capture.capture_source import CaptureSource
from ritual_helper.models import CapturedFrame
from ritual_helper.shared.files import ensure_dir


class FixtureCapture(CaptureSource):
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def capture(self, output_path: Path) -> CapturedFrame:
        ensure_dir(self.fixture_path.parent)
        if not self.fixture_path.exists():
            self._create_placeholder(self.fixture_path)

        ensure_dir(output_path.parent)
        image = Image.open(self.fixture_path).convert("RGB")
        image.save(output_path)
        width, height = image.size
        return CapturedFrame(
            image_path=output_path,
            client_width=width,
            client_height=height,
            mode="test",
            source=str(self.fixture_path),
        )

    @staticmethod
    def _create_placeholder(path: Path) -> None:
        width, height = 1920, 1080
        image = Image.new("RGB", (width, height), (18, 18, 20))
        draw = ImageDraw.Draw(image)
        board = (308, 264, 937, 793)
        draw.rectangle(board, outline=(180, 137, 84), width=3, fill=(38, 34, 31))
        cell_w = (board[2] - board[0]) / 10
        cell_h = (board[3] - board[1]) / 10
        for i in range(11):
            x = round(board[0] + i * cell_w)
            y = round(board[1] + i * cell_h)
            draw.line((x, board[1], x, board[3]), fill=(70, 58, 48), width=1)
            draw.line((board[0], y, board[2], y), fill=(70, 58, 48), width=1)
        draw.ellipse((380, 330, 455, 405), fill=(94, 180, 210), outline=(220, 230, 235), width=3)
        draw.rectangle((610, 470, 735, 585), fill=(152, 120, 224), outline=(232, 220, 255), width=3)
        image.save(path)
