from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageStat

from ritual_helper.models import (
    CapturedFrame,
    DetectedItem,
    IdentificationResult,
    PlanAction,
    PlanSource,
    PlanSummary,
    PriceEstimate,
    RatioRect,
    RitualPlan,
)
from ritual_helper.shared.files import ensure_dir, write_json


@dataclass(frozen=True)
class CellAnalysis:
    row: int
    column: int
    rect: RatioRect
    mean: float
    stddev: float
    edge_mean: float
    gold_ratio: float
    content_ratio: float
    brown_line_ratio: float
    occupied: bool
    deferred: bool
    filtered_out: bool


@dataclass(frozen=True)
class ItemGroup:
    cells: list[CellAnalysis]
    rect: RatioRect
    deferred: bool
    inferred_cells: list[str]


@dataclass(frozen=True)
class MaskComponent:
    cells: list[CellAnalysis]
    pixel_count: int
    bbox: tuple[int, int, int, int]
    area: float = 0.0


class GridRitualAnalyzer:
    def __init__(self, board: RatioRect, grid_config: dict[str, float | int]) -> None:
        self.board = board
        self.columns = int(grid_config.get("columns", 10))
        self.rows = int(grid_config.get("rows", 10))
        self.cell_padding_px = int(grid_config.get("cell_padding_px", 4))
        self.occupied_mean_threshold = float(grid_config.get("occupied_mean_threshold", 14.0))
        self.occupied_stddev_threshold = float(grid_config.get("occupied_stddev_threshold", 18.0))
        self.occupied_edge_threshold = float(grid_config.get("occupied_edge_threshold", 14.0))
        self.deferred_gold_ratio_threshold = float(grid_config.get("deferred_gold_ratio_threshold", 0.035))
        self.filtered_mean_max = float(grid_config.get("filtered_mean_max", 12.0))
        self.filtered_stddev_max = float(grid_config.get("filtered_stddev_max", 12.0))
        self.filtered_edge_max = float(grid_config.get("filtered_edge_max", 12.0))
        self.item_region_inset_ratio = float(grid_config.get("item_region_inset_ratio", 0.1))
        self.max_item_cells = int(grid_config.get("max_item_cells", 8))
        self.item_click_delay_ms = int(grid_config.get("after_item_click_ms", 400))
        self.content_ratio_threshold = float(grid_config.get("content_ratio_threshold", 0.035))
        self.brown_line_ratio_threshold = float(grid_config.get("brown_line_ratio_threshold", 0.02))
        self.use_grayscale_mask = bool(grid_config.get("use_grayscale_mask", True))
        self.canny_threshold1 = int(grid_config.get("canny_threshold1", 70))
        self.canny_threshold2 = int(grid_config.get("canny_threshold2", 150))
        self.canny_dilate_kernel = int(grid_config.get("canny_dilate_kernel", 3))
        self.canny_dilate_iterations = int(grid_config.get("canny_dilate_iterations", 1))
        self.mask_min_area = float(grid_config.get("mask_min_area", 120.0))
        self.mask_cell_ratio_threshold = float(grid_config.get("mask_cell_ratio_threshold", 0.012))
        self.allowed_item_shapes = {
            (1, 1),
            (1, 2),
            (1, 3),
            (1, 4),
            (1, 5),
            (1, 6),
            (1, 7),
            (1, 8),
            (2, 1),
            (2, 2),
            (2, 3),
            (2, 4),
            (3, 1),
            (3, 2),
        }

    def analyze(self, frame: CapturedFrame, debug_dir: Path) -> RitualPlan:
        ensure_dir(debug_dir)
        image = Image.open(frame.image_path).convert("RGB")
        board_crop = image.crop(self.board.to_pixels(frame.client_width, frame.client_height))
        board_crop.save(debug_dir / "board.png")

        cells = self._analyze_cells(image, frame.client_width, frame.client_height)
        foreground_mask = self._build_grayscale_foreground_mask(image, frame.client_width, frame.client_height)
        cells = self._apply_foreground_occupancy(cells, foreground_mask, frame.client_width, frame.client_height)
        mask_components = self._detect_mask_components(foreground_mask, frame.client_width, frame.client_height, cells)
        groups = self._detect_foreground_rectangles(foreground_mask, cells, frame.client_width, frame.client_height)
        if not groups:
            groups = self._group_from_mask_evidence(
                cells,
                mask_components,
                {(cell.row, cell.column): cell for cell in cells},
                frame.client_width,
                frame.client_height,
            ) or self._group_cells(cells)
        self._write_debug(cells, groups, image, debug_dir, foreground_mask, mask_components)
        items = [self._group_to_item(index, group) for index, group in enumerate(groups, start=1)]
        actions = [
            PlanAction(
                action_id=f"action-{index:03d}",
                type="click",
                target=item.item_id,
                position=item.click_point,
                delay_after_ms=self.item_click_delay_ms,
            )
            for index, item in enumerate(items, start=1)
            if item.decision == "select"
        ]

        return RitualPlan(
            schema_version="1.0",
            plan_id=f"ritual-{datetime.now(ZoneInfo('Asia/Saigon')).strftime('%Y%m%d-%H%M%S')}",
            created_at=datetime.now(ZoneInfo("Asia/Saigon")),
            source=PlanSource(
                image_path=str(frame.image_path),
                client_width=frame.client_width,
                client_height=frame.client_height,
                mode=frame.mode,
                screen_left=frame.screen_left,
                screen_top=frame.screen_top,
            ),
            board=self.board,
            items=items,
            actions=actions,
            summary=PlanSummary(
                items_detected=len(items),
                items_identified=0,
                items_selected=sum(1 for item in items if item.decision == "select"),
                items_for_review=sum(1 for item in items if item.decision == "review"),
            ),
        )

    def _analyze_cells(self, image: Image.Image, width: int, height: int) -> list[CellAnalysis]:
        left, top, right, bottom = self.board.to_pixels(width, height)
        cell_width = (right - left) / self.columns
        cell_height = (bottom - top) / self.rows
        cells = []
        for row in range(self.rows):
            for column in range(self.columns):
                x1 = round(left + column * cell_width)
                y1 = round(top + row * cell_height)
                x2 = round(left + (column + 1) * cell_width)
                y2 = round(top + (row + 1) * cell_height)
                padded = (
                    min(x2 - 1, x1 + self.cell_padding_px),
                    min(y2 - 1, y1 + self.cell_padding_px),
                    max(x1 + 1, x2 - self.cell_padding_px),
                    max(y1 + 1, y2 - self.cell_padding_px),
                )
                crop = image.crop(padded)
                gray = crop.convert("L")
                stat = ImageStat.Stat(gray)
                edge_mean = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
                gold_ratio = self._gold_ratio(crop)
                content_ratio, brown_line_ratio = self._cell_content_ratios(crop)
                raw_occupied = (
                    stat.mean[0] >= self.occupied_mean_threshold
                    or stat.stddev[0] >= self.occupied_stddev_threshold
                    or edge_mean >= self.occupied_edge_threshold
                    or brown_line_ratio >= self.brown_line_ratio_threshold
                )
                deferred = raw_occupied and gold_ratio >= self.deferred_gold_ratio_threshold
                filtered_out = (
                    raw_occupied
                    and not deferred
                    and content_ratio < self.content_ratio_threshold
                    and brown_line_ratio < self.brown_line_ratio_threshold
                )
                occupied = raw_occupied and not filtered_out
                cells.append(
                    CellAnalysis(
                        row=row,
                        column=column,
                        rect=RatioRect(left=x1 / width, top=y1 / height, right=x2 / width, bottom=y2 / height),
                        mean=stat.mean[0],
                        stddev=stat.stddev[0],
                        edge_mean=edge_mean,
                        gold_ratio=gold_ratio,
                        content_ratio=content_ratio,
                        brown_line_ratio=brown_line_ratio,
                        occupied=occupied,
                        deferred=deferred,
                        filtered_out=filtered_out,
                    )
                )
        return cells

    def _grid_cells(self, image: Image.Image, width: int, height: int) -> list[CellAnalysis]:
        cells = self._analyze_cells(image, width, height)
        return [replace(cell, occupied=False, filtered_out=False) for cell in cells]

    def _detect_foreground_rectangles(
        self,
        foreground_mask: Image.Image,
        cells: list[CellAnalysis],
        width: int,
        height: int,
    ) -> list[ItemGroup]:
        left, top, _right, _bottom = self.board.to_pixels(width, height)
        board_width, board_height = foreground_mask.size
        cell_width = board_width / self.columns
        cell_height = board_height / self.rows
        by_position = {(cell.row, cell.column): cell for cell in cells}
        contours = self._merge_line_like_contours(
            self._foreground_contours(foreground_mask),
            cell_width,
            cell_height,
            by_position,
        )
        candidates: list[dict[str, object]] = []
        for contour in contours:
            x1, y1, x2, y2, pixels = contour
            if pixels < self.mask_min_area:
                continue
            min_column = max(0, int(x1 / cell_width))
            max_column = min(self.columns - 1, int((x2 - 1) / cell_width))
            min_row = max(0, int(y1 / cell_height))
            max_row = min(self.rows - 1, int((y2 - 1) / cell_height))
            positions = frozenset(
                (row, column)
                for row in range(min_row, max_row + 1)
                for column in range(min_column, max_column + 1)
            )
            if not positions or not self._is_legal_item_shape(positions):
                continue
            contour_cells = [by_position[position] for position in sorted(positions)]
            deferred_cells = [
                cell
                for cell in contour_cells
                if cell.gold_ratio >= self.deferred_gold_ratio_threshold
            ]
            deferred = bool(deferred_cells) and (
                len(contour_cells) == 1
                or len(deferred_cells) / len(contour_cells) >= 0.5
            )
            rect = self._pixel_rect_to_ratio_rect(
                (
                    max(left, x1 + left - 2),
                    max(top, y1 + top - 2),
                    min(left + board_width, x2 + left + 2),
                    min(top + board_height, y2 + top + 2),
                ),
                width,
                height,
            )
            candidates.append(
                {
                    "local_bbox": (x1, y1, x2, y2),
                    "cells": contour_cells,
                    "pixels": pixels,
                    "deferred": deferred,
                    "rect": rect,
                }
            )
        candidates = self._suppress_nested_foreground_candidates(candidates)

        groups: list[ItemGroup] = []
        claimed_footprints: set[tuple[tuple[int, int], ...]] = set()
        for candidate in sorted(
            candidates,
            key=lambda item: (
                min(cell.row for cell in item["cells"]),  # type: ignore[index]
                min(cell.column for cell in item["cells"]),  # type: ignore[index]
                -int(item["pixels"]),
            ),
        ):
            candidate_cells = list(candidate["cells"])  # type: ignore[arg-type]
            if not candidate_cells:
                continue
            footprint = tuple(sorted((cell.row, cell.column) for cell in candidate_cells))
            if footprint in claimed_footprints:
                continue
            claimed_footprints.add(footprint)
            groups.append(
                ItemGroup(
                    cells=candidate_cells,
                    rect=candidate["rect"],  # type: ignore[arg-type]
                    deferred=bool(candidate["deferred"]),
                    inferred_cells=[],
                )
            )
        return sorted(groups, key=lambda group: (min(cell.row for cell in group.cells), min(cell.column for cell in group.cells)))

    @staticmethod
    def _suppress_nested_foreground_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
        kept: list[dict[str, object]] = []
        for candidate in sorted(candidates, key=lambda item: int(item["pixels"]), reverse=True):
            bbox = candidate["local_bbox"]  # type: ignore[assignment]
            if any(GridRitualAnalyzer._rect_overlap_ratio(bbox, kept_item["local_bbox"]) >= 0.55 for kept_item in kept):  # type: ignore[arg-type]
                continue
            kept.append(candidate)
        return kept

    @staticmethod
    def _rect_overlap_ratio(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        overlap = max(0, right - left) * max(0, bottom - top)
        first_area = max(1, (first[2] - first[0]) * (first[3] - first[1]))
        return overlap / first_area

    @staticmethod
    def _pixel_rect_to_ratio_rect(rect: tuple[int, int, int, int], width: int, height: int) -> RatioRect:
        left, top, right, bottom = rect
        return RatioRect(left=left / width, top=top / height, right=right / width, bottom=bottom / height)

    @staticmethod
    def _foreground_contours(foreground_mask: Image.Image) -> list[tuple[int, int, int, int, int]]:
        mask_pixels = foreground_mask.load()
        board_width, board_height = foreground_mask.size
        visited: set[tuple[int, int]] = set()
        contours: list[tuple[int, int, int, int, int]] = []
        for y in range(board_height):
            for x in range(board_width):
                if mask_pixels[x, y] == 0 or (x, y) in visited:
                    continue
                stack = [(x, y)]
                visited.add((x, y))
                xs: list[int] = []
                ys: list[int] = []
                while stack:
                    current_x, current_y = stack.pop()
                    xs.append(current_x)
                    ys.append(current_y)
                    for neighbor_x, neighbor_y in (
                        (current_x - 1, current_y),
                        (current_x + 1, current_y),
                        (current_x, current_y - 1),
                        (current_x, current_y + 1),
                    ):
                        if (
                            0 <= neighbor_x < board_width
                            and 0 <= neighbor_y < board_height
                            and (neighbor_x, neighbor_y) not in visited
                            and mask_pixels[neighbor_x, neighbor_y] > 0
                        ):
                            visited.add((neighbor_x, neighbor_y))
                            stack.append((neighbor_x, neighbor_y))
                contours.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(xs)))
        return contours

    def _merge_line_like_contours(
        self,
        contours: list[tuple[int, int, int, int, int]],
        cell_width: float,
        cell_height: float,
        by_position: dict[tuple[int, int], CellAnalysis],
    ) -> list[tuple[int, int, int, int, int]]:
        usable = [contour for contour in contours if contour[4] >= 35]
        used: set[int] = set()
        merged: list[tuple[int, int, int, int, int]] = []

        for index, contour in sorted(enumerate(usable), key=lambda item: (item[1][1], item[1][0])):
            if index in used:
                continue
            if not self._is_line_like_contour(contour) or self._contour_is_deferred(contour, cell_width, cell_height, by_position):
                continue
            cluster = contour
            used.add(index)
            changed = True
            while changed:
                changed = False
                for other_index, other in sorted(enumerate(usable), key=lambda item: item[1][4], reverse=True):
                    if other_index in used or self._contour_is_deferred(other, cell_width, cell_height, by_position):
                        continue
                    if not self._contours_look_related(cluster, other, cell_width, cell_height):
                        continue
                    cluster = self._union_contours(cluster, other)
                    used.add(other_index)
                    changed = True
                    break
            merged.append(cluster)

        for index, contour in enumerate(usable):
            if index not in used:
                merged.append(contour)
        return merged

    def _contour_is_deferred(
        self,
        contour: tuple[int, int, int, int, int],
        cell_width: float,
        cell_height: float,
        by_position: dict[tuple[int, int], CellAnalysis],
    ) -> bool:
        x1, y1, x2, y2, _pixels = contour
        min_column = max(0, int(x1 / cell_width))
        max_column = min(self.columns - 1, int((x2 - 1) / cell_width))
        min_row = max(0, int(y1 / cell_height))
        max_row = min(self.rows - 1, int((y2 - 1) / cell_height))
        cells = [
            by_position[(row, column)]
            for row in range(min_row, max_row + 1)
            for column in range(min_column, max_column + 1)
            if (row, column) in by_position
        ]
        return bool(cells) and any(cell.gold_ratio >= self.deferred_gold_ratio_threshold for cell in cells)

    @staticmethod
    def _is_line_like_contour(contour: tuple[int, int, int, int, int]) -> bool:
        x1, y1, x2, y2, _pixels = contour
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        return (height >= 22 and height / width >= 1.8) or (width >= 22 and width / height >= 2.4)

    def _contours_look_related(
        self,
        current: tuple[int, int, int, int, int],
        candidate: tuple[int, int, int, int, int],
        cell_width: float,
        cell_height: float,
    ) -> bool:
        combined = self._union_contours(current, candidate)
        x1, y1, x2, y2, _pixels = combined
        footprint_width = int((x2 - 1) / cell_width) - int(x1 / cell_width) + 1
        footprint_height = int((y2 - 1) / cell_height) - int(y1 / cell_height) + 1
        if footprint_width * footprint_height > self.max_item_cells or footprint_width > 2:
            return False

        current_x1, current_y1, current_x2, current_y2, _current_pixels = current
        candidate_x1, candidate_y1, candidate_x2, candidate_y2, _candidate_pixels = candidate
        horizontal_overlap = min(current_x2, candidate_x2) - max(current_x1, candidate_x1)
        center_distance = abs(((current_x1 + current_x2) / 2) - ((candidate_x1 + candidate_x2) / 2))
        vertical_gap = max(candidate_y1 - current_y2, current_y1 - candidate_y2, 0)
        candidate_width = max(1, candidate_x2 - candidate_x1)
        candidate_height = max(1, candidate_y2 - candidate_y1)
        candidate_box_like = candidate_width >= 28 and candidate_height >= 28 and 0.65 <= candidate_width / candidate_height <= 1.55
        current_box_like = (
            current_x2 - current_x1 >= 28
            and current_y2 - current_y1 >= 28
            and 0.65 <= (current_x2 - current_x1) / max(1, current_y2 - current_y1) <= 1.55
        )
        if candidate_box_like and current_box_like:
            return False
        return (horizontal_overlap >= 2 or center_distance <= 24) and vertical_gap <= 85

    @staticmethod
    def _union_contours(
        first: tuple[int, int, int, int, int],
        second: tuple[int, int, int, int, int],
    ) -> tuple[int, int, int, int, int]:
        return (
            min(first[0], second[0]),
            min(first[1], second[1]),
            max(first[2], second[2]),
            max(first[3], second[3]),
            first[4] + second[4],
        )

    def _merge_vertical_foreground_candidates(
        self,
        candidates: list[dict[str, object]],
        by_position: dict[tuple[int, int], CellAnalysis],
    ) -> list[dict[str, object]]:
        pending = sorted(candidates, key=lambda item: (item["local_bbox"][0], item["local_bbox"][1]))  # type: ignore[index]
        merged: list[dict[str, object]] = []
        while pending:
            current = pending.pop(0)
            changed = True
            while changed:
                changed = False
                if current["deferred"]:
                    break
                current_bbox = current["local_bbox"]  # type: ignore[assignment]
                current_cells = current["cells"]  # type: ignore[assignment]
                current_columns = {cell.column for cell in current_cells}
                for index, candidate in enumerate(pending):
                    if candidate["deferred"]:
                        continue
                    candidate_bbox = candidate["local_bbox"]  # type: ignore[assignment]
                    candidate_cells = candidate["cells"]  # type: ignore[assignment]
                    combined_bbox = (
                        min(current_bbox[0], candidate_bbox[0]),
                        min(current_bbox[1], candidate_bbox[1]),
                        max(current_bbox[2], candidate_bbox[2]),
                        max(current_bbox[3], candidate_bbox[3]),
                    )
                    combined_positions = {
                        (cell.row, cell.column)
                        for cell in [*current_cells, *candidate_cells]
                    }
                    rows = [row for row, _ in combined_positions]
                    columns = [column for _, column in combined_positions]
                    width = max(columns) - min(columns) + 1
                    height = max(rows) - min(rows) + 1
                    candidate_columns = {cell.column for cell in candidate_cells}
                    same_column_track = bool(current_columns & candidate_columns)
                    horizontal_overlap = min(current_bbox[2], candidate_bbox[2]) - max(current_bbox[0], candidate_bbox[0])
                    vertical_gap = max(candidate_bbox[1] - current_bbox[3], current_bbox[1] - candidate_bbox[3], 0)
                    if (
                        not same_column_track
                        or horizontal_overlap < 3
                        or vertical_gap > 70
                        or width > 2
                        or width * height > self.max_item_cells
                    ):
                        continue
                    positions = frozenset(
                        (row, column)
                        for row in range(min(rows), max(rows) + 1)
                        for column in range(min(columns), max(columns) + 1)
                    )
                    current = {
                        "bbox": current["bbox"],
                        "local_bbox": combined_bbox,
                        "cells": [by_position[position] for position in sorted(positions)],
                        "pixels": int(current["pixels"]) + int(candidate["pixels"]),
                        "deferred": False,
                    }
                    pending.pop(index)
                    changed = True
                    break
            merged.append(current)
        return merged

    def _build_foreground_mask(
        self,
        image: Image.Image,
        width: int,
        height: int,
    ) -> Image.Image:
        left, top, right, bottom = self.board.to_pixels(width, height)
        board_crop = image.crop((left, top, right, bottom)).convert("RGB")
        board_width, board_height = board_crop.size
        cell_width = board_width / self.columns
        cell_height = board_height / self.rows
        mask = Image.new("L", (board_width, board_height), 0)
        mask_pixels = mask.load()
        crop_pixels = board_crop.load()

        for y in range(board_height):
            for x in range(board_width):
                red, green, blue = crop_pixels[x, y]
                maximum = max(red, green, blue)
                minimum = min(red, green, blue)
                saturation = maximum - minimum
                gold = red >= 105 and green >= 70 and blue <= 85 and red >= green >= blue
                foreground = (not gold) and ((maximum > 55 and saturation > 18) or (maximum > 85 and saturation > 8))
                brown_line = red >= 28 and green >= 18 and blue <= 55 and red >= green >= blue and saturation >= 8
                if foreground or brown_line:
                    mask_pixels[x, y] = 255

        for column in range(1, self.columns):
            grid_x = round(column * cell_width)
            for x in range(max(0, grid_x - 4), min(board_width, grid_x + 5)):
                for y in range(board_height):
                    mask_pixels[x, y] = 0
        for row in range(1, self.rows):
            grid_y = round(row * cell_height)
            for y in range(max(0, grid_y - 4), min(board_height, grid_y + 5)):
                for x in range(board_width):
                    mask_pixels[x, y] = 0
        for x in range(board_width):
            for y in (*range(0, min(8, board_height)), *range(max(0, board_height - 8), board_height)):
                mask_pixels[x, y] = 0
        for y in range(board_height):
            for x in (*range(0, min(8, board_width)), *range(max(0, board_width - 8), board_width)):
                mask_pixels[x, y] = 0

        return mask

    def _build_grayscale_foreground_mask(
        self,
        image: Image.Image,
        width: int,
        height: int,
    ) -> Image.Image:
        if not self.use_grayscale_mask:
            return self._build_foreground_mask(image, width, height)
        try:
            import cv2
            import numpy as np
        except Exception:
            return self._build_foreground_mask(image, width, height)

        left, top, right, bottom = self.board.to_pixels(width, height)
        board_crop = image.crop((left, top, right, bottom)).convert("RGB")
        board_width, board_height = board_crop.size
        cell_width = board_width / self.columns
        cell_height = board_height / self.rows

        rgb = np.array(board_crop)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 1)
        edges = cv2.Canny(blur, self.canny_threshold1, self.canny_threshold2)
        kernel_size = max(1, self.canny_dilate_kernel)
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        mask = cv2.dilate(edges, kernel, iterations=max(0, self.canny_dilate_iterations))

        # Suppress grid/border lines. The item art inside each known cell is the signal.
        for column in range(1, self.columns):
            grid_x = round(column * cell_width)
            mask[:, max(0, grid_x - 4) : min(board_width, grid_x + 5)] = 0
        for row in range(1, self.rows):
            grid_y = round(row * cell_height)
            mask[max(0, grid_y - 4) : min(board_height, grid_y + 5), :] = 0
        border = 8
        mask[:border, :] = 0
        mask[max(0, board_height - border) :, :] = 0
        mask[:, :border] = 0
        mask[:, max(0, board_width - border) :] = 0

        return Image.fromarray(mask).convert("L")

    def _apply_foreground_occupancy(
        self,
        cells: list[CellAnalysis],
        foreground_mask: Image.Image,
        width: int,
        height: int,
    ) -> list[CellAnalysis]:
        left, top, right, bottom = self.board.to_pixels(width, height)
        board_width, board_height = foreground_mask.size
        cell_width = board_width / self.columns
        cell_height = board_height / self.rows
        mask_pixels = foreground_mask.load()
        updated_cells: list[CellAnalysis] = []
        for cell in cells:
            local_x1 = round(cell.column * cell_width)
            local_y1 = round(cell.row * cell_height)
            local_x2 = round((cell.column + 1) * cell_width)
            local_y2 = round((cell.row + 1) * cell_height)
            inset = max(5, self.cell_padding_px)
            sample_x1 = min(local_x2 - 1, local_x1 + inset)
            sample_y1 = min(local_y2 - 1, local_y1 + inset)
            sample_x2 = max(sample_x1 + 1, local_x2 - inset)
            sample_y2 = max(sample_y1 + 1, local_y2 - inset)
            foreground_pixels = 0
            total_pixels = 0
            for y in range(sample_y1, sample_y2):
                for x in range(sample_x1, sample_x2):
                    total_pixels += 1
                    if mask_pixels[x, y] > 0:
                        foreground_pixels += 1
            foreground_ratio = foreground_pixels / max(total_pixels, 1)
            occupied = foreground_ratio >= self.mask_cell_ratio_threshold or cell.deferred
            filtered_out = not occupied and cell.mean >= self.occupied_mean_threshold
            updated_cells.append(
                replace(
                    cell,
                    content_ratio=foreground_ratio,
                    occupied=occupied,
                    deferred=occupied and cell.gold_ratio >= self.deferred_gold_ratio_threshold,
                    filtered_out=filtered_out,
                )
            )
        return updated_cells

    def _detect_mask_components(
        self,
        foreground_mask: Image.Image,
        width: int,
        height: int,
        cells: list[CellAnalysis],
    ) -> list[MaskComponent]:
        left, top, _right, _bottom = self.board.to_pixels(width, height)
        component_mask = foreground_mask
        board_width, board_height = component_mask.size
        cell_width = board_width / self.columns
        cell_height = board_height / self.rows
        mask_pixels = component_mask.load()
        by_position = {(cell.row, cell.column): cell for cell in cells}
        visited: set[tuple[int, int]] = set()
        components: list[MaskComponent] = []
        for y in range(board_height):
            for x in range(board_width):
                if mask_pixels[x, y] == 0 or (x, y) in visited:
                    continue
                stack = [(x, y)]
                visited.add((x, y))
                xs: list[int] = []
                ys: list[int] = []
                component_positions: set[tuple[int, int]] = set()
                while stack:
                    current_x, current_y = stack.pop()
                    xs.append(current_x)
                    ys.append(current_y)
                    component_column = min(self.columns - 1, max(0, int(current_x / cell_width)))
                    component_row = min(self.rows - 1, max(0, int(current_y / cell_height)))
                    component_positions.add((component_row, component_column))
                    for neighbor_x, neighbor_y in (
                        (current_x - 1, current_y),
                        (current_x + 1, current_y),
                        (current_x, current_y - 1),
                        (current_x, current_y + 1),
                    ):
                        if (
                            0 <= neighbor_x < board_width
                            and 0 <= neighbor_y < board_height
                            and (neighbor_x, neighbor_y) not in visited
                            and mask_pixels[neighbor_x, neighbor_y] > 0
                        ):
                            visited.add((neighbor_x, neighbor_y))
                            stack.append((neighbor_x, neighbor_y))

                pixel_count = len(xs)
                if pixel_count < self.mask_min_area:
                    continue
                x1, y1, x2, y2 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
                component_cells = []
                min_column = max(0, int(x1 / cell_width))
                max_column = min(self.columns - 1, int((x2 - 1) / cell_width))
                min_row = max(0, int(y1 / cell_height))
                max_row = min(self.rows - 1, int((y2 - 1) / cell_height))
                bbox_positions = {
                    (row, column)
                    for row in range(min_row, max_row + 1)
                    for column in range(min_column, max_column + 1)
                }
                for row, column in sorted(component_positions | bbox_positions):
                    cell = by_position.get((row, column))
                    if cell is not None:
                        component_cells.append(cell)
                if component_cells:
                    component_by_position = {(cell.row, cell.column): cell for cell in component_cells}
                    components.append(
                        MaskComponent(
                            cells=[component_by_position[key] for key in sorted(component_by_position)],
                            pixel_count=pixel_count,
                            bbox=(x1 + left, y1 + top, x2 + left, y2 + top),
                            area=float(pixel_count),
                        )
                    )

        return components

    def _group_cells(self, cells: list[CellAnalysis]) -> list[ItemGroup]:
        return [
            self._component_to_group([cell])
            for cell in cells
            if cell.occupied and not cell.filtered_out
        ]

    def _group_from_mask_evidence(
        self,
        cells: list[CellAnalysis],
        mask_components: list[MaskComponent],
        by_position: dict[tuple[int, int], CellAnalysis],
        width: int,
        height: int,
    ) -> list[ItemGroup]:
        evidence_components = [component for component in mask_components if component.cells]
        if not evidence_components:
            return []

        claimed_cells: set[tuple[int, int]] = set()
        groups: list[ItemGroup] = []
        for component in sorted(
            evidence_components,
            key=lambda item: (-len(item.cells), -item.pixel_count, min(cell.row for cell in item.cells), min(cell.column for cell in item.cells)),
        ):
            group_cells_by_position: dict[tuple[int, int], CellAnalysis] = {}
            for cell in component.cells:
                group_cells_by_position[(cell.row, cell.column)] = cell
            if not group_cells_by_position:
                continue
            if any(position in claimed_cells for position in group_cells_by_position):
                continue
            for split_component in self._split_mask_evidence_component(list(group_cells_by_position.values()), by_position):
                groups.append(self._component_to_group(split_component))
                claimed_cells.update((cell.row, cell.column) for cell in split_component)

        return self._merge_vertical_mask_groups(groups)

    def _merge_vertical_mask_groups(self, groups: list[ItemGroup]) -> list[ItemGroup]:
        pending = sorted(groups, key=lambda group: (min(cell.column for cell in group.cells), min(cell.row for cell in group.cells)))
        merged: list[ItemGroup] = []
        while pending:
            current = pending.pop(0)
            changed = True
            while changed:
                changed = False
                current_positions = {(cell.row, cell.column) for cell in current.cells}
                current_columns = {cell.column for cell in current.cells}
                current_rows = {cell.row for cell in current.cells}
                if len(current_columns) != 1 or current.deferred:
                    break
                for index, candidate in enumerate(pending):
                    candidate_columns = {cell.column for cell in candidate.cells}
                    candidate_rows = {cell.row for cell in candidate.cells}
                    if (
                        candidate.deferred
                        or candidate_columns != current_columns
                        or len(candidate_columns) != 1
                        or len(current_positions) + len(candidate.cells) > self.max_item_cells
                    ):
                        continue
                    row_gap = max(min(candidate_rows) - max(current_rows), min(current_rows) - max(candidate_rows))
                    if row_gap > 1:
                        continue
                    combined_cells = sorted(current.cells + candidate.cells, key=lambda cell: (cell.row, cell.column))
                    current = self._component_to_group(combined_cells)
                    pending.pop(index)
                    changed = True
                    break
            merged.append(current)
        return sorted(merged, key=lambda group: (min(cell.row for cell in group.cells), min(cell.column for cell in group.cells)))

    def _split_mask_evidence_component(
        self,
        component: list[CellAnalysis],
        all_cells: dict[tuple[int, int], CellAnalysis],
    ) -> list[list[CellAnalysis]]:
        groups: list[list[CellAnalysis]] = []
        for connected_component in self._split_disconnected_cells(component):
            if self._looks_like_deferred_single_cell_stack(connected_component):
                groups.extend([[cell] for cell in sorted(connected_component, key=lambda cell: (cell.row, cell.column))])
            elif len(connected_component) <= self.max_item_cells:
                groups.append(sorted(connected_component, key=lambda cell: (cell.row, cell.column)))
            else:
                groups.extend(self._split_large_mask_component(connected_component))
        return groups

    def _split_large_mask_component(self, cells: list[CellAnalysis]) -> list[list[CellAnalysis]]:
        remaining = {(cell.row, cell.column): cell for cell in cells}
        groups: list[list[CellAnalysis]] = []
        while remaining:
            start = min(remaining)
            chunk_positions: set[tuple[int, int]] = set()
            frontier = [start]
            while frontier and len(chunk_positions) < self.max_item_cells:
                current = frontier.pop(0)
                if current not in remaining or current in chunk_positions:
                    continue
                chunk_positions.add(current)
                for neighbor in self._neighbor_keys(*current):
                    if neighbor in remaining and neighbor not in chunk_positions:
                        frontier.append(neighbor)
            if not chunk_positions:
                chunk_positions.add(start)
            groups.append([remaining[position] for position in sorted(chunk_positions)])
            for position in chunk_positions:
                remaining.pop(position, None)
        return groups

    @staticmethod
    def _components_share_cell(left: MaskComponent, right: MaskComponent) -> bool:
        left_cells = {(cell.row, cell.column) for cell in left.cells}
        right_cells = {(cell.row, cell.column) for cell in right.cells}
        return bool(left_cells & right_cells)

    def _components_bridge_cell_border(self, left: MaskComponent, right: MaskComponent, width: int, height: int) -> bool:
        left_cells = {(cell.row, cell.column) for cell in left.cells}
        right_cells = {(cell.row, cell.column) for cell in right.cells}
        for left_row, left_column in left_cells:
            for right_row, right_column in right_cells:
                if abs(left_row - right_row) + abs(left_column - right_column) != 1:
                    continue
                if left_row == right_row and self._horizontal_border_bridge(left, right, min(left_column, right_column), width, height):
                    return True
                if left_column == right_column and self._vertical_border_bridge(left, right, min(left_row, right_row), width, height):
                    return True
        return False

    def _horizontal_border_bridge(self, left: MaskComponent, right: MaskComponent, left_column: int, width: int, height: int) -> bool:
        board_left, _board_top, board_right, _board_bottom = self.board.to_pixels(width, height)
        cell_width = (board_right - board_left) / self.columns
        border_x = round(board_left + (left_column + 1) * cell_width)
        left_bbox, right_bbox = (left.bbox, right.bbox) if left.bbox[0] <= right.bbox[0] else (right.bbox, left.bbox)
        if abs(left_bbox[2] - border_x) > 10 or abs(right_bbox[0] - border_x) > 10:
            return False
        overlap = min(left_bbox[3], right_bbox[3]) - max(left_bbox[1], right_bbox[1])
        return overlap >= 8

    def _vertical_border_bridge(self, top: MaskComponent, bottom: MaskComponent, top_row: int, width: int, height: int) -> bool:
        _board_left, board_top, _board_right, board_bottom = self.board.to_pixels(width, height)
        cell_height = (board_bottom - board_top) / self.rows
        border_y = round(board_top + (top_row + 1) * cell_height)
        top_bbox, bottom_bbox = (top.bbox, bottom.bbox) if top.bbox[1] <= bottom.bbox[1] else (bottom.bbox, top.bbox)
        if abs(top_bbox[3] - border_y) > 10 or abs(bottom_bbox[1] - border_y) > 10:
            return False
        overlap = min(top_bbox[2], bottom_bbox[2]) - max(top_bbox[0], bottom_bbox[0])
        return overlap >= 8

    def _split_oversized_component(
        self,
        component: list[CellAnalysis],
        all_cells: dict[tuple[int, int], CellAnalysis],
    ) -> list[list[CellAnalysis]]:
        split_components: list[list[CellAnalysis]] = []
        for connected_component in self._split_disconnected_cells(component):
            split_components.extend(self._split_into_legal_shapes(connected_component, all_cells))
        return split_components

    def _split_into_legal_shapes(
        self,
        cells: list[CellAnalysis],
        all_component_cells: dict[tuple[int, int], CellAnalysis],
    ) -> list[list[CellAnalysis]]:
        by_position = {(cell.row, cell.column): cell for cell in cells}
        positions = frozenset(by_position)

        if self._looks_like_deferred_single_cell_stack(cells):
            return [[cell] for cell in sorted(cells, key=lambda cell: (cell.row, cell.column))]

        completed = self._complete_legal_footprint(positions, all_component_cells)
        if completed is not None:
            return [[all_component_cells[position] for position in sorted(completed)]]

        if self._is_legal_item_shape(positions):
            return [sorted(cells, key=lambda cell: (cell.row, cell.column))]

        candidates = self._legal_shape_candidates(by_position)
        best = self._cover_positions(positions, candidates, {})
        if best is None:
            return [[cell] for cell in sorted(cells, key=lambda cell: (cell.row, cell.column))]

        groups: list[list[CellAnalysis]] = []
        for candidate in best:
            candidate_cells = [by_position[position] for position in sorted(candidate)]
            if self._looks_like_deferred_single_cell_stack(candidate_cells):
                groups.extend([[cell] for cell in candidate_cells])
            else:
                groups.append(candidate_cells)
        return groups

    def _legal_shape_candidates(self, by_position: dict[tuple[int, int], CellAnalysis]) -> list[frozenset[tuple[int, int]]]:
        positions = set(by_position)
        candidates: set[frozenset[tuple[int, int]]] = set()
        for row, column in positions:
            for width, height in self.allowed_item_shapes:
                rect_positions = frozenset(
                    (candidate_row, candidate_column)
                    for candidate_row in range(row, row + height)
                    for candidate_column in range(column, column + width)
                )
                if rect_positions and rect_positions <= positions:
                    candidates.add(rect_positions)
        return sorted(candidates, key=lambda candidate: (-len(candidate), min(candidate)))

    def _complete_legal_footprint(
        self,
        evidence_positions: frozenset[tuple[int, int]],
        all_cells: dict[tuple[int, int], CellAnalysis],
    ) -> frozenset[tuple[int, int]] | None:
        if len(evidence_positions) < 3:
            return None

        candidates: list[frozenset[tuple[int, int]]] = []
        for width, height in self.allowed_item_shapes:
            if width == 1 and height == 1:
                continue
            for top in range(self.rows - height + 1):
                for left in range(self.columns - width + 1):
                    positions = frozenset(
                        (row, column)
                        for row in range(top, top + height)
                        for column in range(left, left + width)
                    )
                    if not evidence_positions <= positions:
                        continue
                    missing = positions - evidence_positions
                    if len(missing) > 3:
                        continue
                    if any(all_cells[position].filtered_out for position in missing if position in all_cells):
                        continue
                    candidates.append(positions)

        if not candidates:
            return None

        return min(
            candidates,
            key=lambda positions: (
                len(positions - evidence_positions),
                len(positions),
                min(positions),
            ),
        )

    def _cover_positions(
        self,
        remaining: frozenset[tuple[int, int]],
        candidates: list[frozenset[tuple[int, int]]],
        memo: dict[frozenset[tuple[int, int]], list[frozenset[tuple[int, int]]] | None],
    ) -> list[frozenset[tuple[int, int]]] | None:
        if not remaining:
            return []
        if remaining in memo:
            return memo[remaining]

        first = min(remaining)
        choices = [candidate for candidate in candidates if first in candidate and candidate <= remaining]
        best: list[frozenset[tuple[int, int]]] | None = None
        for candidate in choices:
            rest = self._cover_positions(remaining - candidate, candidates, memo)
            if rest is None:
                continue
            proposal = [candidate] + rest
            if best is None or self._shape_cover_score(proposal) < self._shape_cover_score(best):
                best = proposal

        memo[remaining] = best
        return best

    @staticmethod
    def _shape_cover_score(cover: list[frozenset[tuple[int, int]]]) -> tuple[int, int]:
        return (len(cover), -sum(len(candidate) * len(candidate) for candidate in cover))

    def _is_legal_item_shape(self, positions: frozenset[tuple[int, int]]) -> bool:
        if len(positions) > self.max_item_cells:
            return False
        rows = [row for row, _ in positions]
        columns = [column for _, column in positions]
        width = max(columns) - min(columns) + 1
        height = max(rows) - min(rows) + 1
        if (width, height) not in self.allowed_item_shapes:
            return False
        return len(positions) == width * height

    @staticmethod
    def _looks_like_deferred_single_cell_stack(cells: list[CellAnalysis]) -> bool:
        rows = {cell.row for cell in cells}
        columns = {cell.column for cell in cells}
        return (
            len(columns) == 1
            and len(rows) == len(cells)
            and len(cells) > 1
            and all(cell.deferred for cell in cells)
        )

    def _split_disconnected_cells(self, cells: list[CellAnalysis]) -> list[list[CellAnalysis]]:
        by_position = {(cell.row, cell.column): cell for cell in cells}
        visited: set[tuple[int, int]] = set()
        components: list[list[CellAnalysis]] = []

        for cell in sorted(cells, key=lambda item: (item.row, item.column)):
            key = (cell.row, cell.column)
            if key in visited:
                continue
            component: list[CellAnalysis] = []
            stack = [cell]
            visited.add(key)
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor_key in self._neighbor_keys(current.row, current.column):
                    if neighbor_key in visited:
                        continue
                    neighbor = by_position.get(neighbor_key)
                    if neighbor is None:
                        continue
                    visited.add(neighbor_key)
                    stack.append(neighbor)
            components.append(sorted(component, key=lambda item: (item.row, item.column)))

        return components

    def _component_to_group(self, cells: list[CellAnalysis]) -> ItemGroup:
        return ItemGroup(
            cells=cells,
            rect=RatioRect(
                left=min(cell.rect.left for cell in cells),
                top=min(cell.rect.top for cell in cells),
                right=max(cell.rect.right for cell in cells),
                bottom=max(cell.rect.bottom for cell in cells),
            ),
            deferred=any(cell.deferred for cell in cells),
            inferred_cells=[
                f"r{cell.row + 1}c{cell.column + 1}"
                for cell in sorted(cells, key=lambda item: (item.row, item.column))
                if not cell.occupied
            ],
        )

    @staticmethod
    def _neighbor_keys(row: int, column: int) -> tuple[tuple[int, int], ...]:
        return ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1))

    @staticmethod
    def _is_sideways_deferred_stack_join(
        cell: CellAnalysis,
        neighbor: CellAnalysis,
        by_position: dict[tuple[int, int], CellAnalysis],
    ) -> bool:
        if cell.row != neighbor.row or cell.deferred == neighbor.deferred:
            return False
        deferred_cell = cell if cell.deferred else neighbor
        has_vertical_deferred_neighbor = any(
            (
                by_position.get((deferred_cell.row + row_delta, deferred_cell.column)) is not None
                and by_position[(deferred_cell.row + row_delta, deferred_cell.column)].occupied
                and by_position[(deferred_cell.row + row_delta, deferred_cell.column)].deferred
            )
            for row_delta in (-1, 1)
        )
        return has_vertical_deferred_neighbor

    def _group_to_item(self, index: int, group: ItemGroup) -> DetectedItem:
        status = "deferred" if group.deferred else "available"
        decision = "select" if group.deferred else "review"
        reason = (
            "Detected as already deferred from gold Ritual border; click again to defer/select it"
            if group.deferred
            else "Detected occupied reward shape; tooltip identification and pricing are required"
        )
        region = self._inset_rect(group.rect)
        return DetectedItem(
            item_id=f"item-{index:03d}",
            region=region,
            click_point=region.center(),
            grid_cells=[f"r{cell.row + 1}c{cell.column + 1}" for cell in sorted(group.cells, key=lambda c: (c.row, c.column))],
            is_deferred=group.deferred,
            identification=IdentificationResult(
                internal_item_id=f"unknown/{status}/shape-{index:03d}",
                display_name=f"Unknown {status.title()} Item",
                category="unknown",
                status="unknown",
                score=0.0,
                confidence_gap=0.0,
                identification_scope="unknown",
                requires_tooltip=not group.deferred,
            ),
            estimated_price=PriceEstimate(amount=None, currency="exalted", confidence=0.0, status="unknown"),
            decision=decision,
            decision_reason=reason,
        )

    def _clickable_group_rect(self, group: ItemGroup) -> RatioRect:
        positions = frozenset((cell.row, cell.column) for cell in group.cells)
        if self._is_full_rectangle(positions):
            return group.rect
        primary_cell = max(
            group.cells,
            key=lambda cell: (
                cell.deferred == group.deferred,
                cell.content_ratio + cell.brown_line_ratio + cell.gold_ratio,
                -cell.row,
                -cell.column,
            ),
        )
        return primary_cell.rect

    @staticmethod
    def _is_full_rectangle(positions: frozenset[tuple[int, int]]) -> bool:
        if not positions:
            return False
        rows = [row for row, _ in positions]
        columns = [column for _, column in positions]
        width = max(columns) - min(columns) + 1
        height = max(rows) - min(rows) + 1
        return len(positions) == width * height

    def _write_debug(
        self,
        cells: list[CellAnalysis],
        groups: list[ItemGroup],
        image: Image.Image,
        debug_dir: Path,
        foreground_mask: Image.Image | None = None,
        mask_components: list[MaskComponent] | None = None,
    ) -> None:
        write_json(
            debug_dir / "item-groups.json",
            [
                {
                    "item_index": index,
                    "cells": [f"r{cell.row + 1}c{cell.column + 1}" for cell in sorted(group.cells, key=lambda c: (c.row, c.column))],
                    "inferred_cells": group.inferred_cells,
                    "deferred": group.deferred,
                    "gold_ratio": max(cell.gold_ratio for cell in group.cells),
                    "rect": group.rect.model_dump(mode="json"),
                    "click_point": group.rect.center().model_dump(mode="json"),
                }
                for index, group in enumerate(groups, start=1)
            ],
        )

        width, height = image.size
        cell_overlay = image.copy()
        cell_draw = ImageDraw.Draw(cell_overlay)
        cell_draw.rectangle(self.board.to_pixels(width, height), outline=(255, 210, 90), width=4)
        for cell in cells:
            if cell.filtered_out:
                color = (130, 130, 130)
            elif cell.deferred:
                color = (80, 220, 130)
            elif cell.occupied:
                color = (90, 210, 255)
            else:
                continue
            rect = self._inset_rect(cell.rect).to_pixels(width, height)
            cell_draw.rectangle(rect, outline=color, width=2)
            cell_draw.text((rect[0] + 4, rect[1] + 4), f"{cell.row + 1},{cell.column + 1}", fill=color)
        cell_overlay.save(debug_dir / "cell-analysis.png")
        if foreground_mask is not None:
            foreground_mask.save(debug_dir / "grayscale-foreground-mask.png")
        if mask_components is not None:
            component_overlay = image.copy()
            component_draw = ImageDraw.Draw(component_overlay)
            for index, component in enumerate(mask_components, start=1):
                component_draw.rectangle(component.bbox, outline=(255, 0, 255), width=2)
                component_draw.text((component.bbox[0] + 3, component.bbox[1] + 3), str(index), fill=(255, 0, 255))
            component_overlay.save(debug_dir / "mask-components.png")

    def _inset_rect(self, rect: RatioRect) -> RatioRect:
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        x_inset = width * self.item_region_inset_ratio
        y_inset = height * self.item_region_inset_ratio
        return RatioRect(
            left=rect.left + x_inset,
            top=rect.top + y_inset,
            right=rect.right - x_inset,
            bottom=rect.bottom - y_inset,
        )

    @staticmethod
    def _gold_ratio(crop: Image.Image) -> float:
        rgb_crop = crop.convert("RGB")
        pixels = (
            rgb_crop.get_flattened_data()
            if hasattr(rgb_crop, "get_flattened_data")
            else rgb_crop.getdata()
        )
        total = 0
        gold = 0
        for red, green, blue in pixels:
            total += 1
            if red >= 115 and green >= 80 and blue <= 80 and red >= green >= blue:
                gold += 1
        return gold / max(total, 1)

    @staticmethod
    def _cell_content_ratios(crop: Image.Image) -> tuple[float, float]:
        rgb_crop = crop.convert("RGB")
        edge = rgb_crop.convert("L").filter(ImageFilter.FIND_EDGES)
        pixels = (
            rgb_crop.get_flattened_data()
            if hasattr(rgb_crop, "get_flattened_data")
            else rgb_crop.getdata()
        )
        edge_pixels = (
            edge.get_flattened_data()
            if hasattr(edge, "get_flattened_data")
            else edge.getdata()
        )
        total = 0
        content = 0
        brown_line = 0
        for (red, green, blue), edge_value in zip(pixels, edge_pixels):
            total += 1
            maximum = max(red, green, blue)
            minimum = min(red, green, blue)
            saturation = maximum - minimum
            gold = red >= 105 and green >= 70 and blue <= 85 and red >= green >= blue
            if not gold and ((maximum > 55 and saturation > 18) or maximum > 80):
                content += 1
            brown = red >= 28 and green >= 18 and blue <= 55 and red >= green >= blue and saturation >= 8
            if brown and edge_value > 18:
                brown_line += 1
        return content / max(total, 1), brown_line / max(total, 1)
