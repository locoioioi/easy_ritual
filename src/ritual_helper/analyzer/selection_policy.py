from __future__ import annotations

from ritual_helper.analyzer.tooltip_parser import ParsedTooltip
from ritual_helper.models import PriceEstimate
from ritual_helper.models.selection_decision import Decision


class TooltipSelectionPolicy:
    def __init__(self, minimum_value: float, price_currency: str = "exalted") -> None:
        self.minimum_value = minimum_value
        self.price_currency = price_currency

    def decide(self, tooltip: ParsedTooltip, price: PriceEstimate) -> tuple[Decision, str]:
        if tooltip.item_class and tooltip.item_class.lower() == "omen":
            return "select", "Omen reward identified from tooltip; defer/select immediately"
        if price.amount is None:
            return "review", "Tooltip identified item, but price lookup is unavailable"
        if price.currency != self.price_currency:
            return "review", f"Price is in {price.currency}, expected {self.price_currency}"
        if price.amount >= self.minimum_value:
            return "select", f"Estimated value {price.amount:g} {price.currency} meets threshold"
        return "skip", f"Estimated value {price.amount:g} {price.currency} is below threshold"
