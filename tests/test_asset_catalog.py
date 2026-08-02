from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from ritual_helper.assets.catalog import ExtractedAssetManifest
from ritual_helper.assets.normalization import normalize_icon


def test_extracted_asset_manifest_accepts_expected_json(tmp_path: Path) -> None:
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"not-used")
    payload = {
        "schema_version": "1.0",
        "created_at": "2026-08-01T19:00:00+07:00",
        "source": {"extractor": "LibGGPK3"},
        "assets": [
            {
                "internal_item_id": "Art/2DItems/Currency/Test",
                "display_name": "Test",
                "category": "currency",
                "source_path": "Art/2DItems/Currency/Test.png",
                "extracted_path": str(icon),
                "asset_kind": "icon",
                "content_hash": "abc",
                "size_bytes": 12,
                "needs_conversion": False,
            }
        ],
    }

    manifest = ExtractedAssetManifest.model_validate_json(json.dumps(payload))

    assert manifest.assets[0].display_name == "Test"
    assert manifest.assets[0].category == "currency"


def test_normalize_icon_writes_fixed_canvas(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "normalized.png"
    image = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    for x in range(8, 24):
        for y in range(4, 12):
            image.putpixel((x, y), (220, 40, 90, 255))
    image.save(source)

    width, height, perceptual_hash = normalize_icon(source, output)

    assert output.exists()
    assert Image.open(output).size == (64, 64)
    assert width == 16
    assert height == 8
    assert len(perceptual_hash) == 16
