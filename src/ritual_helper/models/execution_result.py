from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RecordedClick(BaseModel):
    type: str = "click"
    target: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class BackendResult(BaseModel):
    backend: str
    status: str
    clicks: list[RecordedClick] = Field(default_factory=list)
    artifact_path: str | None = None
    message: str | None = None


class ExecutionResult(BaseModel):
    schema_version: str = "1.0"
    plan_id: str
    created_at: datetime
    status: str
    backend_results: list[BackendResult]
