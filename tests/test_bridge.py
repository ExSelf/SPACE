import mido

from main import midi_to_packet
from space.packet import Packet, TYPE_COMMAND


def test_note_on_becomes_command_packet() -> None:
    message = mido.Message("note_on", channel=2, note=64, velocity=100)

    packet = midi_to_packet(message)

    assert packet is not None
    assert packet.type == TYPE_COMMAND
    assert packet.node == 3
    assert packet.command == 64
    assert packet.parameter == 100


def test_control_change_becomes_constant_packet() -> None:
    message = mido.Message("control_change", channel=1, value=35)

    packet = midi_to_packet(message)

    assert packet is not None
    assert packet.node == 2
    assert packet.constant_commands is not None
    assert packet.constant_commands[0] == 35


def test_packet_serializes_to_wire_payload() -> None:
    packet = Packet(type=TYPE_COMMAND, node=1, command=12, parameter=90)

    payload = packet.to_wire_payload()

    assert payload.startswith(b'{"type":"command"')
    assert b'"node":1' in payload
    assert b'"command":12' in payload
    assert b'"parameter":90' in payload
