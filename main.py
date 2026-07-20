from __future__ import annotations

import time

import mido

from space import config
from space.midi_input import MidiInput, list_input_ports
from space.packet import Packet, TYPE_COMMAND
from space.serial_link import SerialLink


def midi_to_packet(message: mido.Message) -> Packet | None:
    """
    Translate one MIDI message into a command Packet.

    Placeholder mapping -- replace with whatever makes sense for your
    show once you've decided how nodes/channels map to MIDI:

      note_on/note_off channel -> node number (1-16)
      note number              -> command
      velocity                 -> parameter
      control_change            -> parameter update on constant_commands[0]
    """
    if message.type in ("note_on", "note_off"):
        node = message.channel + 1
        return Packet(
            type=TYPE_COMMAND,
            node=node,
            command=message.note,
            parameter=message.velocity if message.type == "note_on" else 0,
        )
    if message.type == "control_change":
        node = message.channel + 1
        const_cmds = bytearray(12)
        const_cmds[0] = message.value
        return Packet(
            type=TYPE_COMMAND,
            node=node,
            constant_commands=bytes(const_cmds),
        )
    return None


def on_status_packet(packet: Packet) -> None:
    print(
        f"[status] node={packet.node} voltage={packet.voltage} "
        f"charge={packet.charge}% ttl={packet.ttl}"
    )


def main() -> None:
    print("Available MIDI inputs:", list_input_ports())
    print("Available serial ports:", SerialLink.list_ports())

    link = SerialLink(config.SERIAL_PORT, config.BAUD_RATE)
    link.on_packet = on_status_packet
    link.open()

    def handle_midi(message: mido.Message) -> None:
        packet = midi_to_packet(message)
        if packet is not None:
            link.send(packet)

    midi = MidiInput(config.MIDI_PORT_NAME, handle_midi)
    midi.open()

    print("Bridge running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        midi.close()
        link.close()


if __name__ == "__main__":
    main()