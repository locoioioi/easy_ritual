from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ritual_helper.models import BackendResult, RitualPlan


class ClickBackend(ABC):
    name: str

    @abstractmethod
    def execute(self, plan: RitualPlan, output_dir: Path) -> BackendResult:
        raise NotImplementedError
