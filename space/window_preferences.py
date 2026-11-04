"""Load user-editable window and table layout preferences."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_WINDOW_WIDTH = 900
DEFAULT_WINDOW_HEIGHT = 700
DEFAULT_COLUMN_WIDTHS = {
    "Node": 55,
    "Name": 150,
    "Status": 145,
    "Address": 130,
    "Cmd": 70,
    "Actual Cmd": 100,
    "Param": 70,
    "Actual Param": 110,
    "Voltage": 85,
    "Charge": 80,
    **{f"Ch {channel}": 55 for channel in range(1, 17)},
}


@dataclass(frozen=True)
class WindowPreferences:
    width: int = DEFAULT_WINDOW_WIDTH
    height: int = DEFAULT_WINDOW_HEIGHT
    column_widths: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_COLUMN_WIDTHS))


def load_window_preferences(path: str | Path) -> WindowPreferences:
    """Load valid preference values, reporting malformed files or entries."""
    file_path = Path(path)
    if not file_path.exists():
        return WindowPreferences()

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read window preferences from {file_path}: {exc}")
        return WindowPreferences()

    if not isinstance(payload, dict):
        print(f"Invalid window preferences in {file_path}: expected a JSON object.")
        return WindowPreferences()

    width = (
        _valid_integer(payload["window_width"], 760, 10000, "window_width", file_path)
        if "window_width" in payload
        else None
    )
    height = (
        _valid_integer(payload["window_height"], 560, 10000, "window_height", file_path)
        if "window_height" in payload
        else None
    )
    column_widths = dict(DEFAULT_COLUMN_WIDTHS)
    configured_widths = payload.get("node_table_column_widths", {})
    if not isinstance(configured_widths, dict):
        print(f"Invalid node_table_column_widths in {file_path}: expected a JSON object.")
    else:
        for column, value in configured_widths.items():
            if column not in column_widths:
                print(f"Unknown table column '{column}' in {file_path}; ignoring it.")
                continue
            valid_width = _valid_integer(value, 20, 2000, f"node_table_column_widths.{column}", file_path)
            if valid_width is not None:
                column_widths[column] = valid_width

    return WindowPreferences(
        width=width if width is not None else DEFAULT_WINDOW_WIDTH,
        height=height if height is not None else DEFAULT_WINDOW_HEIGHT,
        column_widths=column_widths,
    )


def _valid_integer(value: object, minimum: int, maximum: int, name: str, path: Path) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        print(f"Invalid {name} in {path}; expected an integer from {minimum} to {maximum}.")
        return None
    return value
