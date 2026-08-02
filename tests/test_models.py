from __future__ import annotations

import pytest

from ritual_helper.models import RatioPoint, RatioRect
from ritual_helper.models.ritual_plan import PlanAction, PlanSource, PlanSummary, RitualPlan


def test_ratio_rect_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError, match="right must be greater"):
        RatioRect(left=0.5, top=0.1, right=0.4, bottom=0.2)


def test_ratio_point_maps_to_pixels() -> None:
    assert RatioPoint(x=0.25, y=0.5).to_pixels(1920, 1080) == (480, 540)


def test_plan_rejects_unknown_action_target() -> None:
    with pytest.raises(ValueError, match="action target"):
        RitualPlan(
            schema_version="1.0",
            plan_id="ritual-test",
            created_at="2026-08-01T18:00:00+07:00",
            source=PlanSource(
                image_path="fixture.png",
                client_width=1920,
                client_height=1080,
                mode="test",
            ),
            board=RatioRect(left=0.1, top=0.1, right=0.5, bottom=0.5),
            items=[],
            actions=[
                PlanAction(
                    action_id="action-001",
                    type="click",
                    target="missing-item",
                    position=RatioPoint(x=0.2, y=0.2),
                    delay_after_ms=0,
                )
            ],
            summary=PlanSummary(items_detected=0, items_identified=0, items_selected=0, items_for_review=0),
        )
