"""Binary packet serialization for the BEAM/SUN protocol."""

from __future__ import annotations

import configparser
import struct
import time
import hmac
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Packet type constants
TYPE_COMMAND = 0x01
TYPE_STATUS = 0x02
TYPE_ACK = 0x03
TYPE_HEARTBEAT = 0x04

# Total packet size (ESP-NOW maximum)
PACKET_SIZE = 250
TARGET_BITMAP_SIZE = 32
TARGET_BITMAP_OFFSET = 28
COMMAND_FLAGS_OFFSET = 25
CONSTANT_UPDATE_MASK_OFFSET = 26
AUTHENTICATED_SIZE = 242
AUTH_TAG_SIZE = 8
COMMAND_UPDATE_STATE = 0x01
COMMAND_UPDATE_CONSTANTS = 0x02
SECRETS_INI_PATH = Path(__file__).resolve().parent.parent / "secrets.ini"
HMAC_KEY_PLACEHOLDER = "REPLACE_WITH_SHARED_KEY_OF_AT_LEAST_32_CHARACTERS"


def _secrets_ini_path() -> Path:
    if not getattr(sys, "frozen", False):
        return SECRETS_INI_PATH

    executable_directory = Path(sys.executable).resolve().parent
    candidates = [directory / "secrets.ini" for directory in (executable_directory, *executable_directory.parents)]
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def get_packet_hmac_key() -> bytes:
    key = os.environ.get("SUN_PACKET_HMAC_KEY")
    if key is None:
        parser = configparser.ConfigParser(interpolation=None)
        secrets_path = _secrets_ini_path()
        if not secrets_path.is_file():
            raise RuntimeError(
                "Set SUN_PACKET_HMAC_KEY or configure it in secrets.ini before starting SPACE"
            )
        parser.read(secrets_path, encoding="utf-8")
        key = parser.get("security", "SUN_PACKET_HMAC_KEY", fallback=None)
    if key is None or key == HMAC_KEY_PLACEHOLDER:
        raise RuntimeError(
            "Replace the SUN_PACKET_HMAC_KEY placeholder in secrets.ini or set the environment variable"
        )
    key_bytes = key.encode("utf-8")
    if len(key_bytes) < 32:
        raise RuntimeError("SUN_PACKET_HMAC_KEY must be at least 32 bytes")
    return key_bytes


def _finalize_packet(packet: bytearray) -> bytes:
    packet[AUTHENTICATED_SIZE:] = hmac.new(
        get_packet_hmac_key(),
        packet[:AUTHENTICATED_SIZE],
        "sha256",
    ).digest()[:AUTH_TAG_SIZE]
    return bytes(packet)


def _valid_packet(data: bytes, packet_type: int) -> bool:
    if len(data) != PACKET_SIZE or data[0] != packet_type:
        return False
    expected_tag = hmac.new(
        get_packet_hmac_key(),
        data[:AUTHENTICATED_SIZE],
        "sha256",
    ).digest()[:AUTH_TAG_SIZE]
    return hmac.compare_digest(data[AUTHENTICATED_SIZE:], expected_tag)


