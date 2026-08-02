from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ritual_helper.controller.application_controller import build_controller
from ritual_helper.controller.hotkey_controller import HotkeyController
from ritual_helper.shared.configuration import load_config
from ritual_helper.shared.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PoE 2 Ritual helper")
    parser.add_argument("--once", action="store_true", help="run the offline T workflow once and exit")
    parser.add_argument("--gui", action="store_true", help="open the desktop GUI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root containing config/")
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    config = load_config(args.root)
    controller = build_controller(config)

    if args.gui:
        from ritual_helper.gui import run_gui

        run_gui(args.root)
        return

    if args.once:
        controller.toggle_enabled()
        result = controller.analyze_current_table(require_enabled=True)
        if result is None:
            raise SystemExit(1)
        LOGGER.info("one-shot workflow complete")
        return

    HotkeyController(controller).run()


if __name__ == "__main__":
    main()
