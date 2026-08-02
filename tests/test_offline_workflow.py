from __future__ import annotations

import copy
import json
from pathlib import Path

from ritual_helper.controller.application_controller import build_controller
from ritual_helper.shared.configuration import AppConfig, load_config


def test_one_shot_offline_workflow_writes_artifacts(tmp_path: Path) -> None:
    root = Path.cwd()
    base = load_config(root)
    application = copy.deepcopy(base.application)
    application["mode"] = "test"
    application["analyzer"] = "stub"
    application["output_dir"] = str(tmp_path / "output")
    application["fixture_screenshot"] = str(tmp_path / "fixtures" / "ritual.png")
    config = AppConfig(root=root, application=application, vision=base.vision, selection_policy=base.selection_policy)
    controller = build_controller(config)

    controller.toggle_enabled()
    result = controller.analyze_current_table()

    assert result is not None
    plan, execution_result = result
    assert plan.summary.items_selected == 1
    assert execution_result.status == "completed"
    assert (tmp_path / "output" / "plans" / "ritual_plan.json").exists()
    assert (tmp_path / "output" / "execution-results" / "execution_result.json").exists()
    assert (tmp_path / "output" / "debug" / "selection-preview.png").exists()


def test_debug_disabled_does_not_write_output_debug_folder(tmp_path: Path) -> None:
    root = Path.cwd()
    base = load_config(root)
    application = copy.deepcopy(base.application)
    application["mode"] = "test"
    application["debug_enabled"] = False
    application["analyzer"] = "stub"
    application["output_dir"] = str(tmp_path / "output")
    application["fixture_screenshot"] = str(tmp_path / "fixtures" / "ritual.png")
    config = AppConfig(root=root, application=application, vision=base.vision, selection_policy=base.selection_policy)
    controller = build_controller(config)

    controller.toggle_enabled()
    result = controller.analyze_current_table()

    assert result is not None
    assert (tmp_path / "output" / "plans" / "ritual_plan.json").exists()
    assert (tmp_path / "output" / "execution-results" / "execution_result.json").exists()
    assert not (tmp_path / "output" / "debug").exists()


def test_provided_ritual_fixture_detects_deferred_and_available_items(tmp_path: Path) -> None:
    root = Path.cwd()
    base = load_config(root)
    application = copy.deepcopy(base.application)
    application["mode"] = "test"
    application["analyzer"] = "grid"
    application["output_dir"] = str(tmp_path / "output")
    application["fixture_screenshot"] = "fixtures/screenshots/ritual-provided.jpg"
    config = AppConfig(root=root, application=application, vision=base.vision, selection_policy=base.selection_policy)
    controller = build_controller(config)

    controller.toggle_enabled()
    result = controller.analyze_current_table()

    assert result is not None
    plan, execution_result = result
    deferred_items = [item for item in plan.items if item.is_deferred]
    available_items = [item for item in plan.items if not item.is_deferred]
    selected_items = [item for item in plan.items if item.decision == "select"]
    review_items = [item for item in plan.items if item.decision == "review"]
    assert all(_item_cells_are_connected(item.grid_cells) for item in plan.items)
    assert max(len(item.grid_cells) for item in plan.items) <= 8
    assert len(plan.items) >= 1
    assert len(deferred_items) >= 1
    assert selected_items == deferred_items
    assert review_items == available_items
    assert len(plan.actions) == len(deferred_items)
    assert execution_result.status == "completed"
    assert (tmp_path / "output" / "debug" / "selection-preview.png").exists()
    debug_run = next((tmp_path / "output" / "debug").glob("run-*"))
    assert (debug_run / "grayscale-foreground-mask.png").exists()
    assert (debug_run / "available-foreground-mask.png").exists()
    assert (debug_run / "foreground-contours.png").exists()
    assert (debug_run / "contour-cell-footprints.png").exists()
    assert (debug_run / "mask-components.png").exists()
    assert not (debug_run / "foreground-mask.png").exists()
    assert not (debug_run / "grouped-items.png").exists()
    assert (debug_run / "item-groups.json").exists()


