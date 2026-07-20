"""Minimal serial link wrapper for beginners."""

from __future__ import annotations

from typing import Callable


class SerialLink:
    """Placeholder serial bridge used by the example app."""

    def __init__(self, port: str, baud_rate: int):
        self.port = port
        self.baud_rate = baud_rate
        self.on_packet: Callable | None = None

    @staticmethod
    def list_ports() -> list[str]:
        """Return a placeholder list of serial ports."""
        return ["/dev/ttyUSB0", "/dev/ttyACM0"]

    def open(self) -> None:
        """Open the serial connection."""
        print(f"Serial link open on {self.port} at {self.baud_rate} baud")

    def send(self, packet) -> None:
        """Send a packet to the serial device."""
        if self.on_packet is not None:
            self.on_packet(packet)
        print(f"Sending packet: {packet}")

    def close(self) -> None:
        """Close the serial connection."""
        print("Serial link closed.")
