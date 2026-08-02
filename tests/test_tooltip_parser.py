from __future__ import annotations

from ritual_helper.analyzer.tooltip_parser import parse_tooltip


OMEN_TEXT = """Item Class: Omen
Rarity: Currency
Omen of Sinistral Exaltation
--------
Stack Size: 1/10
--------
While this item is active in your inventory your next
Exalted Orb will add only prefix modifiers
--------
Right click this item in your inventory to set it to be active. This item is consumed when triggered.
"""


def test_parse_omen_tooltip() -> None:
    parsed = parse_tooltip(OMEN_TEXT)

    assert parsed.item_class == "Omen"
    assert parsed.rarity == "Currency"
    assert parsed.name == "Omen of Sinistral Exaltation"
    assert parsed.stack_size_current == 1
    assert parsed.stack_size_max == 10
    assert parsed.category == "currency"
    assert "Exalted Orb" in parsed.description


def test_tooltip_to_identification_result() -> None:
    identification = parse_tooltip(OMEN_TEXT).to_identification_result()

    assert identification.display_name == "Omen of Sinistral Exaltation"
    assert identification.internal_item_id == "tooltip/omen-of-sinistral-exaltation"
    assert identification.status == "tooltip"
    assert identification.score == 1.0
