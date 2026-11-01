"""Serial link wrapper for talking to an ESP32 over USB."""

from __future__ import annotations

import queue
import threading
from typing import Callable

import serial
from serial.tools import list_ports

from space.packet import PACKET_SIZE, TYPE_STATUS, StatusPacket


def extract_status_frames(buffer: bytearray) -> list[bytes]:
    """Extract complete SUN status packets from BEAM's binary USB stream."""
    packets = []
    while True:
        start = buffer.find(bytes((TYPE_STATUS,)))
        if start < 0:
            buffer.clear()
            break
        if start:
            del buffer[:start]
        if len(buffer) < PACKET_SIZE:
            break

        frame = bytes(buffer[:PACKET_SIZE])
        if frame[1] == 0 or frame[2] > 12 or StatusPacket.from_bytes(frame) is None:
            del buffer[0]
            continue

        del buffer[:PACKET_SIZE]
        packets.append(frame)
    return packets


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
        """Read BEAM's fixed-size binary SUN records from the serial byte stream."""
        receive_buffer = bytearray()
        while not self._stop_receive and self.is_open():
            try:
                waiting = self._serial.in_waiting
                if waiting > 0:
                    data = self._serial.read(waiting)
                    if data:
                        receive_buffer.extend(data)
                        for packet in extract_status_frames(receive_buffer):
                            self._rx_queue.put(packet)
                            if self.on_receive is not None:
                                self.on_receive(packet)
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
        """Send a 250-byte binary packet as one BEAM USB line."""
        if self.on_packet is not None:
            self.on_packet(packet)

        if not self.is_open():
            return

        payload = packet.to_bytes()
        if len(payload) != PACKET_SIZE:
            raise ValueError(f"Expected a {PACKET_SIZE}-byte packet, got {len(payload)}")
        if b"\r" in payload or b"\n" in payload:
            raise ValueError("BEAM USB line framing cannot carry carriage-return or newline bytes")

        payload += b"\n"
        self._serial.write(payload)
        self._serial.flush()
        print(f"Sent {PACKET_SIZE}-byte binary packet to {self.port}")

    def close(self) -> None:
        """Close the serial connection and stop the receive thread."""
        self._stop_receive = True
        
        # Wait for receive thread to stop
        if self._receive_thread is not None and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=1.0)
        
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        print("Serial link closed.")
