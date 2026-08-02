from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ritual_helper.models import IdentificationResult, PriceEstimate


SECTION_SEPARATOR = "--------"


class ParsedTooltip(BaseModel):
    item_class: str | None = None
    rarity: str | None = None
    name: str
    base_type: str | None = None
    stack_size_current: int | None = Field(default=None, ge=0)
    stack_size_max: int | None = Field(default=None, ge=0)
    description: str = ""
    raw_text: str

    @property
    def category(self) -> str:
        if self.item_class:
            return normalize_category(self.item_class)
        if self.rarity and self.rarity.lower() == "currency":
            return "currency"
        return "unknown"

    def to_identification_result(self) -> IdentificationResult:
        return IdentificationResult(
            internal_item_id=f"tooltip/{slugify(self.name)}",
            display_name=self.name,
            category=self.category,
            status="tooltip",
            score=1.0,
            confidence_gap=1.0,
            identification_scope="tooltip",
            requires_tooltip=False,
        )

    def to_price_estimate(self) -> PriceEstimate:
        return PriceEstimate(amount=None, currency="exalted", confidence=0.0, status="unknown")


def parse_tooltip(text: str) -> ParsedTooltip:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("tooltip text is empty")

    sections = [
        [line.strip() for line in section.splitlines() if line.strip()]
        for section in normalized.split(SECTION_SEPARATOR)
    ]
    sections = [section for section in sections if section]
    header = sections[0]

    item_class = _header_value(header, "Item Class")
    rarity = _header_value(header, "Rarity")
    non_header_lines = [line for line in header if not _is_key_value_line(line)]
    if not non_header_lines:
        raise ValueError("tooltip item name not found")

    name = non_header_lines[0]
    base_type = non_header_lines[1] if len(non_header_lines) > 1 else None
    stack_current, stack_max = _stack_size(sections)
    description = "\n".join(line for section in sections[1:] for line in section if not line.startswith("Stack Size:"))

    return ParsedTooltip(
        item_class=item_class,
        rarity=rarity,
        name=name,
        base_type=base_type,
        stack_size_current=stack_current,
        stack_size_max=stack_max,
        description=description,
        raw_text=normalized,
    )


def normalize_category(item_class: str) -> str:
    value = item_class.strip().lower()
    if value in {"currency", "omen", "rune", "soul core"}:
        return "currency"
    if "fragment" in value:
        return "fragment"
    if "map" in value or "waystone" in value:
        return "map"
    if value in {"ring", "amulet", "belt", "jewel"}:
        return "equipment"
    if any(part in value for part in ["weapon", "armour", "armor", "quiver", "shield", "focus"]):
        return "equipment"
    return value.replace(" ", "_")


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _header_value(lines: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _is_key_value_line(line: str) -> bool:
    return bool(re.match(r"^[A-Za-z ]+:", line))


def _stack_size(sections: list[list[str]]) -> tuple[int | None, int | None]:
    for section in sections:
        for line in section:
            match = re.match(r"^Stack Size:\s*(\d+)\s*/\s*(\d+)$", line)
            if match:
                return int(match.group(1)), int(match.group(2))
    return None, None
