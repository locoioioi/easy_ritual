from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ritual_helper.executor.click_backend import ClickBackend
from ritual_helper.models import ExecutionResult, RitualPlan


class RitualExecutor:
    def __init__(self, backends: list[ClickBackend]) -> None:
        self.backends = backends

    def execute(self, plan: RitualPlan, output_dir: Path) -> ExecutionResult:
        results = [backend.execute(plan, output_dir) for backend in self.backends]
        status = "completed" if all(result.status in {"recorded", "rendered", "clicked"} for result in results) else "partial"
        return ExecutionResult(
            plan_id=plan.plan_id,
            created_at=datetime.now(ZoneInfo("Asia/Saigon")),
            status=status,
            backend_results=results,
        )
