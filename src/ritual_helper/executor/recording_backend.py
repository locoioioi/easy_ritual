from __future__ import annotations

from pathlib import Path

from ritual_helper.executor.click_backend import ClickBackend
from ritual_helper.models import BackendResult, RecordedClick, RitualPlan
from ritual_helper.shared.files import write_json


class RecordingBackend(ClickBackend):
    name = "recording"

    def execute(self, plan: RitualPlan, output_dir: Path) -> BackendResult:
        clicks = [
            RecordedClick(
                target=action.target,
                x=action.position.to_pixels(plan.source.client_width, plan.source.client_height)[0],
                y=action.position.to_pixels(plan.source.client_width, plan.source.client_height)[1],
            )
            for action in plan.actions
        ]
        artifact_path = output_dir / "recorded_clicks.json"
        write_json(artifact_path, [click.model_dump(mode="json") for click in clicks])
        return BackendResult(
            backend=self.name,
            status="recorded",
            clicks=clicks,
            artifact_path=str(artifact_path),
        )
