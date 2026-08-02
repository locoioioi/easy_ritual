from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class CapturedFrame(BaseModel):
    image_path: Path
    client_width: int = Field(gt=0)
    client_height: int = Field(gt=0)
    mode: str
    source: str
    screen_left: int = 0
    screen_top: int = 0