def test_second_ritual_fixture_filters_grey_cells_and_clicks_deferred_items(tmp_path: Path) -> None:
    root = Path.cwd()
    base = load_config(root)
    application = copy.deepcopy(base.application)
    application["mode"] = "test"
    application["analyzer"] = "grid"
    application["output_dir"] = str(tmp_path / "output")
    application["fixture_screenshot"] = "fixtures/screenshots/ritual-provided-2.jpg"
    config = AppConfig(root=root, application=application, vision=base.vision, selection_policy=base.selection_policy)
    controller = build_controller(config)

    controller.toggle_enabled()
    result = controller.analyze_current_table()

    assert result is not None
    plan, execution_result = result
    deferred_items = [item for item in plan.items if item.is_deferred]
    available_items = [item for item in plan.items if not item.is_deferred]
    assert all(_item_cells_are_connected(item.grid_cells) for item in plan.items)
    assert deferred_items
    assert all(item.decision == "select" for item in deferred_items)
    assert all(item.decision == "review" for item in available_items)
    assert max(len(item.grid_cells) for item in plan.items) <= 8
    assert any(len(item.grid_cells) == 6 for item in plan.items)
    assert len(plan.actions) == len(deferred_items)
    assert plan.summary.items_selected == len(deferred_items)
    assert execution_result.status == "completed"
    debug_run = next((tmp_path / "output" / "debug").glob("run-*"))
    assert (debug_run / "grayscale-foreground-mask.png").exists()
    assert (debug_run / "available-foreground-mask.png").exists()
    assert (debug_run / "foreground-contours.png").exists()
    assert (debug_run / "contour-cell-footprints.png").exists()
    assert (debug_run / "mask-components.png").exists()
    assert not (debug_run / "foreground-mask.png").exists()
    assert not (debug_run / "grouped-items.png").exists()
    assert (debug_run / "item-groups.json").exists()


def test_reroll_workflow_records_reroll_defer_analysis_and_confirm(tmp_path: Path) -> None:
    root = Path.cwd()
    base = load_config(root)
    application = copy.deepcopy(base.application)
    application["mode"] = "test"
    application["analyzer"] = "grid"
    application["output_dir"] = str(tmp_path / "output")
    application["fixture_screenshot"] = "fixtures/screenshots/ritual-provided-2.jpg"
    config = AppConfig(root=root, application=application, vision=base.vision, selection_policy=base.selection_policy)
    controller = build_controller(config)

    controller.toggle_enabled()
    result = controller.reroll_and_process()

    assert result is not None
    plan, execution_result = result
    assert execution_result.status == "completed"
    debug_runs = sorted((tmp_path / "output" / "debug").glob("run-*"))
    assert len(debug_runs) == 1
    debug_run = debug_runs[0]
    pre_clicks = json.loads((debug_run / "reroll-actions" / "recorded_clicks.json").read_text(encoding="utf-8"))
    final_clicks = json.loads((debug_run / "recorded_clicks.json").read_text(encoding="utf-8"))
    assert [click["target"] for click in pre_clicks] == ["reroll", "defer"]
    assert (debug_run / "before-reroll.png").exists()
    assert (debug_run / "captured-frame.png").exists()
    assert (tmp_path / "output" / "screenshots" / "after-reroll.png").exists()
    assert plan.source.image_path.endswith("after-reroll.png")
    assert final_clicks[-1]["target"] == "confirm_defer"
    assert [action.target for action in plan.actions][-1] == "confirm_defer"
    assert all(action.delay_after_ms == 300 for action in plan.actions if action.target != "confirm_defer")
    assert plan.actions[-1].delay_before_ms == 250
    assert plan.actions[-1].delay_after_ms == 250


def _has_overlapping_item_regions(items) -> bool:
    for index, item in enumerate(items):
        for other in items[index + 1 :]:
            horizontal_overlap = item.region.left < other.region.right and item.region.right > other.region.left
            vertical_overlap = item.region.top < other.region.bottom and item.region.bottom > other.region.top
            if horizontal_overlap and vertical_overlap:
                return True
    return False


def _item_cells_are_connected(grid_cells: list[str]) -> bool:
    parsed = {_parse_grid_cell(cell) for cell in grid_cells}
    if not parsed:
        return False
    visited = set()
    stack = [next(iter(parsed))]
    visited.add(stack[0])
    while stack:
        row, column = stack.pop()
        for neighbor in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if neighbor in parsed and neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    return visited == parsed


def _parse_grid_cell(cell: str) -> tuple[int, int]:
    row_text, column_text = cell.removeprefix("r").split("c", maxsplit=1)
    return int(row_text), int(column_text)
