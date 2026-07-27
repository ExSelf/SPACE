"""Serial link wrapper for talking to an ESP32 over USB."""

from __future__ import annotations

from typing import Callable

import serial
from serial.tools import list_ports


class SerialLink:
    """A lightweight wrapper around pyserial for packet transport."""

    def __init__(self, port: str | None, baud_rate: int):
        self.port = port
        self.baud_rate = baud_rate
        self.on_packet: Callable | None = None
        self._serial = None

    @staticmethod
    def list_ports() -> list[str]:
        """Return the available serial port names."""
        return [port.device for port in list_ports.comports()]

    def open(self) -> None:
        """Open the serial connection."""
        if not self.port:
            ports = self.list_ports()
            if not ports:
                raise RuntimeError("No serial ports detected")
            self.port = ports[0]

        try:
            self._serial = serial.Serial(self.port, self.baud_rate, timeout=0.1)
        except Exception as exc:  # pragma: no cover - runtime environment specific
            self._serial = None
            raise RuntimeError(f"Unable to open serial port {self.port}: {exc}") from exc

        print(f"Serial link open on {self.port} at {self.baud_rate} baud")

    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def send(self, packet) -> None:
        """Send a packet to the serial device."""
        if self.on_packet is not None:
            self.on_packet(packet)

        if not self.is_open():
            return

        payload = packet.to_wire_payload() + b"\n"
        self._serial.write(payload)
        self._serial.flush()
        print(f"Sent: {payload.decode('utf-8', errors='ignore')}")

    def close(self) -> None:
        """Close the serial connection."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        print("Serial link closed.")
