from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from ritual_helper.models import (
    CapturedFrame,
    DetectedItem,
    IdentificationResult,
    PlanAction,
    PlanSource,
    PlanSummary,
    PriceEstimate,
    RatioRect,
    RitualPlan,
)
from ritual_helper.shared.files import ensure_dir


class StubRitualAnalyzer:
    def __init__(self, board: RatioRect, item_delay_ms: int) -> None:
        self.board = board
        self.item_delay_ms = item_delay_ms

    def analyze(self, frame: CapturedFrame, debug_dir: Path) -> RitualPlan:
        ensure_dir(debug_dir)
        self._save_board_crop(frame, debug_dir)

        items = [
            self._item(
                "item-001",
                RatioRect(left=0.196, top=0.316, right=0.237, bottom=0.384),
                "Metadata/Items/Currency/StubHighValue",
                "Stub High Value Currency",
                14.5,
                "select",
                "Stub analyzer selected this item to validate the offline execution flow",
            ),
            self._item(
                "item-002",
                RatioRect(left=0.318, top=0.438, right=0.383, bottom=0.542),
                "Metadata/Items/Currency/StubReview",
                "Stub Review Item",
                7.0,
                "review",
                "Stub analyzer left this item for review because its value is below the configured threshold",
            ),
        ]
        actions = [
            PlanAction(
                action_id=f"action-{index:03d}",
                type="click",
                target=item.item_id,
                position=item.click_point,
                delay_after_ms=self.item_delay_ms,
            )
            for index, item in enumerate(items, start=1)
            if item.decision == "select"
        ]
        return RitualPlan(
            schema_version="1.0",
            plan_id=f"ritual-{datetime.now(ZoneInfo('Asia/Saigon')).strftime('%Y%m%d-%H%M%S')}",
            created_at=datetime.now(ZoneInfo("Asia/Saigon")),
            source=PlanSource(
                image_path=str(frame.image_path),
                client_width=frame.client_width,
                client_height=frame.client_height,
                mode=frame.mode,
                screen_left=frame.screen_left,
                screen_top=frame.screen_top,
            ),
            board=self.board,
            items=items,
            actions=actions,
            summary=PlanSummary(
                items_detected=len(items),
                items_identified=len(items),
                items_selected=sum(1 for item in items if item.decision == "select"),
                items_for_review=sum(1 for item in items if item.decision == "review"),
            ),
        )

    def _item(
        self,
        item_id: str,
        region: RatioRect,
        internal_item_id: str,
        display_name: str,
        price: float,
        decision: str,
        reason: str,
    ) -> DetectedItem:
        return DetectedItem(
            item_id=item_id,
            region=region,
            click_point=region.center(),
            identification=IdentificationResult(
                internal_item_id=internal_item_id,
                display_name=display_name,
                category="currency",
                status="matched",
                score=0.95,
                confidence_gap=0.1,
            ),
            estimated_price=PriceEstimate(amount=price, currency="exalted", confidence=0.9),
            decision=decision,
            decision_reason=reason,
        )

    def _save_board_crop(self, frame: CapturedFrame, debug_dir: Path) -> None:
        image = Image.open(frame.image_path).convert("RGB")
        image.crop(self.board.to_pixels(frame.client_width, frame.client_height)).save(debug_dir / "board.png")
