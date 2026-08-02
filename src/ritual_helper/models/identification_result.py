from __future__ import annotations

from pydantic import BaseModel, Field


class IdentificationResult(BaseModel):
    internal_item_id: str
    display_name: str
    category: str
    status: str
    score: float = Field(ge=0.0, le=1.0)
    confidence_gap: float = Field(ge=0.0, le=1.0)
    identification_scope: str = "exact"
    requires_tooltip: bool = False
