"""Simple packet model used by the bridge."""

from __future__ import annotations

from dataclasses import dataclass

TYPE_COMMAND = "command"


@dataclass
class Packet:
    """Represents a command packet sent to the serial device."""

    type: str = TYPE_COMMAND
    node: int = 0
    command: int | None = None
    parameter: int | None = None
    voltage: int | None = None
    charge: int | None = None
    ttl: int | None = None
    constant_commands: bytes | None = None
