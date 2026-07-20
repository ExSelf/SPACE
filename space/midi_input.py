"""Minimal MIDI input wrapper for beginner-friendly use."""

from __future__ import annotations

from typing import Callable

import mido


def list_input_ports() -> list[str]:
    """Return the available MIDI input port names."""
    try:
        return list(mido.get_input_names())
    except Exception:
        return []


class MidiInput:
    """Simple wrapper around a MIDI input callback."""

    def __init__(self, port_name: str | None = None, callback: Callable | None = None):
        self.port_name = port_name
        self.callback = callback
        self._closed = True

    def open(self) -> None:
        """Open the MIDI input and print a friendly message."""
        ports = list_input_ports()
        if self.port_name and self.port_name not in ports:
            print(f"Requested MIDI port '{self.port_name}' was not found. Available ports: {ports}")
        else:
            print(f"MIDI input ready on: {self.port_name or '(default)'}")
        self._closed = False

    def close(self) -> None:
        """Close the MIDI input."""
        self._closed = True
        print("MIDI input closed.")
