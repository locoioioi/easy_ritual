from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    root: Path
    application: dict[str, Any]
    vision: dict[str, Any]
    selection_policy: dict[str, Any]

    @property
    def output_dir(self) -> Path:
        return self.root / self.application.get("output_dir", "output")

    @property
    def fixture_screenshot(self) -> Path:
        return self.root / self.application.get("fixture_screenshot", "fixtures/screenshots/ritual.png")

    @property
    def mode(self) -> str:
        return self.application.get("mode", "test")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_config(root: Path) -> AppConfig:
    config_dir = root / "config"
    return AppConfig(
        root=root,
        application=load_json(config_dir / "application.json"),
        vision=load_json(config_dir / "vision.json"),
        selection_policy=load_json(config_dir / "selection-policy.json"),
    )
