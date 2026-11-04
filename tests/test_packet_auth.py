from __future__ import annotations

import hashlib
import hmac

import pytest

from space.packet import (
    AUTHENTICATED_SIZE,
    PACKET_SIZE,
    CommandPacket,
    StatusPacket,
    get_packet_hmac_key,
)
from space.serial_link import SerialLink, extract_status_frames


def test_command_packet_uses_sun_compatible_hmac() -> None:
    packet = CommandPacket(
        node_id=14,
        ttl=3,
        command=21,
        parameter=10,
        cmd_timestamp_ms=0x12345678,
    ).to_bytes()
    expected_tag = hmac.new(
        get_packet_hmac_key(),
        packet[:AUTHENTICATED_SIZE],
        hashlib.sha256,
    ).digest()[:8]

    assert len(packet) == PACKET_SIZE
    assert packet[AUTHENTICATED_SIZE:] == expected_tag
    assert CommandPacket.from_bytes(packet) is not None


def test_packet_parser_rejects_modified_authenticated_data() -> None:
    packet = bytearray(StatusPacket(node_id=14, ttl=3).to_bytes())
    packet[11] ^= 1

    assert StatusPacket.from_bytes(bytes(packet)) is None


def test_serial_receiver_extracts_hmac_packet_containing_newline_bytes() -> None:
    packet = StatusPacket(node_id=14, ttl=3, parameter=0x0A).to_bytes()
    buffer = bytearray(packet[:73])

    assert extract_status_frames(buffer) == []
    buffer.extend(packet[73:])

    assert extract_status_frames(buffer) == [packet]
    assert buffer == b""


def test_serial_sender_writes_only_the_authenticated_frame() -> None:
    from unittest.mock import Mock

    link = SerialLink("/dev/test", 115200)
    link._serial = Mock(is_open=True)
    link._serial.write.return_value = PACKET_SIZE
    packet = CommandPacket(node_id=14, ttl=3)

    link.send(packet)

    link._serial.write.assert_called_once_with(packet.to_bytes())


def test_shared_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUN_PACKET_HMAC_KEY")
    with pytest.raises(RuntimeError, match="Set SUN_PACKET_HMAC_KEY"):
        get_packet_hmac_key()
