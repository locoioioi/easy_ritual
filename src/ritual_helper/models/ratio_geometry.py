from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


Ratio = float


class RatioPoint(BaseModel):
    x: Ratio = Field(ge=0.0, le=1.0)
    y: Ratio = Field(ge=0.0, le=1.0)

    def to_pixels(self, width: int, height: int) -> tuple[int, int]:
        return round(self.x * width), round(self.y * height)


class RatioRect(BaseModel):
    left: Ratio = Field(ge=0.0, le=1.0)
    top: Ratio = Field(ge=0.0, le=1.0)
    right: Ratio = Field(ge=0.0, le=1.0)
    bottom: Ratio = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "RatioRect":
        if self.right <= self.left:
            raise ValueError("right must be greater than left")
        if self.bottom <= self.top:
            raise ValueError("bottom must be greater than top")
        return self

    def center(self) -> RatioPoint:
        return RatioPoint(x=(self.left + self.right) / 2.0, y=(self.top + self.bottom) / 2.0)

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        return (
            round(self.left * width),
            round(self.top * height),
            round(self.right * width),
            round(self.bottom * height),
        )
