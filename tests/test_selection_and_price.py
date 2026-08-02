from __future__ import annotations

from ritual_helper.analyzer.price_service import StaticPriceProvider
from ritual_helper.analyzer.price_service import PoeNinjaPriceProvider
from ritual_helper.analyzer.price_service import Poe2ScoutPriceProvider
from ritual_helper.analyzer.price_service import build_price_provider
from ritual_helper.analyzer.selection_policy import TooltipSelectionPolicy
from ritual_helper.analyzer.tooltip_parser import parse_tooltip


def test_omen_tooltip_is_selected_without_price() -> None:
    tooltip = parse_tooltip(
        """Item Class: Omen
Rarity: Currency
Omen of Sinistral Exaltation
--------
Stack Size: 1/10
"""
    )
    price = StaticPriceProvider({}).price(tooltip)

    decision, reason = TooltipSelectionPolicy(minimum_value=10).decide(tooltip, price)

    assert decision == "select"
    assert "Omen" in reason


def test_non_omen_uses_price_threshold() -> None:
    tooltip = parse_tooltip(
        """Item Class: Currency
Rarity: Currency
Perfect Jeweller's Orb
--------
Stack Size: 1/10
"""
    )
    price = StaticPriceProvider({"Perfect Jeweller's Orb": 20}).price(tooltip)

    decision, _ = TooltipSelectionPolicy(minimum_value=10).decide(tooltip, price)

    assert decision == "select"


def test_poe_ninja_exchange_currency_payload_converts_to_exalted() -> None:
    payload = {
        "lines": [
            {"id": "exalted", "primaryValue": 0.001},
            {"id": "perfect-jewellers-orb", "primaryValue": 0.09},
        ],
        "items": [
            {"id": "perfect-jewellers-orb", "name": "Perfect Jeweller's Orb"},
        ],
    }

    assert PoeNinjaPriceProvider._exalted_per_divine(payload) == 1000


def test_poe2scout_currency_payload_returns_exalted_price() -> None:
    class FakePoe2Scout(Poe2ScoutPriceProvider):
        def _fetch_json(self, path, query=None):
            if path == "Leagues":
                return [{"Value": "Runes of Aldur", "ShortName": "runes"}]
            assert path == "Leagues/runes/Currencies/ByCategory"
            assert query["Category"] == "currency"
            assert query["ReferenceCurrency"] == "exalted"
            return {
                "Items": [
                    {"Text": "Exalted Orb", "CurrentPrice": 1},
                    {"Text": "Perfect Jeweller's Orb", "CurrentPrice": 162.5},
                ]
            }

    tooltip = parse_tooltip(
        """Item Class: Currency
Rarity: Currency
Perfect Jeweller's Orb
--------
Stack Size: 1/10
"""
    )

    price = FakePoe2Scout("Runes of Aldur").price(tooltip)

    assert price.amount == 162.5
    assert price.currency == "exalted"
    assert price.status == "known"


def test_poe2scout_ritual_category_prices_omens() -> None:
    class FakePoe2Scout(Poe2ScoutPriceProvider):
        def _fetch_json(self, path, query=None):
            if path == "Leagues":
                return [{"Value": "Runes of Aldur", "ShortName": "runes"}]
            if query["Category"] == "ritual":
                return {"Items": [{"Text": "Omen of Resurgence", "CurrentPrice": 7.3}]}
            return {"Items": []}

    tooltip = parse_tooltip(
        """Item Class: Omen
Rarity: Currency
Omen of Resurgence
--------
Stack Size: 1/10
"""
    )

    price = FakePoe2Scout("Runes of Aldur").price(tooltip)

    assert price.amount == 7.3
    assert price.status == "known"


def test_poe2scout_unique_payload_matches_unique_name_field() -> None:
    class FakePoe2Scout(Poe2ScoutPriceProvider):
        def _fetch_json(self, path, query=None):
            if path == "Leagues":
                return [{"Value": "Runes of Aldur", "ShortName": "runes"}]
            assert path == "Leagues/runes/Uniques/ByCategory"
            return {
                "Items": [
                    {
                        "Text": "Heartbound Loop Pearl Ring",
                        "Name": "Heartbound Loop",
                        "CurrentPrice": 1,
                    }
                ]
            }

    tooltip = parse_tooltip(
        """Item Class: Rings
Rarity: Unique
Heartbound Loop
Pearl Ring
--------
"""
    )

    price = FakePoe2Scout("Runes of Aldur").price(tooltip)

    assert price.amount == 1
    assert price.status == "known"


def test_poe2scout_uses_configured_reference_currency() -> None:
    class FakePoe2Scout(Poe2ScoutPriceProvider):
        def _fetch_json(self, path, query=None):
            if path == "Leagues":
                return [{"Value": "Runes of Aldur", "ShortName": "runes"}]
            assert query["ReferenceCurrency"] == "divine"
            return {"Items": [{"Text": "Perfect Jeweller's Orb", "CurrentPrice": 0.39}]}

    tooltip = parse_tooltip(
        """Item Class: Currency
Rarity: Currency
Perfect Jeweller's Orb
--------
Stack Size: 1/10
"""
    )

    price = FakePoe2Scout("Runes of Aldur", reference_currency="divine").price(tooltip)

    assert price.amount == 0.39
    assert price.currency == "divine"


def test_price_provider_config_defaults_to_poe2scout() -> None:
    provider = build_price_provider(
        {"pricing": {"source": "poe2scout", "league": "Runes of Aldur"}},
        {"price_currency": "chaos"},
    )

    assert isinstance(provider, Poe2ScoutPriceProvider)
    assert provider.reference_currency == "chaos"


def test_selection_policy_uses_configured_currency_threshold() -> None:
    tooltip = parse_tooltip(
        """Item Class: Currency
Rarity: Currency
Perfect Jeweller's Orb
--------
Stack Size: 1/10
"""
    )
    price = StaticPriceProvider({"Perfect Jeweller's Orb": 0.4}, currency="divine").price(tooltip)

    decision, reason = TooltipSelectionPolicy(minimum_value=0.3, price_currency="divine").decide(tooltip, price)

    assert decision == "select"
    assert "divine" in reason
