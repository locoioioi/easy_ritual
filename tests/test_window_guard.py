from __future__ import annotations

from ritual_helper.shared.window_guard import ActiveWindowInfo, window_info_matches


def test_window_info_matches_poe2_title_and_process() -> None:
    info = ActiveWindowInfo(
        hwnd=1,
        title="Path of Exile 2",
        process_id=10,
        process_name="PathOfExileSteam.exe",
        process_path="C:/Games/PathOfExileSteam.exe",
    )

    assert window_info_matches(
        info,
        {
            "title_keywords": ["Path of Exile 2"],
            "process_names": ["PathOfExileSteam.exe"],
        },
    )


def test_window_info_rejects_non_poe2_process() -> None:
    info = ActiveWindowInfo(
        hwnd=1,
        title="Path of Exile 2 wiki",
        process_id=10,
        process_name="chrome.exe",
        process_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
    )

    assert not window_info_matches(
        info,
        {
            "title_keywords": ["Path of Exile 2"],
            "process_names": ["PathOfExileSteam.exe"],
        },
    )

