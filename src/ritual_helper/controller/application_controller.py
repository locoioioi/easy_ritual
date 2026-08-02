from __future__ import annotations

import logging
import shutil
import threading
import time
import ctypes
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, TypeVar
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from ritual_helper.analyzer.price_service import PriceProvider
from ritual_helper.analyzer.selection_policy import TooltipSelectionPolicy
from ritual_helper.analyzer.tooltip_parser import ParsedTooltip, parse_tooltip, slugify
from ritual_helper.capture.capture_source import CaptureSource
from ritual_helper.controller.application_state import ApplicationState, BusyGuard
from ritual_helper.executor.ritual_executor import RitualExecutor
from ritual_helper.models import CheckedItemDecision, DetectedItem, ExecutionResult, PlanAction, PlanSource, PlanSummary, RatioPoint, RatioRect, RitualPlan
from ritual_helper.shared.clipboard import read_clipboard_text, write_clipboard_text
from ritual_helper.shared.configuration import AppConfig
from ritual_helper.shared.files import ensure_dir, write_json, write_model_json
from ritual_helper.shared.window_guard import active_window_description, active_window_is_allowed

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43


class WorkflowCancelled(Exception):
    pass


class ApplicationController:
    def __init__(
        self,
        config: AppConfig,
        capture_source: CaptureSource,
        analyzer,
        executor: RitualExecutor,
        price_provider: PriceProvider,
        selection_policy: TooltipSelectionPolicy,
    ) -> None:
        self.config = config
        self.capture_source = capture_source
        self.analyzer = analyzer
        self.executor = executor
        self.price_provider = price_provider
        self.selection_policy = selection_policy
        self.state = ApplicationState()
        self.busy_guard = BusyGuard()
        self.checked_items: list[CheckedItemDecision] = []
        self._selected_tooltip_keys: set[str] = set()
        self._selected_click_points: set[tuple[int, int]] = set()

    def toggle_enabled(self) -> None:
        if self.state.enabled:
            self.state.enabled = False
            self.state.cancel_requested.set()
            self.state.target_window = None
            self._notify("helper disabled", "stop", global_overlay=True)
            LOGGER.info("helper disabled")
            return

        self.state.cancel_requested.clear()
        self.state.enabled = True
        self.state.target_window = "fixture" if self.config.mode == "test" else active_window_description()
        self._notify(f"helper enabled for {self.state.target_window}", "start", global_overlay=True)
        LOGGER.info("helper enabled for %s", self.state.target_window)

    def stop(self) -> None:
        self.state.stopping = True
        self.state.cancel_requested.set()
        LOGGER.info("stop requested")

    def run_hotkey(self, action_name: str, action: Callable[[], T], require_active_window: bool = True) -> T | None:
        if require_active_window and not self._active_window_allowed(action_name):
            return None
        return action()

    def analyze_current_table(self, require_enabled: bool = True) -> tuple[RitualPlan, ExecutionResult] | None:
        if not self._active_window_allowed("T"):
            return None
        if require_enabled and not self.state.enabled:
            self._notify("T ignored: helper is disabled", "warn")
            LOGGER.info("T ignored because helper is disabled")
            return None
        if not self.busy_guard.acquire():
            self._notify("T ignored: workflow already running", "warn")
            LOGGER.info("T ignored because a workflow is already running")
            return None
        try:
            self._notify("T analysis started", "start")
            result = self._run_analysis_workflow()
            plan, _execution_result = result
            self._notify(f"T analysis done: {plan.summary.items_detected} items, {plan.summary.items_selected} selected", "done")
            return result
        except WorkflowCancelled:
            LOGGER.info("analysis workflow cancelled")
            return None
        except Exception:
            self._notify("T analysis failed", "error")
            LOGGER.exception("analysis workflow failed")
            return None
        finally:
            self.busy_guard.release()

    def reroll_and_process(self) -> tuple[RitualPlan, ExecutionResult] | None:
        if not self._active_window_allowed("R"):
            return None
        if not self.state.enabled:
            self._notify("R ignored: helper is disabled", "warn")
            LOGGER.info("R ignored because helper is disabled")
            return None
        if not self.busy_guard.acquire():
            self._notify("R ignored: workflow already running", "warn")
            LOGGER.info("R ignored because a workflow is already running")
            return None
        try:
            self.clear_checked_items()
            self._notify("R reroll workflow started", "start")
            LOGGER.info("reroll workflow: reroll -> defer -> analyze -> click selected -> confirm")
            result = self._run_reroll_workflow()
            plan, _execution_result = result
            self._notify(f"R workflow done: {plan.summary.items_detected} items, {plan.summary.items_selected} selected", "done")
            return result
        except WorkflowCancelled:
            LOGGER.info("reroll workflow cancelled")
            return None
        except Exception:
            self._notify("R workflow failed", "error")
            LOGGER.exception("reroll workflow failed")
            return None
        finally:
            self.busy_guard.release()

    def _notify(self, message: str, kind: str = "info", global_overlay: bool = False) -> None:
        timestamp = datetime.now(ZoneInfo("Asia/Saigon")).strftime("%Y-%m-%d %H:%M:%S")
        try:
            output_dir = ensure_dir(self.config.output_dir)
            (output_dir / "status.txt").write_text(f"{timestamp} {message}\n", encoding="utf-8")
        except Exception:
            LOGGER.exception("failed to write helper status")

        if self.config.mode == "live" and (global_overlay or active_window_is_allowed(self.config.application)):
            self._show_overlay(message, kind)

    def _show_overlay(self, message: str, kind: str) -> None:
        def worker() -> None:
            try:
                import tkinter as tk
            except Exception:
                LOGGER.debug("tkinter notification overlay unavailable", exc_info=True)
                return

            colors = {
                "start": ("#10243a", "#8bd3ff"),
                "done": ("#10361f", "#8cffad"),
                "warn": ("#3a2c10", "#ffd66b"),
                "error": ("#3a1212", "#ff8b8b"),
                "stop": ("#252525", "#dddddd"),
            }
            background, foreground = colors.get(kind, ("#202020", "#ffffff"))
            try:
                root = tk.Tk()
                root.overrideredirect(True)
                root.attributes("-topmost", True)
                root.configure(background=background)
                label = tk.Label(
                    root,
                    text=message,
                    background=background,
                    foreground=foreground,
                    font=("Segoe UI", 14, "bold"),
                    padx=18,
                    pady=12,
                )
                label.pack()
                root.update_idletasks()
                screen_width = root.winfo_screenwidth()
                window_width = root.winfo_width()
                x = max(20, screen_width - window_width - 40)
                y = 80
                root.geometry(f"+{x}+{y}")
                root.after(1400, root.destroy)
                root.mainloop()
            except Exception:
                LOGGER.debug("notification overlay failed", exc_info=True)

        threading.Thread(target=worker, daemon=True).start()

    def _run_analysis_workflow(
        self,
        extra_actions: list[PlanAction] | None = None,
        output_dir: Path | None = None,
        debug_dir: Path | None = None,
        screenshot_name: str = "current-ritual.png",
    ) -> tuple[RitualPlan, ExecutionResult]:
        output_dir = ensure_dir(output_dir or self.config.output_dir)
        if debug_dir is None:
            debug_dir_context = self._debug_dir_context(output_dir)
            debug_dir = debug_dir_context.__enter__()
        else:
            debug_dir_context = None
        screenshot_path = output_dir / "screenshots" / screenshot_name
        try:
            frame = self.capture_source.capture(screenshot_path)
            self._raise_if_cancelled()
            self._selected_tooltip_keys.clear()
            self._selected_click_points.clear()
            shutil.copyfile(frame.image_path, debug_dir / "captured-frame.png")
            capture_metadata_path = frame.image_path.with_suffix(".capture.json")
            if capture_metadata_path.exists():
                shutil.copyfile(capture_metadata_path, debug_dir / "captured-frame.capture.json")

            plan = self.analyzer.analyze(frame, debug_dir)
            self._raise_if_cancelled()
            if self.config.mode == "live":
                self._execute_initial_selected_items(plan, debug_dir)
            self._raise_if_cancelled()
            plan = self._review_tooltip_items_if_live(plan, debug_dir)
            self._raise_if_cancelled()
            if extra_actions:
                plan = plan.model_copy(update={"actions": [*plan.actions, *extra_actions]})
            plan = TypeAdapter(RitualPlan).validate_python(plan.model_dump(mode="python"))
            plan_path = output_dir / "plans" / "ritual_plan.json"
            write_model_json(plan_path, plan)
            if self._debug_enabled():
                write_model_json(debug_dir / "ritual_plan.json", plan)

            execution_plan = self._final_execution_plan(plan, extra_actions)
            result = self.executor.execute(execution_plan, debug_dir)
            self._raise_if_cancelled()
            result = TypeAdapter(ExecutionResult).validate_python(result.model_dump(mode="python"))
            result_path = output_dir / "execution-results" / "execution_result.json"
            write_model_json(result_path, result)
            if self._debug_enabled():
                write_model_json(debug_dir / "execution_result.json", result)

            preview_path = debug_dir / "selection-preview.png"
            if self._debug_enabled() and preview_path.exists():
                shutil.copyfile(preview_path, output_dir / "debug" / "selection-preview.png")

            LOGGER.info("plan written to %s", plan_path)
            LOGGER.info("execution result written to %s", result_path)
            return plan, result
        finally:
            if debug_dir_context is not None:
                debug_dir_context.__exit__(None, None, None)

    def _run_reroll_workflow(self) -> tuple[RitualPlan, ExecutionResult]:
        output_dir = ensure_dir(self.config.output_dir)
        debug_dir_context = self._debug_dir_context(output_dir)
        debug_dir = debug_dir_context.__enter__()
        try:
            before_path = output_dir / "screenshots" / "before-reroll.png"
            before_frame = self.capture_source.capture(before_path)
            self._raise_if_cancelled()
            shutil.copyfile(before_frame.image_path, debug_dir / "before-reroll.png")
            before_metadata_path = before_frame.image_path.with_suffix(".capture.json")
            if before_metadata_path.exists():
                shutil.copyfile(before_metadata_path, debug_dir / "before-reroll.capture.json")

            pre_plan = self._ui_action_plan(
                plan_id=f"ritual-reroll-{datetime.now(ZoneInfo('Asia/Saigon')).strftime('%Y%m%d-%H%M%S')}",
                source=PlanSource(
                    image_path=str(before_frame.image_path),
                    client_width=before_frame.client_width,
                    client_height=before_frame.client_height,
                    mode=before_frame.mode,
                    screen_left=before_frame.screen_left,
                    screen_top=before_frame.screen_top,
                ),
                actions=[
                    self._ui_click_action("action-reroll", "reroll", "after_reroll_ms"),
                    self._ui_click_action("action-defer", "defer", "after_defer_ms", delay_before_key="before_defer_ms"),
                ],
            )
            pre_result = self.executor.execute(pre_plan, debug_dir / "reroll-actions")
            self._raise_if_cancelled()
            if self._debug_enabled():
                write_model_json(debug_dir / "reroll_actions_result.json", pre_result)

            confirm_action = self._ui_click_action(
                "action-confirm-defer",
                "confirm_defer",
                "after_confirm_ms",
                delay_before_key="before_confirm_defer_ms",
            )
            return self._run_analysis_workflow(
                extra_actions=[confirm_action],
                output_dir=output_dir,
                debug_dir=debug_dir,
                screenshot_name="after-reroll.png",
            )
        finally:
            debug_dir_context.__exit__(None, None, None)

    def _ui_action_plan(self, plan_id: str, source: PlanSource, actions: list[PlanAction]) -> RitualPlan:
        return RitualPlan(
            schema_version="1.0",
            plan_id=plan_id,
            created_at=datetime.now(ZoneInfo("Asia/Saigon")),
            source=source,
            board=RatioRect(**self.config.vision["board"]),
            items=[],
            actions=actions,
            summary=PlanSummary(items_detected=0, items_identified=0, items_selected=0, items_for_review=0),
        )

    def _ui_click_action(
        self,
        action_id: str,
        target: str,
        delay_key: str,
        delay_before_key: str | None = None,
    ) -> PlanAction:
        return PlanAction(
            action_id=action_id,
            type="click",
            target=target,
            position=RatioPoint(**self.config.application["ui_controls"][target]),
            delay_before_ms=int(self.config.application["delays"].get(delay_before_key, 0)) if delay_before_key else 0,
            delay_after_ms=int(self.config.application["delays"][delay_key]),
        )

    def _execute_initial_selected_items(self, plan: RitualPlan, debug_dir: Path) -> None:
        self._raise_if_cancelled()
        selected_items = [item for item in plan.items if item.decision == "select"]
        selected_actions = []
        for item in selected_items:
            if not self._mark_click_point_if_new(plan, item):
                LOGGER.info("skipped duplicate initial click for %s at %s", item.item_id, item.click_point)
                continue
            selected_actions.extend(action for action in plan.actions if action.target == item.item_id)
        if not selected_actions:
            return
        delay_before_ms = int(self.config.application["delays"].get("before_deferred_item_click_ms", 0))
        selected_actions = [
            action.model_copy(update={"delay_before_ms": delay_before_ms})
            for action in selected_actions
        ]
        LOGGER.info("selecting %s already-deferred items before tooltip review", len(selected_actions))
        self._notify(f"selecting {len(selected_actions)} deferred items", "start")
        selected_plan = plan.model_copy(update={"actions": selected_actions})
        result = self.executor.execute(selected_plan, debug_dir / "preselected-items")
        write_model_json(debug_dir / "preselected_items_result.json", result)
        self._raise_if_cancelled()

    def _execute_review_selected_item(self, plan: RitualPlan, item: DetectedItem, debug_dir: Path) -> None:
        self._raise_if_cancelled()
        if not self._mark_click_point_if_new(plan, item):
            LOGGER.info("skipped duplicate reviewed click for %s at %s", item.item_id, item.click_point)
            return
        action = self._item_click_action(item, f"action-priced-{item.item_id}")
        item_plan = plan.model_copy(update={"items": [item], "actions": [action]})
        result = self.executor.execute(item_plan, debug_dir / "priced-item-actions" / item.item_id)
        write_model_json(debug_dir / "priced-item-actions" / f"{item.item_id}.json", result)
        self._raise_if_cancelled()

    def _item_click_action(self, item: DetectedItem, action_id: str) -> PlanAction:
        return PlanAction(
            action_id=action_id,
            type="click",
            target=item.item_id,
            position=item.click_point,
            delay_after_ms=int(self.config.application["delays"]["after_item_click_ms"]),
        )

    def _mark_click_point_if_new(self, plan: RitualPlan, item: DetectedItem) -> bool:
        x, y = item.click_point.to_pixels(plan.source.client_width, plan.source.client_height)
        key = (round(x / 4), round(y / 4))
        if key in self._selected_click_points:
            return False
        self._selected_click_points.add(key)
        return True

    def _final_execution_plan(self, plan: RitualPlan, extra_actions: list[PlanAction] | None) -> RitualPlan:
        if self.config.mode != "live":
            return plan
        return plan.model_copy(update={"actions": list(extra_actions or [])})

    def clear_checked_items(self) -> None:
        self.checked_items.clear()
        LOGGER.info("cleared checked item decision cache")

    def remember_checked_item_from_clipboard(self) -> CheckedItemDecision | None:
        if not self._active_window_allowed("Ctrl+C"):
            return None
        try:
            return self.remember_checked_item(read_clipboard_text())
        except Exception:
            LOGGER.exception("failed to remember checked item from clipboard")
            return None

    def _active_window_allowed(self, action_name: str) -> bool:
        if active_window_is_allowed(self.config.application):
            return True
        LOGGER.info("%s ignored because active window is not PoE 2: %s", action_name, active_window_description())
        return False

    def remember_checked_item(self, tooltip_text: str) -> CheckedItemDecision:
        tooltip = parse_tooltip(tooltip_text)
        cache_key = self._tooltip_cache_key(tooltip)
        cached = self.checked_item_for_key(cache_key)
        if cached is not None:
            LOGGER.info("reused checked item decision for %s: shouldSelect=%s", cached.item_name, cached.shouldSelect)
            return cached

        price = self.price_provider.price(tooltip)
        decision, reason = self.selection_policy.decide(tooltip, price)
        checked_item = CheckedItemDecision(
            cache_key=cache_key,
            item_name=tooltip.name,
            item_class=tooltip.item_class,
            rarity=tooltip.rarity,
            raw_text=tooltip.raw_text,
            price=price,
            decision=decision,
            decision_reason=reason,
            shouldSelect=decision == "select",
        )
        self.checked_items.append(checked_item)
        LOGGER.info("remembered checked item %s: shouldSelect=%s", checked_item.item_name, checked_item.shouldSelect)
        return checked_item

    def _review_tooltip_items_if_live(self, plan: RitualPlan, debug_dir: Path) -> RitualPlan:
        if self.config.mode != "live":
            return plan
        review_items = [
            item
            for item in plan.items
            if item.decision == "review" and item.identification.requires_tooltip
        ]
        if not review_items:
            return plan

        reviewed_items = []
        decisions = []
        self._notify(f"reviewing {len(review_items)} item tooltips", "start")
        for item in plan.items:
            self._raise_if_cancelled()
            if item not in review_items:
                reviewed_items.append(item)
                continue

            checked_item, copy_status = self._review_item_tooltip(plan, item)
            if checked_item is None:
                reviewed_items.append(item)
                decisions.append(
                    {
                        "item_id": item.item_id,
                        "grid_cells": item.grid_cells,
                        "status": copy_status["status"],
                        "copy": copy_status,
                        "decision": item.decision,
                        "reason": item.decision_reason,
                    }
                )
                continue

            parsed_tooltip = parse_tooltip(checked_item.raw_text)
            updated_item = item.model_copy(
                update={
                    "identification": parsed_tooltip.to_identification_result(),
                    "estimated_price": checked_item.price,
                    "decision": checked_item.decision,
                    "decision_reason": checked_item.decision_reason,
                }
            )
            if updated_item.decision == "select":
                duplicate_tooltip = checked_item.cache_key in self._selected_tooltip_keys
                if duplicate_tooltip:
                    LOGGER.info("skipped duplicate selected tooltip for %s: %s", item.item_id, checked_item.cache_key)
                    updated_item = updated_item.model_copy(
                        update={
                            "decision": "skip",
                            "decision_reason": f"Duplicate selected tooltip already clicked: {checked_item.item_name}",
                        }
                    )
                else:
                    self._selected_tooltip_keys.add(checked_item.cache_key)
                    self._execute_review_selected_item(plan, updated_item, debug_dir)
            reviewed_items.append(updated_item)
            decisions.append(
                {
                    "item_id": item.item_id,
                    "grid_cells": item.grid_cells,
                    "name": checked_item.item_name,
                    "class": checked_item.item_class,
                    "price": checked_item.price.model_dump(mode="python"),
                    "copy": copy_status,
                    "decision": checked_item.decision,
                    "reason": checked_item.decision_reason,
                }
            )

        tooltip_path = debug_dir / "tooltip-review.json"
        try:
            write_json(tooltip_path, decisions)
        except Exception:
            LOGGER.exception("failed to write tooltip review decisions")
        return self._plan_with_items_and_rebuilt_actions(plan, reviewed_items)

    def _review_item_tooltip(self, plan: RitualPlan, item: DetectedItem) -> tuple[CheckedItemDecision | None, dict]:
        self._raise_if_cancelled()
        if not active_window_is_allowed(self.config.application):
            LOGGER.info("tooltip review stopped because active window is not PoE 2: %s", active_window_description())
            return None, {"status": "inactive_window", "attempts": []}

        hover_ms = int(self.config.application.get("delays", {}).get("before_tooltip_copy_ms", 180))
        copy_ms = int(self.config.application.get("delays", {}).get("after_tooltip_copy_ms", 160))
        retry_ms = int(self.config.application.get("delays", {}).get("tooltip_copy_retry_ms", 250))
        attempts = int(self.config.application.get("delays", {}).get("tooltip_copy_attempts", 2))
        sentinel = f"ritual-helper-copy-{time.time_ns()}"
        copy_attempts = []
        try:
            max_probe_points = int(self.config.application.get("delays", {}).get("tooltip_probe_points", 5))
            for point_index, (x, y) in enumerate(self._tooltip_probe_points(plan, item)[:max_probe_points], start=1):
                self._raise_if_cancelled()
                screen_x = plan.source.screen_left + x
                screen_y = plan.source.screen_top + y
                write_clipboard_text(sentinel)
                ctypes.windll.user32.SetCursorPos(screen_x, screen_y)
                self._sleep_or_cancel(hover_ms)
                for attempt in range(1, attempts + 1):
                    self._raise_if_cancelled()
                    self._send_ctrl_c()
                    self._sleep_or_cancel(copy_ms)
                    tooltip_text = read_clipboard_text()
                    copied = bool(tooltip_text and tooltip_text != sentinel)
                    copy_attempts.append(
                        {
                            "point": point_index,
                            "attempt": attempt,
                            "x": x,
                            "y": y,
                            "copied": copied,
                            "clipboard_length": len(tooltip_text or ""),
                        }
                    )
                    if copied:
                        checked_item = self.remember_checked_item(tooltip_text)
                        return checked_item, {"status": "copied", "attempts": copy_attempts, "x": x, "y": y}
                    LOGGER.info(
                        "tooltip copy attempt %s/%s at point %s failed for %s",
                        attempt,
                        attempts,
                        point_index,
                        item.item_id,
                    )
                    if attempt < attempts:
                        self._sleep_or_cancel(retry_ms)
            return None, {"status": "copy_failed", "attempts": copy_attempts}
        except Exception:
            LOGGER.exception("failed to review tooltip for %s", item.item_id)
            return None, {"status": "copy_error", "attempts": copy_attempts}

    def _raise_if_cancelled(self) -> None:
        if self.state.cancel_requested.is_set():
            raise WorkflowCancelled()

    def _sleep_or_cancel(self, milliseconds: int) -> None:
        deadline = time.monotonic() + milliseconds / 1000
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            time.sleep(min(0.03, max(0, deadline - time.monotonic())))
        self._raise_if_cancelled()

    @staticmethod
    def _tooltip_probe_points(plan: RitualPlan, item: DetectedItem) -> list[tuple[int, int]]:
        width = plan.source.client_width
        height = plan.source.client_height
        left, top, right, bottom = item.region.to_pixels(width, height)
        center_x, center_y = item.click_point.to_pixels(width, height)
        inset_x = max(3, round((right - left) * 0.25))
        inset_y = max(3, round((bottom - top) * 0.25))
        candidates = [
            (center_x, center_y),
            (left + inset_x, top + inset_y),
            (right - inset_x, top + inset_y),
            (left + inset_x, bottom - inset_y),
            (right - inset_x, bottom - inset_y),
            ((left + right) // 2, top + inset_y),
            ((left + right) // 2, bottom - inset_y),
        ]
        unique = []
        seen = set()
        for point in candidates:
            clamped = (min(max(point[0], left), right - 1), min(max(point[1], top), bottom - 1))
            if clamped not in seen:
                unique.append(clamped)
                seen.add(clamped)
        return unique

    def _plan_with_items_and_rebuilt_actions(self, plan: RitualPlan, items: list[DetectedItem]) -> RitualPlan:
        item_ids = {item.item_id for item in items}
        ui_actions = [action for action in plan.actions if action.target not in item_ids]
        delay_ms = int(self.config.application["delays"]["after_item_click_ms"])
        item_actions = [
            PlanAction(
                action_id=f"action-{index:03d}",
                type="click",
                target=item.item_id,
                position=item.click_point,
                delay_after_ms=delay_ms,
            )
            for index, item in enumerate(items, start=1)
            if item.decision == "select"
        ]
        return plan.model_copy(
            update={
                "items": items,
                "actions": [*item_actions, *ui_actions],
                "summary": PlanSummary(
                    items_detected=len(items),
                    items_identified=sum(1 for item in items if item.identification.status != "unknown"),
                    items_selected=sum(1 for item in items if item.decision == "select"),
                    items_for_review=sum(1 for item in items if item.decision == "review"),
                ),
            }
        )

    @staticmethod
    def _send_ctrl_c() -> None:
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    def checked_item_for_key(self, cache_key: str) -> CheckedItemDecision | None:
        for checked_item in self.checked_items:
            if checked_item.cache_key == cache_key:
                return checked_item
        return None

    @staticmethod
    def _tooltip_cache_key(tooltip: ParsedTooltip) -> str:
        parts = [
            slugify(tooltip.item_class or "unknown-class"),
            slugify(tooltip.rarity or "unknown-rarity"),
            slugify(tooltip.name),
            slugify(tooltip.base_type or "no-base-type"),
        ]
        return "/".join(parts)

    @staticmethod
    def _next_run_id(debug_root: Path) -> str:
        ensure_dir(debug_root)
        existing = [path.name for path in debug_root.glob("run-*") if path.is_dir()]
        numbers = []
        for name in existing:
            try:
                numbers.append(int(name.split("-", 1)[1]))
            except (IndexError, ValueError):
                continue
        return f"run-{(max(numbers, default=0) + 1):03d}"

    def _debug_enabled(self) -> bool:
        return bool(self.config.application.get("debug_enabled", True))

    @contextmanager
    def _debug_dir_context(self, output_dir: Path) -> Iterator[Path]:
        if self._debug_enabled():
            run_id = self._next_run_id(output_dir / "debug")
            yield ensure_dir(output_dir / "debug" / run_id)
            return

        with TemporaryDirectory(prefix="ritual-helper-") as temp_dir:
            yield ensure_dir(Path(temp_dir))


def build_controller(config: AppConfig) -> ApplicationController:
    from ritual_helper.analyzer.grid_ritual_analyzer import GridRitualAnalyzer
    from ritual_helper.analyzer.price_service import build_price_provider
    from ritual_helper.analyzer.ritual_analyzer import StubRitualAnalyzer
    from ritual_helper.capture.fixture_capture import FixtureCapture
    from ritual_helper.capture.window_capture import WindowCapture
    from ritual_helper.executor.recording_backend import RecordingBackend
    from ritual_helper.executor.render_backend import RenderBackend
    from ritual_helper.executor.live_mouse_backend import LiveMouseBackend

    board = RatioRect(**config.vision["board"])
    delay_ms = int(config.application["delays"]["after_item_click_ms"])
    capture_source = FixtureCapture(config.fixture_screenshot) if config.mode == "test" else WindowCapture()
    if config.application.get("analyzer", "stub") == "grid":
        grid_config = dict(config.vision["grid"])
        grid_config["after_item_click_ms"] = int(config.application["delays"]["after_item_click_ms"])
        analyzer = GridRitualAnalyzer(board=board, grid_config=grid_config)
    else:
        analyzer = StubRitualAnalyzer(board=board, item_delay_ms=delay_ms)

    backend_names = config.application.get("executor_backends", ["recording", "render"])
    backends = []
    if "recording" in backend_names:
        backends.append(RecordingBackend())
    if "render" in backend_names:
        backends.append(RenderBackend())
    controller = ApplicationController(
        config=config,
        capture_source=capture_source,
        analyzer=analyzer,
        executor=RitualExecutor(backends),
        price_provider=build_price_provider(config.application, config.selection_policy),
        selection_policy=TooltipSelectionPolicy(
            minimum_value=float(config.selection_policy.get("minimum_defer_value", config.selection_policy["minimum_value"])),
            price_currency=str(config.selection_policy["price_currency"]),
        ),
    )
    if config.mode == "live" and config.application.get("live_execution_enabled", False) and "live_mouse" in backend_names:
        backends.append(LiveMouseBackend(config.application, controller.state.cancel_requested.is_set))
    return controller


def configured_ui_actions(config: AppConfig) -> dict[str, RatioPoint]:
    return {name: RatioPoint(**coords) for name, coords in config.application["ui_controls"].items()}
