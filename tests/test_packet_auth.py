from __future__ import annotations

import hashlib
import hmac

import pytest

import space.packet as packet_module
from space.packet import (
    AUTHENTICATED_SIZE,
    PACKET_SIZE,
    CommandPacket,
    StatusPacket,
    get_packet_hmac_key,
    target_bitmap_for_nodes,
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


def test_command_packet_fields_match_current_sun_and_beam_layout() -> None:
    packet = CommandPacket(
        node_id=0,
        ttl=3,
        command=60,
        parameter=100,
        target_bitmap=target_bitmap_for_nodes([255]),
        global_timestamp_ms=0x01020304,
        cmd_timestamp_ms=0x11223344,
        flags=1,
    ).to_bytes()

    assert packet[0:3] == bytes((1, 0, 3))
    assert packet[3:7] == b"\x04\x03\x02\x01"
    assert packet[7:11] == b"\x44\x33\x22\x11"
    assert packet[11:13] == bytes((60, 100))
    assert packet[25:28] == b"\x01\x00\x00"
    assert packet[28:59] == bytes(31)
    assert packet[59] == 0x80
    assert CommandPacket.from_bytes(packet).target_nodes == [255]


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
    monkeypatch.setattr(packet_module, "SECRETS_INI_PATH", packet_module.SECRETS_INI_PATH.parent / "missing-secrets.ini")
    with pytest.raises(RuntimeError, match="Set SUN_PACKET_HMAC_KEY"):
        get_packet_hmac_key()


def test_packet_key_loads_from_secrets_ini_when_environment_is_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    key = "test-shared-key-with-%-characters-and-at-least-32-bytes"
    secrets_file = tmp_path / "secrets.ini"
    secrets_file.write_text(f"[security]\nSUN_PACKET_HMAC_KEY = {key}\n", encoding="utf-8")
    monkeypatch.delenv("SUN_PACKET_HMAC_KEY")
    monkeypatch.setattr(packet_module, "SECRETS_INI_PATH", secrets_file)

    assert get_packet_hmac_key() == key.encode("utf-8")


def test_packet_key_environment_value_takes_precedence_over_ini(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    secrets_file = tmp_path / "secrets.ini"
    secrets_file.write_text("[security]\nSUN_PACKET_HMAC_KEY = ini-key\n", encoding="utf-8")
    monkeypatch.setattr(packet_module, "SECRETS_INI_PATH", secrets_file)
    monkeypatch.setenv("SUN_PACKET_HMAC_KEY", "environment-key-with-at-least-32-bytes")

    assert get_packet_hmac_key() == b"environment-key-with-at-least-32-bytes"


def test_packet_key_rejects_unreplaced_ini_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    secrets_file = tmp_path / "secrets.ini"
    secrets_file.write_text(
        f"[security]\nSUN_PACKET_HMAC_KEY = {packet_module.HMAC_KEY_PLACEHOLDER}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SUN_PACKET_HMAC_KEY")
    monkeypatch.setattr(packet_module, "SECRETS_INI_PATH", secrets_file)

    with pytest.raises(RuntimeError, match="Replace the SUN_PACKET_HMAC_KEY placeholder"):
        get_packet_hmac_key()


def test_frozen_app_finds_secrets_ini_in_an_executable_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app_directory = tmp_path / "dist" / "SPACE.app" / "Contents" / "MacOS"
    app_directory.mkdir(parents=True)
    secrets_file = tmp_path / "secrets.ini"
    key = "test-shared-key-for-frozen-app-with-32-bytes"
    secrets_file.write_text(f"[security]\nSUN_PACKET_HMAC_KEY = {key}\n", encoding="utf-8")
    monkeypatch.delenv("SUN_PACKET_HMAC_KEY")
    monkeypatch.setattr(packet_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(packet_module.sys, "executable", str(app_directory / "SPACE"))

    assert get_packet_hmac_key() == key.encode("utf-8")