def target_bitmap_for_nodes(node_ids: list[int]) -> bytes:
    """Pack node IDs 0-255 into a 256-bit little-endian bitmap."""
    bitmap = bytearray(TARGET_BITMAP_SIZE)
    for node_id in node_ids:
        if not 0 <= node_id <= 255:
            raise ValueError(f"Node ID must be between 0 and 255, got {node_id}")
        bitmap[node_id // 8] |= 1 << (node_id % 8)
    return bytes(bitmap)


def nodes_in_target_bitmap(bitmap: bytes) -> list[int]:
    """Return all node IDs selected by a 32-byte target bitmap."""
    if len(bitmap) != TARGET_BITMAP_SIZE:
        raise ValueError(f"Target bitmap must be {TARGET_BITMAP_SIZE} bytes")
    return [
        node_id
        for node_id in range(256)
        if bitmap[node_id // 8] & (1 << (node_id % 8))
    ]


@dataclass
class CommandPacket:
    """Command broadcast with a packed bitmap identifying its target nodes."""

    node_id: int = 0
    ttl: int = 3
    command: int = 0
    parameter: int = 0
    constant_commands: bytes = field(default_factory=lambda: bytes(12))
    target_bitmap: bytes = field(default_factory=lambda: bytes(TARGET_BITMAP_SIZE))
    global_timestamp_ms: Optional[int] = None
    cmd_timestamp_ms: int = 0
    flags: int = 0
    constant_update_mask: int = 0

    @property
    def target_nodes(self) -> list[int]:
        return nodes_in_target_bitmap(self.target_bitmap)

    def targets_node(self, node_id: int) -> bool:
        return bool(self.target_bitmap[node_id // 8] & (1 << (node_id % 8)))

    def to_bytes(self) -> bytes:
        """
        Serialize to 250-byte binary packet.
        
        Format:
        [0]     packet_type (0x01)
        [1]     source node (0 for SPACE)
        [2]     ttl (1-12)
        [3-6]   global_timestamp_ms (uint32_le)
        [7-10]  cmd_timestamp_ms (uint32_le)
        [11]    command (0-255)
        [12]    parameter (0-255)
        [13-24] constant_commands[12]
        [25]    command update flags
        [26-27] constant command update mask (uint16_le)
        [28-59] target bitmap (256 bits, bit N selects node N)
        [60-241] reserved
        [242-249] first 8 bytes of HMAC-SHA-256 over bytes 0-241
        """
        packet = bytearray(PACKET_SIZE)
        
        if len(self.target_bitmap) != TARGET_BITMAP_SIZE:
            raise ValueError(f"Target bitmap must be {TARGET_BITMAP_SIZE} bytes")

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
        
        packet[COMMAND_FLAGS_OFFSET] = self.flags & 0xFF
        struct.pack_into("<H", packet, CONSTANT_UPDATE_MASK_OFFSET, self.constant_update_mask & 0xFFFF)
        packet[TARGET_BITMAP_OFFSET:TARGET_BITMAP_OFFSET + TARGET_BITMAP_SIZE] = self.target_bitmap
        return _finalize_packet(packet)

    @staticmethod
    def from_bytes(data: bytes) -> CommandPacket | None:
        """Parse a complete, integrity-checked command packet."""
        if not _valid_packet(data, TYPE_COMMAND):
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
                flags=data[COMMAND_FLAGS_OFFSET],
                constant_update_mask=struct.unpack_from("<H", data, CONSTANT_UPDATE_MASK_OFFSET)[0],
                target_bitmap=bytes(data[TARGET_BITMAP_OFFSET:TARGET_BITMAP_OFFSET + TARGET_BITMAP_SIZE]),
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
        [28-59] unused target bitmap
        [60-241] reserved
        [242-249] first 8 bytes of HMAC-SHA-256 over bytes 0-241
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
        
        return _finalize_packet(packet)

    @staticmethod
    def from_bytes(data: bytes) -> StatusPacket | None:
        """Parse a complete, integrity-checked status packet."""
        if not _valid_packet(data, TYPE_STATUS):
            return None
        
        try:
            global_ts = struct.unpack_from('<I', data, 3)[0]
            cmd_ts = struct.unpack_from('<I', data, 7)[0]
            voltage = struct.unpack_from('<H', data, 25)[0]
            
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
            )
        except (struct.error, IndexError):
            return None


def extract_espnow_payload(data: bytes) -> bytes:
    """Strip the BEAM/ESP-NOW text prefix so the remaining bytes can be parsed as a binary packet."""
    if data is None:
        return b""

    frame = bytes(data)
    if not frame:
        return frame

    prefix = b"ESP_NOW_FROM"
    if frame.startswith(prefix):
        payload = frame[len(prefix):]
        payload = payload.lstrip(b" \t")
        if b" " in payload:
            payload = payload.split(b" ", 1)[1]
            payload = payload.lstrip(b" \t")
        if len(payload) == PACKET_SIZE + 2 and payload.endswith(b"\r\n"):
            return payload[:-2]
        if len(payload) == PACKET_SIZE + 1 and payload.endswith((b"\r", b"\n")):
            return payload[:-1]
        return payload

    return frame


# Convenience functions for converting voltage
def voltage_to_mv(volts: float) -> int:
    """Convert voltage float to millivolts (uint16)."""
    return int(volts * 1000) & 0xFFFF


def mv_to_voltage(mv: int) -> float:
    """Convert millivolts to voltage float."""
    return mv / 1000.0
