from __future__ import annotations

import json
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from ritual_helper.analyzer.tooltip_parser import ParsedTooltip
from ritual_helper.models import PriceEstimate


class PriceProvider(ABC):
    @abstractmethod
    def price(self, tooltip: ParsedTooltip) -> PriceEstimate:
        raise NotImplementedError


class StaticPriceProvider(PriceProvider):
    def __init__(self, prices: dict[str, float], currency: str = "exalted") -> None:
        self.prices = {name.lower(): amount for name, amount in prices.items()}
        self.currency = currency

    def price(self, tooltip: ParsedTooltip) -> PriceEstimate:
        amount = self.prices.get(tooltip.name.lower())
        if amount is None:
            return PriceEstimate(amount=None, currency=self.currency, confidence=0.0, status="unknown")
        return PriceEstimate(amount=amount, currency=self.currency, confidence=1.0, status="known")


class PoeNinjaPriceProvider(PriceProvider):
    """Best-effort poe.ninja lookup for tooltip-identified PoE2 rewards.

    poe.ninja says its PoE2 unique/economy views estimate prices from the official
    trade API rather than a PoE2 River API, so this provider treats failures as
    normal and returns an unknown price instead of failing the run.
    """

    def __init__(self, league: str, timeout_seconds: float = 8.0, currency: str = "exalted") -> None:
        self.league = league
        self.timeout_seconds = timeout_seconds
        self.currency = _supported_currency(currency)
        self._cache: dict[tuple[str, str], PriceEstimate] = {}

    def price(self, tooltip: ParsedTooltip) -> PriceEstimate:
        for endpoint_type in self._endpoint_types(tooltip):
            key = (endpoint_type, tooltip.name.lower())
            if key not in self._cache:
                if endpoint_type == "Currency":
                    self._cache[key] = self._lookup_exchange_currency(tooltip.name)
                else:
                    self._cache[key] = self._lookup(endpoint_type, tooltip.name)
            estimate = self._cache[key]
            if estimate.amount is not None:
                return estimate
        return PriceEstimate(amount=None, currency=self.currency, confidence=0.0, status="unknown")

    def _lookup_exchange_currency(self, item_name: str) -> PriceEstimate:
        query = urllib.parse.urlencode({"league": self.league, "type": "Currency"})
        url = f"https://poe.ninja/poe2/api/economy/exchange/current/overview?{query}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "poe2-ritual-helper/0.1"})
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return PriceEstimate(amount=None, currency="exalted", confidence=0.0, status="unknown")

        items_by_id = {item.get("id"): item for item in payload.get("items", [])}
        currency_per_divine = self._currency_per_divine(payload, self.currency)
        for line in payload.get("lines", []):
            item = items_by_id.get(line.get("id"), {})
            if item.get("name", "").lower() != item_name.lower():
                continue
            divine_value = line.get("primaryValue")
            if divine_value is None or currency_per_divine is None:
                return PriceEstimate(amount=None, currency=self.currency, confidence=0.0, status="unknown")
            return PriceEstimate(
                amount=float(divine_value) * currency_per_divine,
                currency=self.currency,
                confidence=0.7,
                status="known",
            )
        return PriceEstimate(amount=None, currency=self.currency, confidence=0.0, status="unknown")

    def _lookup(self, endpoint_type: str, item_name: str) -> PriceEstimate:
        query = urllib.parse.urlencode({"league": self.league, "type": endpoint_type})
        url = f"https://poe.ninja/poe2/api/economy/stash/current/item/overview?{query}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "poe2-ritual-helper/0.1"})
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return PriceEstimate(amount=None, currency=self.currency, confidence=0.0, status="unknown")

        for line in payload.get("lines", []):
            if line.get("name", "").lower() != item_name.lower():
                continue
            amount = line.get(f"{self.currency}Value")
            currency = self.currency
            if amount is not None:
                return PriceEstimate(amount=float(amount), currency=currency, confidence=0.7, status="known")
        return PriceEstimate(amount=None, currency=self.currency, confidence=0.0, status="unknown")

    @staticmethod
    def _endpoint_types(tooltip: ParsedTooltip) -> list[str]:
        item_class = (tooltip.item_class or "").lower()
        rarity = (tooltip.rarity or "").lower()
        if item_class == "omen":
            return ["Omens"]
        if "currency" in rarity or item_class in {"rune", "soul core"}:
            return ["Currency"]
        if "map" in item_class or "waystone" in item_class:
            return ["Map", "UniqueMap"]
        if rarity == "unique":
            if any(part in item_class for part in ["ring", "amulet", "belt"]):
                return ["UniqueAccessory"]
            if any(part in item_class for part in ["armour", "armor", "boots", "gloves", "helmet"]):
                return ["UniqueArmour"]
            if any(part in item_class for part in ["weapon", "staff", "bow", "wand", "sceptre", "shield"]):
                return ["UniqueWeapon"]
            return ["UniqueAccessory", "UniqueArmour", "UniqueWeapon"]
        return ["BaseType"]

    @staticmethod
    def _exalted_per_divine(payload: dict) -> float | None:
        return PoeNinjaPriceProvider._currency_per_divine(payload, "exalted")

    @staticmethod
    def _currency_per_divine(payload: dict, currency: str) -> float | None:
        if currency == "divine":
            return 1.0
        for line in payload.get("lines", []):
            if line.get("id") == currency and line.get("primaryValue"):
                return 1.0 / float(line["primaryValue"])
        return None


