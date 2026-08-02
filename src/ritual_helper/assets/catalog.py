from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class ExtractedAsset(BaseModel):
    internal_item_id: str = ""
    display_name: str = ""
    category: str = "unknown"
    source_path: str = ""
    extracted_path: Path | None = None
    asset_kind: str = ""
    content_hash: str | None = None
    size_bytes: int = Field(default=0, ge=0)
    needs_conversion: bool = False
    error: str | None = None


class ExtractedAssetManifest(BaseModel):
    schema_version: str
    created_at: str
    source: dict
    candidates: list[str] = Field(default_factory=list)
    assets: list[ExtractedAsset] = Field(default_factory=list)


class RuntimeIconAsset(BaseModel):
    internal_item_id: str
    display_name: str
    category: str
    source_path: str
    extracted_path: Path
    normalized_icon_path: Path
    content_hash: str
    perceptual_hash: str
    width: int
    height: int


class RuntimeAssetCatalog(BaseModel):
    schema_version: str = "1.0"
    assets: list[RuntimeIconAsset] = Field(default_factory=list)
