"""MIDI input wrapper for listening to commands from a MIDI device."""

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
        self._port = None
        self._closed = True

    def open(self) -> None:
        """Open the MIDI input and register the callback."""
        ports = list_input_ports()
        if self.port_name and self.port_name not in ports:
            print(f"Requested MIDI port '{self.port_name}' was not found. Available ports: {ports}")
            self.port_name = None

        try:
            self._port = mido.open_input(self.port_name, callback=self.callback)
            print(f"MIDI input ready on: {self.port_name or '(default)'}")
        except Exception as exc:  # pragma: no cover - runtime environment specific
            print(f"Unable to open MIDI input: {exc}")
            self._port = None

        self._closed = self._port is None

    def close(self) -> None:
        """Close the MIDI input."""
        if self._port is not None:
            self._port.close()
        self._closed = True
        print("MIDI input closed.")
