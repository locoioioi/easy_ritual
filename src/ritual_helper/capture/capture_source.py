from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ritual_helper.models import CapturedFrame


class CaptureSource(ABC):
    @abstractmethod
    def capture(self, output_path: Path) -> CapturedFrame:
        raise NotImplementedError
