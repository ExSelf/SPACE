"""Serial link wrapper for talking to an ESP32 over USB."""

from __future__ import annotations

import queue
import threading
from typing import Callable

import serial
from serial.tools import list_ports


class SerialLink:
    """A lightweight wrapper around pyserial for packet transport with bi-directional support."""

    def __init__(self, port: str | None, baud_rate: int):
        self.port = port
        self.baud_rate = baud_rate
        self.on_packet: Callable | None = None
        self.on_receive: Callable | None = None
        self._serial = None
        self._rx_queue: queue.Queue = queue.Queue()
        self._receive_thread: threading.Thread | None = None
        self._stop_receive = False

    @staticmethod
    def list_ports() -> list[str]:
        """Return the available serial port names."""
        return [port.device for port in list_ports.comports()]

    def open(self) -> None:
        """Open the serial connection and start the receive thread."""
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

        # Start the receive thread
        self._stop_receive = False
        self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._receive_thread.start()

        print(f"Serial link open on {self.port} at {self.baud_rate} baud")

    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _receive_loop(self) -> None:
        """Background thread: continuously read from serial port and queue received data."""
        while not self._stop_receive and self.is_open():
            try:
                if self._serial.in_waiting > 0:
                    data = self._serial.readline()
                    if data:
                        self._rx_queue.put(data)
                        print(f"Received: {data.decode('utf-8', errors='ignore')}")
                        # Trigger callback if set
                        if self.on_receive is not None:
                            self.on_receive(data)
            except Exception as exc:
                if not self._stop_receive:
                    print(f"Error reading from serial: {exc}")

    def get_received_data(self) -> bytes | None:
        """Non-blocking get of received data from the queue."""
        try:
            return self._rx_queue.get_nowait()
        except queue.Empty:
            return None

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
        """Close the serial connection and stop the receive thread."""
        self._stop_receive = True
        
        # Wait for receive thread to stop
        if self._receive_thread is not None and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=1.0)
        
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        print("Serial link closed.")
