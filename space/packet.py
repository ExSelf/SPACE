"""Simple packet model used by the bridge."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

TYPE_COMMAND = "command"
TYPE_STATUS = "status"
TYPE_ACK = "ack"


@dataclass
class Packet:
    """Represents a command packet sent through BEAM to SUN nodes."""

    type: str = TYPE_COMMAND
    node: int = 0
    ttl: int = 3
    command: int | None = None
    parameter: int | None = None
    voltage: int | None = None
    charge: int | None = None
    constant_commands: bytes | None = None
    timestamp_ms: int | None = None

    def to_wire_payload(self) -> bytes:
        """
        Serialize the packet to CSV format for BEAM compatibility.
        Format: key,ttl,node,time_b0,time_b1,time_b2,time_b3,cmd0,cmd1,...,cmd11
        """
        if self.constant_commands is None:
            self.constant_commands = bytes(12)
        
        # Ensure constant_commands is exactly 12 bytes
        cmds = bytearray(12)
        if self.constant_commands:
            for i, byte in enumerate(self.constant_commands[:12]):
                cmds[i] = byte
        
        # Get timestamp in milliseconds (use lower 32 bits only to fit in uint32)
        if self.timestamp_ms is None:
            self.timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFF
        
        # Split timestamp into 4 bytes (little-endian)
        time_bytes = struct.pack("<I", self.timestamp_ms & 0xFFFFFFFF)
        
        # Build CSV packet: key,ttl,node,t0,t1,t2,t3,c0,c1,...,c11
        parts = [
            "1",  # key (command type)
            str(self.ttl),
            str(self.node),
            str(time_bytes[0]),
            str(time_bytes[1]),
            str(time_bytes[2]),
            str(time_bytes[3]),
        ]
        
        # Add 12 command bytes
        for cmd_byte in cmds:
            parts.append(str(cmd_byte))
        
        payload = ",".join(parts).encode("utf-8")
        return payload


@dataclass
class StatusPacket:
    """Represents a status update packet received from a SUN node."""
    
    node: int
    voltage: float
    charge: int
    actual_command: int
    actual_parameter: int
    timestamp: float
    
    @staticmethod
    def from_wire_payload(data: bytes) -> StatusPacket | None:
        """
        Parse incoming status packet.
        Expected format: node,voltage,charge,actual_command,actual_parameter
        """
        try:
            text = data.decode('utf-8', errors='ignore').strip()
            if not text:
                return None
            
            parts = text.split(',')
            if len(parts) < 5:
                return None
            
            return StatusPacket(
                node=int(parts[0]),
                voltage=float(parts[1]),
                charge=int(parts[2]),
                actual_command=int(parts[3]),
                actual_parameter=int(parts[4]),
                timestamp=time.time(),
            )
        except (ValueError, IndexError):
            return None
