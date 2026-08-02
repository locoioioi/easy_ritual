from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ritual_helper.models.detected_item import DetectedItem
from ritual_helper.models.ratio_geometry import RatioPoint, RatioRect


SUPPORTED_SCHEMA_VERSION = "1.0"
SUPPORTED_UI_CONTROLS = {"reroll", "defer", "confirm_defer"}


class PlanSource(BaseModel):
    image_path: str
    client_width: int = Field(gt=0)
    client_height: int = Field(gt=0)
    mode: str
    screen_left: int = 0
    screen_top: int = 0


class PlanAction(BaseModel):
    action_id: str
    type: Literal["click"]
    target: str
    position: RatioPoint
    delay_before_ms: int = Field(default=0, ge=0)
    delay_after_ms: int = Field(ge=0)


class PlanSummary(BaseModel):
    items_detected: int = Field(ge=0)
    items_identified: int = Field(ge=0)
    items_selected: int = Field(ge=0)
    items_for_review: int = Field(ge=0)


class RitualPlan(BaseModel):
    schema_version: str
    plan_id: str
    created_at: datetime
    source: PlanSource
    board: RatioRect
    items: list[DetectedItem]
    actions: list[PlanAction]
    summary: PlanSummary

    @model_validator(mode="after")
    def validate_plan(self) -> "RitualPlan":
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        item_ids = {item.item_id for item in self.items}
        for action in self.actions:
            if action.target not in item_ids and action.target not in SUPPORTED_UI_CONTROLS:
                raise ValueError(f"action target is not an item or supported UI control: {action.target}")
        return self
