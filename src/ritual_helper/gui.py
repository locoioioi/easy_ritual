from __future__ import annotations

import copy
import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from ritual_helper.controller.application_controller import ApplicationController, build_controller
from ritual_helper.controller.hotkey_controller import HotkeyController
from ritual_helper.shared.configuration import AppConfig, load_config


CONFIG_DEFAULTS: dict[str, Any] = {
    "application.mode": "test",
    "application.fixture_screenshot": "fixtures/screenshots/ritual-provided-2.jpg",
    "application.analyzer": "grid",
    "application.debug_enabled": True,
    "application.live_execution_enabled": False,
    "application.executor_backends": ["recording", "render"],
    "application.output_dir": "output",
    "application.target_window.title_keywords": ["Path of Exile 2"],
    "application.target_window.process_names": ["PathOfExileSteam.exe", "PathOfExile.exe", "PathOfExile_x64.exe"],
    "application.pricing.source": "poe2scout",
    "application.pricing.league": "Runes of Aldur",
    "application.pricing.timeout_seconds": 8.0,
    "selection_policy.minimum_defer_value": 10.0,
    "selection_policy.price_currency": "exalted",
    "application.delays.after_item_click_ms": 300,
    "application.delays.before_deferred_item_click_ms": 120,
    "application.delays.after_reroll_ms": 350,
    "application.delays.before_defer_ms": 650,
    "application.delays.after_defer_ms": 250,
    "application.delays.mouse_down_up_ms": 35,
    "application.delays.before_confirm_defer_ms": 250,
    "application.delays.after_confirm_ms": 250,
    "application.ui_controls.reroll.x": 0.1969,
    "application.ui_controls.reroll.y": 0.2009,
    "application.ui_controls.defer.x": 0.4479,
    "application.ui_controls.defer.y": 0.2019,
    "application.ui_controls.confirm_defer.x": 0.3276,
    "application.ui_controls.confirm_defer.y": 0.8231,
    "vision.board.left": 0.1604,
    "vision.board.top": 0.2444,
    "vision.board.right": 0.4356,
    "vision.board.bottom": 0.7343,
    "vision.grid.columns": 10,
    "vision.grid.rows": 10,
    "vision.grid.cell_padding_px": 6,
    "vision.grid.deferred_gold_ratio_threshold": 0.013,
    "vision.grid.use_grayscale_mask": True,
    "vision.grid.canny_threshold1": 70,
    "vision.grid.canny_threshold2": 150,
    "vision.grid.canny_dilate_kernel": 3,
    "vision.grid.canny_dilate_iterations": 1,
    "vision.grid.mask_min_area": 120.0,
    "vision.grid.contour_cell_min_overlap_ratio": 0.12,
}


