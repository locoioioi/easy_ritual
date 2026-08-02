from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


Decision = Literal["select", "skip", "review"]


class SelectionDecision(BaseModel):
    decision: Decision
    decision_reason: str
