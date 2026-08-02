from __future__ import annotations

import copy
from pathlib import Path

from ritual_helper.analyzer.price_service import PriceProvider
from ritual_helper.analyzer.tooltip_parser import ParsedTooltip
from ritual_helper.controller.application_controller import build_controller
from ritual_helper.models import CheckedItemDecision, PriceEstimate
from ritual_helper.shared.configuration import AppConfig, load_config


JEWELLER_TOOLTIP = """Item Class: Currency
Rarity: Currency
Perfect Jeweller's Orb
--------
Stack Size: 1/10
"""


class MutablePriceProvider(PriceProvider):
    def __init__(self) -> None:
        self.amount = 60.0
        self.calls = 0

    def price(self, tooltip: ParsedTooltip) -> PriceEstimate:
        self.calls += 1
        return PriceEstimate(amount=self.amount, currency="exalted", confidence=1.0, status="known")


def test_checked_item_cache_reuses_should_select_without_repricing(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    price_provider = MutablePriceProvider()
    controller.price_provider = price_provider

    first = controller.remember_checked_item(JEWELLER_TOOLTIP)
    price_provider.amount = 1.0
    second = controller.remember_checked_item(JEWELLER_TOOLTIP)

    assert first is second
    assert first.shouldSelect is True
    assert first.decision == "select"
    assert price_provider.calls == 1
    assert len(controller.checked_items) == 1


def test_reroll_clears_checked_item_cache(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.price_provider = MutablePriceProvider()
    controller.remember_checked_item(JEWELLER_TOOLTIP)

    controller.toggle_enabled()
    result = controller.reroll_and_process()

    assert result is not None
    assert controller.checked_items == []


def test_live_tooltip_review_updates_review_items_and_rebuilds_actions(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.config.application["mode"] = "live"
    controller._notify = lambda *args, **kwargs: None

    def fake_review(_plan, item):
        return CheckedItemDecision(
            cache_key=f"test/{item.item_id}",
            item_name=f"Priced {item.item_id}",
            item_class="Currency",
            rarity="Currency",
            raw_text=f"""Item Class: Currency
Rarity: Currency
Priced {item.item_id}
--------
Stack Size: 1/10
""",
            price=PriceEstimate(amount=20.0, currency="exalted", confidence=1.0, status="known"),
            decision="select",
            decision_reason="test selected item",
            shouldSelect=True,
        ), {"status": "copied", "attempts": [{"copied": True}], "x": 1, "y": 1}

    controller._review_item_tooltip = fake_review

    plan, _execution_result = controller._run_analysis_workflow(output_dir=tmp_path / "output")

    assert all(item.decision == "select" for item in plan.items)
    assert plan.summary.items_for_review == 0
    assert plan.summary.items_identified >= 1
    assert len(plan.actions) == len(plan.items)
    assert (tmp_path / "output" / "debug" / "run-001" / "tooltip-review.json").exists()


def _controller(tmp_path: Path):
    root = Path.cwd()
    base = load_config(root)
    application = copy.deepcopy(base.application)
    application["mode"] = "test"
    application["analyzer"] = "grid"
    application["output_dir"] = str(tmp_path / "output")
    application["fixture_screenshot"] = "fixtures/screenshots/ritual-provided-2.jpg"
    config = AppConfig(root=root, application=application, vision=base.vision, selection_policy=base.selection_policy)
    return build_controller(config)
