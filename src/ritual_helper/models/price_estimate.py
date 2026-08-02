from __future__ import annotations

from pydantic import BaseModel, Field


class PriceEstimate(BaseModel):
    amount: float | None = Field(default=None, ge=0.0)
    currency: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: str = "known"
