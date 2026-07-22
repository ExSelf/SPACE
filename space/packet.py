"""Simple packet model used by the bridge."""

from __future__ import annotations

import json
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

    def to_wire_payload(self) -> bytes:
        """Serialize the packet to a compact JSON payload for the ESP32."""
        data = {
            "type": self.type,
            "node": self.node,
            "command": self.command,
            "parameter": self.parameter,
            "voltage": self.voltage,
            "charge": self.charge,
            "ttl": self.ttl,
            "constant_commands": self.constant_commands.hex() if self.constant_commands else None,
        }
        return json.dumps(data, separators=(",", ":")).encode("utf-8")
