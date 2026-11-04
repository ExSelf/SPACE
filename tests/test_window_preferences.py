from __future__ import annotations

import json

from space.window_preferences import (
    DEFAULT_COLUMN_WIDTHS,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    load_window_preferences,
)


def test_load_window_preferences_uses_defaults_when_file_is_missing(tmp_path) -> None:
    preferences = load_window_preferences(tmp_path / "window_preferences.json")

    assert preferences.width == DEFAULT_WINDOW_WIDTH
    assert preferences.height == DEFAULT_WINDOW_HEIGHT
    assert preferences.column_widths == DEFAULT_COLUMN_WIDTHS


def test_load_window_preferences_applies_configured_values(tmp_path) -> None:
    path = tmp_path / "window_preferences.json"
    path.write_text(
        json.dumps(
            {
                "window_width": 1200,
                "window_height": 800,
                "node_table_column_widths": {"Name": 240, "Ch 1": 72},
            }
        ),
        encoding="utf-8",
    )

    preferences = load_window_preferences(path)

    assert preferences.width == 1200
    assert preferences.height == 800
    assert preferences.column_widths["Name"] == 240
    assert preferences.column_widths["Ch 1"] == 72
    assert preferences.column_widths["Node"] == DEFAULT_COLUMN_WIDTHS["Node"]


def test_load_window_preferences_ignores_invalid_values(tmp_path, capsys) -> None:
    path = tmp_path / "window_preferences.json"
    path.write_text(
        json.dumps(
            {
                "window_width": "wide",
                "node_table_column_widths": {"Name": -1},
            }
        ),
        encoding="utf-8",
    )

    preferences = load_window_preferences(path)

    assert preferences.width == DEFAULT_WINDOW_WIDTH
    assert preferences.column_widths["Name"] == DEFAULT_COLUMN_WIDTHS["Name"]
    assert "Invalid window_width" in capsys.readouterr().out