class RitualHelperGui:
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self.base_config = load_config(root_path)
        self.application = copy.deepcopy(self.base_config.application)
        self.vision = copy.deepcopy(self.base_config.vision)
        self.selection_policy = copy.deepcopy(self.base_config.selection_policy)
        self.controller: ApplicationController | None = None
        self.hotkey_thread: threading.Thread | None = None

        self.window = tk.Tk()
        self.window.title("PoE 2 Ritual Helper")
        self.window.geometry("680x620")
        self.window.minsize(560, 520)

        self.status_var = tk.StringVar(value="Stopped")
        self.running_var = tk.StringVar(value="Helper is stopped")
        self.fields: dict[str, tk.Variable] = {}

        self._build_layout()
        self._load_fields()
        self.window.lift()
        self.window.attributes("-topmost", True)
        self.window.after(800, lambda: self.window.attributes("-topmost", False))
        self.window.focus_force()
        self._poll_status()

    def run(self) -> None:
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.mainloop()

    def _build_layout(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        top = ttk.Frame(self.window, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(2, weight=1)

        self.start_button = ttk.Button(top, text="Start", command=self._start_helper)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.stop_button = ttk.Button(top, text="Stop", command=self._stop_helper, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(top, textvariable=self.running_var).grid(row=0, column=2, sticky="w")

        notebook = ttk.Notebook(self.window)
        notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        runtime = ttk.Frame(notebook, padding=10)
        selection = ttk.Frame(notebook, padding=10)
        controls = ttk.Frame(notebook, padding=10)
        vision = ttk.Frame(notebook, padding=10)
        notebook.add(runtime, text="Runtime")
        notebook.add(selection, text="Selection")
        notebook.add(controls, text="Coordinates")
        notebook.add(vision, text="Vision")

        self._build_runtime_tab(runtime)
        self._build_selection_tab(selection)
        self._build_controls_tab(controls)
        self._build_vision_tab(vision)

        bottom = ttk.Frame(self.window, padding=(12, 0, 12, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="Reload", command=self._reload_config).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(bottom, text="Save Config", command=self._save_config).grid(row=0, column=2, padx=(8, 0))

    def _build_runtime_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self._combo(parent, "Mode", "application.mode", ("test", "live"), row=0)
        self._check(parent, "Live mouse execution", "application.live_execution_enabled", row=1)
        self._check(parent, "Enable debug", "application.debug_enabled", row=2)
        self._entry(parent, "Executor backends", "application.executor_backends", row=3)
        self._entry(parent, "Output directory", "application.output_dir", row=4)
        self._entry(parent, "Fixture screenshot", "application.fixture_screenshot", row=5)
        ttk.Button(parent, text="Browse", command=self._choose_fixture).grid(row=5, column=2, padx=(8, 0))
        self._entry(parent, "Target title keywords", "application.target_window.title_keywords", row=6)
        self._entry(parent, "Target process names", "application.target_window.process_names", row=7)
        self._combo(parent, "Pricing source", "application.pricing.source", ("poe2scout", "poe.ninja", "static"), row=8)
        self._entry(parent, "Pricing league", "application.pricing.league", row=9)
        self._entry(parent, "Pricing timeout sec", "application.pricing.timeout_seconds", row=10)
        self._entry(parent, "After item click ms", "application.delays.after_item_click_ms", row=11)
        self._entry(parent, "Before deferred item click ms", "application.delays.before_deferred_item_click_ms", row=12)
        self._entry(parent, "After reroll ms", "application.delays.after_reroll_ms", row=13)
        self._entry(parent, "Before defer ms", "application.delays.before_defer_ms", row=14)
        self._entry(parent, "After defer ms", "application.delays.after_defer_ms", row=15)
        self._entry(parent, "Mouse down/up ms", "application.delays.mouse_down_up_ms", row=16)
        self._entry(parent, "Before confirm ms", "application.delays.before_confirm_defer_ms", row=17)
        self._entry(parent, "After confirm ms", "application.delays.after_confirm_ms", row=18)

    def _build_selection_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self._entry(parent, "Minimum defer value", "selection_policy.minimum_defer_value", row=0)
        self._combo(parent, "Price currency", "selection_policy.price_currency", ("exalted", "chaos", "divine"), row=1)

    def _build_controls_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)
        ttk.Label(parent, text="X").grid(row=0, column=1)
        ttk.Label(parent, text="Y").grid(row=0, column=2)
        for row, name in enumerate(("reroll", "defer", "confirm_defer"), start=1):
            ttk.Label(parent, text=name).grid(row=row, column=0, sticky="w", pady=4)
            self._raw_entry(parent, f"application.ui_controls.{name}.x", row, 1)
            self._raw_entry(parent, f"application.ui_controls.{name}.y", row, 2)

    def _build_vision_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self._entry(parent, "Board left", "vision.board.left", row=0)
        self._entry(parent, "Board top", "vision.board.top", row=1)
        self._entry(parent, "Board right", "vision.board.right", row=2)
        self._entry(parent, "Board bottom", "vision.board.bottom", row=3)
        self._entry(parent, "Columns", "vision.grid.columns", row=4)
        self._entry(parent, "Rows", "vision.grid.rows", row=5)
        self._entry(parent, "Cell padding px", "vision.grid.cell_padding_px", row=6)
        self._entry(parent, "Deferred gold threshold", "vision.grid.deferred_gold_ratio_threshold", row=7)
        self._check(parent, "Use grayscale mask", "vision.grid.use_grayscale_mask", row=8)
        self._entry(parent, "Canny threshold 1", "vision.grid.canny_threshold1", row=9)
        self._entry(parent, "Canny threshold 2", "vision.grid.canny_threshold2", row=10)
        self._entry(parent, "Canny dilate kernel", "vision.grid.canny_dilate_kernel", row=11)
        self._entry(parent, "Canny dilate iterations", "vision.grid.canny_dilate_iterations", row=12)
        self._entry(parent, "Mask minimum area", "vision.grid.mask_min_area", row=13)
        self._entry(parent, "Contour cell overlap", "vision.grid.contour_cell_min_overlap_ratio", row=14)

    def _entry(self, parent: ttk.Frame, label: str, key: str, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        self._raw_entry(parent, key, row, 1)

    def _raw_entry(self, parent: ttk.Frame, key: str, row: int, column: int) -> None:
        variable = tk.StringVar()
        self.fields[key] = variable
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=column, sticky="ew", padx=(8, 0), pady=4)

    def _combo(self, parent: ttk.Frame, label: str, key: str, values: tuple[str, ...], row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        variable = tk.StringVar()
        self.fields[key] = variable
        ttk.Combobox(parent, textvariable=variable, values=values, state="readonly").grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)

    def _check(self, parent: ttk.Frame, label: str, key: str, row: int) -> None:
        variable = tk.BooleanVar()
        self.fields[key] = variable
        ttk.Checkbutton(parent, text=label, variable=variable).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)

    def _load_fields(self) -> None:
        for key, variable in self.fields.items():
            value = self._get_config_value(key)
            if isinstance(variable, tk.BooleanVar):
                variable.set(bool(value))
            elif isinstance(value, list):
                variable.set(", ".join(value))
            else:
                variable.set(str(value))

    def _reload_config(self) -> None:
        if self._is_running():
            messagebox.showinfo("Helper Running", "Stop the helper before reloading config.")
            return
        self.base_config = load_config(self.root_path)
        self.application = copy.deepcopy(self.base_config.application)
        self.vision = copy.deepcopy(self.base_config.vision)
        self.selection_policy = copy.deepcopy(self.base_config.selection_policy)
        self._load_fields()
        self.status_var.set("Config reloaded")

    def _save_config(self) -> None:
        if self._is_running():
            messagebox.showinfo("Helper Running", "Stop the helper before saving config.")
            return
        try:
            self._apply_fields()
            self._write_json(self.root_path / "config" / "application.json", self.application)
            self._write_json(self.root_path / "config" / "vision.json", self.vision)
            self._write_json(self.root_path / "config" / "selection-policy.json", self.selection_policy)
        except Exception as exc:
            messagebox.showerror("Save Failed", str(exc))
            return
        self.base_config = load_config(self.root_path)
        self.status_var.set("Config saved")

    def _choose_fixture(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(self.root_path / "fixtures" / "screenshots"),
            filetypes=(("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")),
        )
        if path:
            self.fields["application.fixture_screenshot"].set(path)

    def _start_helper(self) -> None:
        if self._is_running():
            return
        try:
            self._apply_fields()
            config = AppConfig(
                root=self.root_path,
                application=copy.deepcopy(self.application),
                vision=copy.deepcopy(self.vision),
                selection_policy=copy.deepcopy(self.selection_policy),
            )
            self.controller = build_controller(config)
            if not self.controller.state.enabled:
                self.controller.toggle_enabled()
            self.hotkey_thread = threading.Thread(target=HotkeyController(self.controller).run, daemon=True)
            self.hotkey_thread.start()
        except Exception as exc:
            messagebox.showerror("Start Failed", str(exc))
            self.controller = None
            self.hotkey_thread = None
            return
        self.status_var.set("Helper started")
        self._set_running_buttons(True)

    def _stop_helper(self) -> None:
        if self.controller is not None:
            self.controller.stop()
            if self.controller.state.enabled:
                self.controller.toggle_enabled()
        self.status_var.set("Helper stopping")
        self.window.after(250, self._finish_stop)

    def _finish_stop(self) -> None:
        if self.hotkey_thread is not None and self.hotkey_thread.is_alive():
            self.window.after(250, self._finish_stop)
            return
        self.controller = None
        self.hotkey_thread = None
        self._set_running_buttons(False)
        self.status_var.set("Helper stopped")

    def _poll_status(self) -> None:
        if self._is_running() and self.controller is not None:
            cache_count = len(self.controller.checked_items)
            self.running_var.set(f"Running | enabled={self.controller.state.enabled} | cached items={cache_count}")
        elif self.hotkey_thread is not None and not self.hotkey_thread.is_alive():
            self._finish_stop()
        else:
            self.running_var.set("Helper is stopped")
        self.window.after(500, self._poll_status)

    def _set_running_buttons(self, running: bool) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _is_running(self) -> bool:
        return self.hotkey_thread is not None and self.hotkey_thread.is_alive()

    def _close(self) -> None:
        if self._is_running():
            self._stop_helper()
            self.window.after(300, self.window.destroy)
            return
        self.window.destroy()

    def _apply_fields(self) -> None:
        for key, variable in self.fields.items():
            raw_value = variable.get()
            if key in {
                "application.executor_backends",
                "application.target_window.title_keywords",
                "application.target_window.process_names",
            }:
                value: Any = [part.strip() for part in str(raw_value).split(",") if part.strip()]
            else:
                current = self._get_config_value(key)
                value = self._coerce_value(raw_value, current)
            self._set_config_value(key, value)

    def _get_config_value(self, key: str) -> Any:
        root_name, *parts = key.split(".")
        data = self._config_root(root_name)
        for part in parts:
            if not isinstance(data, dict) or part not in data:
                return CONFIG_DEFAULTS[key]
            data = data[part]
        return data

    def _set_config_value(self, key: str, value: Any) -> None:
        root_name, *parts = key.split(".")
        data = self._config_root(root_name)
        for part in parts[:-1]:
            if part not in data or not isinstance(data[part], dict):
                data[part] = {}
            data = data[part]
        data[parts[-1]] = value

    def _config_root(self, root_name: str) -> dict[str, Any]:
        if root_name == "application":
            return self.application
        if root_name == "selection_policy":
            return self.selection_policy
        return self.vision

    @staticmethod
    def _coerce_value(raw_value: Any, current: Any) -> Any:
        if isinstance(current, bool):
            return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(current, int) and not isinstance(current, bool):
            return int(raw_value)
        if isinstance(current, float):
            return float(raw_value)
        return str(raw_value)

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")


def run_gui(root_path: Path) -> None:
    RitualHelperGui(root_path).run()


def main() -> None:
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    root_path = exe_root if (exe_root / "config").exists() else Path.cwd()
    try:
        run_gui(root_path)
    except Exception as exc:
        log_path = root_path / "gui-crash.log"
        log_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        try:
            messagebox.showerror("Ritual Helper Failed", f"{exc}\n\nWrote {log_path}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
