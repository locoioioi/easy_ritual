from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ritual_helper.executor.click_backend import ClickBackend
from ritual_helper.models import BackendResult, RecordedClick, RitualPlan
from ritual_helper.shared.files import ensure_dir


class RenderBackend(ClickBackend):
    name = "render"

    def execute(self, plan: RitualPlan, output_dir: Path) -> BackendResult:
        ensure_dir(output_dir)
        image = Image.open(plan.source.image_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        width, height = image.size
        font = ImageFont.load_default()

        draw.rectangle(plan.board.to_pixels(width, height), outline=(255, 210, 90), width=4)
        clicks: list[RecordedClick] = []
        selected_index = 1
        for item in plan.items:
            color = self._decision_color(item.decision)
            rect = item.region.to_pixels(width, height)
            draw.rectangle(rect, outline=color, width=3)
            label = f"{item.item_id} {item.identification.display_name} {item.decision}"
            draw.text((rect[0], max(0, rect[1] - 14)), label, fill=color, font=font)
            if item.decision == "select":
                x, y = item.click_point.to_pixels(width, height)
                radius = 14
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 255, 255), width=3)
                draw.text((x - 3, y - 5), str(selected_index), fill=(255, 255, 255), font=font)
                clicks.append(RecordedClick(target=item.item_id, x=x, y=y))
                selected_index += 1

        artifact_path = output_dir / "selection-preview.png"
        image.save(artifact_path)
        return BackendResult(
            backend=self.name,
            status="rendered",
            clicks=clicks,
            artifact_path=str(artifact_path),
        )

    @staticmethod
    def _decision_color(decision: str) -> tuple[int, int, int]:
        if decision == "select":
            return (80, 220, 130)
        if decision == "review":
            return (245, 190, 70)
        return (180, 180, 180)
