from __future__ import annotations

from pydantic import BaseModel

from ritual_helper.models.price_estimate import PriceEstimate
from ritual_helper.models.selection_decision import Decision


class CheckedItemDecision(BaseModel):
    cache_key: str
    item_name: str
    item_class: str | None = None
    rarity: str | None = None
    raw_text: str
    price: PriceEstimate
    decision: Decision
    decision_reason: str
    shouldSelect: bool
