from __future__ import annotations

from pydantic import BaseModel, Field

from ritual_helper.models.identification_result import IdentificationResult
from ritual_helper.models.price_estimate import PriceEstimate
from ritual_helper.models.ratio_geometry import RatioPoint, RatioRect
from ritual_helper.models.selection_decision import Decision


class DetectedItem(BaseModel):
    item_id: str
    region: RatioRect
    click_point: RatioPoint
    grid_cells: list[str] = Field(default_factory=list)
    is_deferred: bool = False
    identification: IdentificationResult
    estimated_price: PriceEstimate
    decision: Decision
    decision_reason: str
