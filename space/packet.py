"""Binary packet serialization for BEAM protocol v2.0."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional

# Packet type constants
TYPE_COMMAND = 0x01
TYPE_STATUS = 0x02
TYPE_ACK = 0x03
TYPE_HEARTBEAT = 0x04

# Total packet size (ESP-NOW maximum)
PACKET_SIZE = 250


@dataclass
class CommandPacket:
    """Command packet sent to SUN nodes (250 bytes, binary format)."""

    node_id: int
    ttl: int = 3
    command: int = 0
    parameter: int = 0
    constant_commands: bytes = field(default_factory=lambda: bytes(12))
    global_timestamp_ms: Optional[int] = None
    cmd_timestamp_ms: int = 0
    flags: int = 0

    def to_bytes(self) -> bytes:
        """
        Serialize to 250-byte binary packet.
        
        Format:
        [0]     packet_type (0x01)
        [1]     node_id (1-255)
        [2]     ttl (1-12)
        [3-6]   global_timestamp_ms (uint32_le)
        [7-10]  cmd_timestamp_ms (uint32_le)
        [11]    command (0-255)
        [12]    parameter (0-255)
        [13-24] constant_commands[12]
        [25]    flags
        [26-199] future_payload (174 bytes)
        [200-249] reserved (50 bytes)
        """
        packet = bytearray(PACKET_SIZE)
        
        # Header
        packet[0] = TYPE_COMMAND
        packet[1] = self.node_id & 0xFF
        packet[2] = self.ttl & 0xFF
        
        # Timestamps (uint32 little-endian)
        if self.global_timestamp_ms is None:
            self.global_timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFF
        
        struct.pack_into('<I', packet, 3, self.global_timestamp_ms & 0xFFFFFFFF)
        struct.pack_into('<I', packet, 7, self.cmd_timestamp_ms & 0xFFFFFFFF)
        
        packet[11] = self.command & 0xFF
        packet[12] = self.parameter & 0xFF
        
        # Constant commands (12 bytes)
        cmds = bytearray(12)
        if self.constant_commands:
            for i, byte in enumerate(self.constant_commands[:12]):
                cmds[i] = byte & 0xFF
        packet[13:25] = bytes(cmds)
        
        packet[25] = self.flags & 0xFF
        
        # Rest is zeros (already initialized)
        return bytes(packet)

    @staticmethod
    def from_bytes(data: bytes) -> CommandPacket | None:
        """Parse a 250-byte binary command packet."""
        if len(data) < 25 or data[0] != TYPE_COMMAND:
            return None
        
        try:
            global_ts = struct.unpack_from('<I', data, 3)[0]
            cmd_ts = struct.unpack_from('<I', data, 7)[0]
            
            return CommandPacket(
                node_id=data[1],
                ttl=data[2],
                global_timestamp_ms=global_ts,
                cmd_timestamp_ms=cmd_ts,
                command=data[11],
                parameter=data[12],
                constant_commands=bytes(data[13:25]),
                flags=data[25]
            )
        except (struct.error, IndexError):
            return None


@dataclass
class Subnode:
    """Status of a subnode (e.g., sub-controller or module)."""
    
    node_id: int
    voltage_mv: int
    charge_percent: int


@dataclass
class StatusPacket:
    """Status packet from SUN nodes (250 bytes, binary format)."""

    node_id: int
    ttl: int = 0
    command: int = 0
    parameter: int = 0
    constant_commands: bytes = field(default_factory=lambda: bytes(12))
    voltage_mv: int = 0
    charge_percent: int = 0
    global_timestamp_ms: Optional[int] = None
    cmd_timestamp_ms: int = 0
    subnodes: List[Subnode] = field(default_factory=list)

    def to_bytes(self) -> bytes:
        """
        Serialize to 250-byte binary status packet.
        
        Format:
        [0]     packet_type (0x02)
        [1]     node_id (1-255)
        [2]     ttl (1-12)
        [3-6]   global_timestamp_ms (uint32_le)
        [7-10]  cmd_timestamp_ms (uint32_le)
        [11]    command (0-255)
        [12]    parameter (0-255)
        [13-24] constant_commands[12]
        [25-26] voltage_mv (uint16_le, millivolts)
        [27]    charge_percent (0-100%)
        [28-91] subnodes array (8 slots × 8 bytes)
        [92-249] reserved (158 bytes)
        """
        packet = bytearray(PACKET_SIZE)
        
        # Header
        packet[0] = TYPE_STATUS
        packet[1] = self.node_id & 0xFF
        packet[2] = self.ttl & 0xFF
        
        # Timestamps
        if self.global_timestamp_ms is None:
            self.global_timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFF
        
        struct.pack_into('<I', packet, 3, self.global_timestamp_ms & 0xFFFFFFFF)
        struct.pack_into('<I', packet, 7, self.cmd_timestamp_ms & 0xFFFFFFFF)
        
        packet[11] = self.command & 0xFF
        packet[12] = self.parameter & 0xFF
        
        # Constant commands
        cmds = bytearray(12)
        if self.constant_commands:
            for i, byte in enumerate(self.constant_commands[:12]):
                cmds[i] = byte & 0xFF
        packet[13:25] = bytes(cmds)
        
        # Voltage and charge
        struct.pack_into('<H', packet, 25, self.voltage_mv & 0xFFFF)
        packet[27] = self.charge_percent & 0xFF
        
        # Subnodes (up to 8, 8 bytes each)
        for i, subnode in enumerate(self.subnodes[:8]):
            offset = 28 + (i * 8)
            packet[offset] = subnode.node_id & 0xFF
            struct.pack_into('<H', packet, offset + 1, subnode.voltage_mv & 0xFFFF)
            packet[offset + 3] = subnode.charge_percent & 0xFF
            # bytes [offset+4:offset+8] are reserved (already zeros)
        
        return bytes(packet)

    @staticmethod
    def from_bytes(data: bytes) -> StatusPacket | None:
        """Parse a 250-byte binary status packet."""
        if len(data) < 28 or data[0] != TYPE_STATUS:
            return None
        
        try:
            global_ts = struct.unpack_from('<I', data, 3)[0]
            cmd_ts = struct.unpack_from('<I', data, 7)[0]
            voltage = struct.unpack_from('<H', data, 25)[0]
            
            # Parse subnodes
            subnodes = []
            for i in range(8):
                offset = 28 + (i * 8)
                subnode_id = data[offset]
                if subnode_id > 0:  # 0 = unused slot
                    subnode_voltage = struct.unpack_from('<H', data, offset + 1)[0]
                    subnode_charge = data[offset + 3]
                    subnodes.append(Subnode(
                        node_id=subnode_id,
                        voltage_mv=subnode_voltage,
                        charge_percent=subnode_charge
                    ))
            
            return StatusPacket(
                node_id=data[1],
                ttl=data[2],
                global_timestamp_ms=global_ts,
                cmd_timestamp_ms=cmd_ts,
                command=data[11],
                parameter=data[12],
                constant_commands=bytes(data[13:25]),
                voltage_mv=voltage,
                charge_percent=data[27],
                subnodes=subnodes
            )
        except (struct.error, IndexError):
            return None


# Convenience functions for converting voltage
def voltage_to_mv(volts: float) -> int:
    """Convert voltage float to millivolts (uint16)."""
    return int(volts * 1000) & 0xFFFF


def mv_to_voltage(mv: int) -> float:
    """Convert millivolts to voltage float."""
    return mv / 1000.0