class Poe2ScoutPriceProvider(PriceProvider):
    """POE2Scout lookup adapted from RuneshapePriceChecker's pricing flow."""

    BASE_URL = "https://api.poe2scout.com/poe2"
    CURRENCY_CATEGORIES = ("currency", "expedition", "uncutgems", "runes", "ritual", "verisium")
    UNIQUE_CATEGORIES = ("weapon", "armour", "accessory")

    def __init__(
        self,
        league: str,
        timeout_seconds: float = 8.0,
        reference_currency: str = "exalted",
    ) -> None:
        self.league = league
        self.timeout_seconds = timeout_seconds
        self.reference_currency = _supported_currency(reference_currency)
        self._league_short_name: str | None = None
        self._category_cache: dict[str, dict[str, PriceEstimate]] = {}

    def price(self, tooltip: ParsedTooltip) -> PriceEstimate:
        for category in self._categories_for_tooltip(tooltip):
            prices = self._prices_for_category(category)
            estimate = prices.get(_normalize_key(tooltip.name))
            if estimate is not None:
                return estimate
        return PriceEstimate(amount=None, currency=self.reference_currency, confidence=0.0, status="unknown")

    def _prices_for_category(self, category: str) -> dict[str, PriceEstimate]:
        if category not in self._category_cache:
            self._category_cache[category] = self._fetch_category_prices(category)
        return self._category_cache[category]

    def _fetch_category_prices(self, category: str) -> dict[str, PriceEstimate]:
        try:
            short_league = self._resolve_short_league()
            if category in self.UNIQUE_CATEGORIES:
                path = f"Leagues/{short_league}/Uniques/ByCategory"
                query = {"Category": category, "ReferenceCurrency": self.reference_currency, "SmoothingDays": 1}
            else:
                path = f"Leagues/{short_league}/Currencies/ByCategory"
                query = {"Category": category, "ReferenceCurrency": self.reference_currency, "SmoothingDays": 1}
            prices: dict[str, PriceEstimate] = {}
            for row in self._fetch_all_pages(path, query):
                amount = _as_float(row.get("CurrentPrice"))
                if amount is None or amount <= 0:
                    continue
                estimate = PriceEstimate(
                    amount=amount,
                    currency=self.reference_currency,
                    confidence=0.75,
                    status="known",
                )
                for name in self._row_names(row):
                    prices[_normalize_key(name)] = estimate
            return prices
        except Exception:
            return {}

    def _resolve_short_league(self) -> str:
        if self._league_short_name is not None:
            return self._league_short_name
        try:
            for row in self._fetch_json_array("Leagues"):
                if str(row.get("Value") or "").lower() == self.league.lower():
                    self._league_short_name = str(row.get("ShortName") or _fallback_league_short_name(self.league))
                    return self._league_short_name
        except Exception:
            pass
        self._league_short_name = _fallback_league_short_name(self.league)
        return self._league_short_name

    def _fetch_all_pages(self, path: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        page = 1
        per_page = 200
        items: list[dict[str, Any]] = []
        while True:
            page_items = self._fetch_json_array(path, {**query, "Page": page, "PerPage": per_page})
            items.extend(page_items)
            if len(page_items) < per_page:
                return items
            page += 1

    def _fetch_json_array(self, path: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = self._fetch_json(path, query)
        if isinstance(payload, dict) and isinstance(payload.get("Items"), list):
            return [row for row in payload["Items"] if isinstance(row, dict)]
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    def _fetch_json(self, path: str, query: dict[str, Any] | None = None) -> Any:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"User-Agent": "poe2-ritual-helper/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @classmethod
    def _categories_for_tooltip(cls, tooltip: ParsedTooltip) -> list[str]:
        item_class = (tooltip.item_class or "").lower()
        rarity = (tooltip.rarity or "").lower()
        if "currency" in rarity or item_class in {"rune", "soul core", "omen"}:
            return list(cls.CURRENCY_CATEGORIES)
        if rarity == "unique":
            if any(part in item_class for part in ["ring", "amulet", "belt"]):
                return ["accessory"]
            if any(part in item_class for part in ["armour", "armor", "boots", "gloves", "helmet"]):
                return ["armour"]
            if any(part in item_class for part in ["weapon", "staff", "bow", "wand", "sceptre", "shield"]):
                return ["weapon"]
            return list(cls.UNIQUE_CATEGORIES)
        return []

    @staticmethod
    def _row_names(row: dict[str, Any]) -> list[str]:
        names = []
        for key in ("Text", "Name"):
            name = str(row.get(key) or "").strip()
            if name:
                names.append(name)
        metadata = row.get("ItemMetadata")
        if isinstance(metadata, dict):
            for key in ("name", "base_type"):
                name = str(metadata.get(key) or "").strip()
                if name:
                    names.append(name)
        return list(dict.fromkeys(names))


def build_price_provider(config: dict[str, Any], selection_policy: dict[str, Any] | None = None) -> PriceProvider:
    pricing = config.get("pricing", {})
    source = str(pricing.get("source", "poe2scout")).lower()
    league = str(pricing.get("league", "Runes of Aldur"))
    timeout_seconds = float(pricing.get("timeout_seconds", 8.0))
    currency = _supported_currency((selection_policy or {}).get("price_currency", "exalted"))
    if source in {"poe.ninja", "poeninja", "ninja"}:
        return PoeNinjaPriceProvider(league=league, timeout_seconds=timeout_seconds, currency=currency)
    if source in {"static", "none", "off"}:
        return StaticPriceProvider({}, currency=currency)
    return Poe2ScoutPriceProvider(league=league, timeout_seconds=timeout_seconds, reference_currency=currency)


def _normalize_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _fallback_league_short_name(value: str) -> str:
    parts = value.split()
    return parts[0].casefold() if parts else value.casefold()


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _supported_currency(value: Any) -> str:
    currency = str(value).strip().lower()
    if currency not in {"chaos", "exalted", "divine"}:
        return "exalted"
    return currency
