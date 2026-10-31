from __future__ import annotations

from unittest.mock import Mock, patch

import mido
import pytest

import main
import space.midi_input as midi_input
from space import packet as packet_module
from space.node_registry import NodeRegistry, NodeState
from space.serial_link import SerialLink, extract_status_frames


class DummyButton:
    def __init__(self) -> None:
        self.state = None

    def config(self, **kwargs) -> None:
        self.state = kwargs.get("state")

    def setEnabled(self, enabled: bool) -> None:
        self.state = enabled


class DummyVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class DummyCombo:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def currentText(self) -> str:
        return self.value


def test_list_input_ports_uses_windows_fallback_when_mido_is_unavailable() -> None:
    with patch("space.midi_input.platform.system", return_value="Windows"), patch(
        "space.midi_input._enumerate_windows_input_ports", return_value=["Microsoft GS Wavetable Synth"]
    ):
        assert midi_input.list_input_ports() == ["Microsoft GS Wavetable Synth"]


def test_start_bridge_keeps_running_when_serial_open_fails() -> None:
    app = main.BridgeApp.__new__(main.BridgeApp)
    app.running = False
    app._beam_status_timer = Mock()
    app._refresh_beam_indicator = Mock()
    app.start_button = DummyButton()
    app.root = Mock()
    app.root.after = Mock()
    app.midi_input = None
    app.serial_link = None
    app.midi_combo = DummyCombo("(no MIDI ports)")
    app.serial_combo = DummyCombo("(no serial ports)")
    app.log_text = Mock()

    def fake_log(message: str) -> None:
        return None

    app._log = fake_log
    app._schedule_log = fake_log

    with patch("main.SerialLink") as serial_cls, patch("main.MidiInput") as midi_cls:
        serial_instance = serial_cls.return_value
        serial_instance.open.side_effect = RuntimeError("No serial ports detected")
        midi_instance = midi_cls.return_value

        app.start_bridge()

    assert app.running is True
    assert app.midi_input is midi_instance
    assert app.serial_link is None


def test_midi_channel_numbering_uses_human_facing_channel_labels() -> None:
    message = mido.Message("note_on", channel=5, note=60, velocity=64)

    assert main.midi_channel_number(message.channel) == 6
    assert main.midi_to_registry_update(message) == (5, 60, 64)


def test_control_change_shows_its_value_as_the_command() -> None:
    message = mido.Message("control_change", channel=5, control=64, value=127)

    assert main.midi_to_registry_update(message) == (5, 127, None)
    packet = main.midi_to_packet(message, node_id=6)
    assert packet is not None
    assert packet.command == 0
    assert packet.parameter == 0
    assert packet.constant_commands[0] == 127


def test_midi_packets_target_recent_nodes_not_channel_assignments() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    offline_assigned = NodeState(
        number=3,
        name="Offline",
        address="0x03",
        listen_channels=[False] * 13 + [True] + [False] * 2,
    )
    online = NodeState(number=255, name="Online", address="0xff")
    registry.add_node(offline_assigned)
    registry.add_node(online)
    registry.update_node_status(node_number=255)

    packets = main.midi_to_packets(
        mido.Message("note_on", channel=13, note=60, velocity=100),
        node_registry=registry,
    )

    assert [packet.node_id for packet in packets] == [255]


def test_midi_packets_do_not_fall_back_to_channel_node_when_none_are_online() -> None:
    registry = NodeRegistry(initialize_default_nodes=True)

    packets = main.midi_to_packets(
        mido.Message("note_on", channel=13, note=60, velocity=100),
        node_registry=registry,
    )

    assert packets == []


def test_process_midi_logs_serial_send_failure() -> None:
    app = main.BridgeApp.__new__(main.BridgeApp)
    app.ttl_slider = Mock()
    app.ttl_slider.value.return_value = 3
    app.node_registry = Mock()
    app.node_registry.recent_nodes.return_value = [NodeState(number=1, name="Node 1", address="0x01")]
    app.serial_link = Mock()
    app.serial_link.send.side_effect = AttributeError("to_wire_payload is unavailable")
    app._refresh_node_view = Mock()
    app._schedule_log = Mock()

    app._process_midi(mido.Message("note_on", channel=13, note=21, velocity=122))

    assert any(
        "MIDI packet not sent: to_wire_payload is unavailable" in call.args[0]
        for call in app._schedule_log.call_args_list
    )


def test_process_midi_updates_the_online_node_after_successful_send() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    node = NodeState(number=255, name="Node 255", address="0xff")
    registry.add_node(node)
    registry.update_node_status(node_number=255)
    app = main.BridgeApp.__new__(main.BridgeApp)
    app.ttl_slider = Mock()
    app.ttl_slider.value.return_value = 3
    app.node_registry = registry
    app.serial_link = Mock()
    app._refresh_node_view = Mock()
    app._schedule_log = Mock()

    app._process_midi(mido.Message("note_on", channel=13, note=60, velocity=100))

    assert node.command == 60
    assert node.parameter == 100
    app.serial_link.send.assert_called_once()
    assert app.serial_link.send.call_args.args[0].node_id == 255
    app._refresh_node_view.assert_called_once()


def test_serial_link_sends_binary_packet_with_beam_line_terminator() -> None:
    link = SerialLink("/dev/cu.usbmodem01", 115200)
    link._serial = Mock(is_open=True)
    packet = packet_module.CommandPacket(
        node_id=14,
        ttl=3,
        command=21,
        parameter=122,
        global_timestamp_ms=0x12345678,
    )

    link.send(packet)

    link._serial.write.assert_called_once_with(packet.to_bytes() + b"\n")
    link._serial.flush.assert_called_once_with()


def test_serial_link_rejects_binary_packet_containing_beam_line_delimiter() -> None:
    link = SerialLink("/dev/cu.usbmodem01", 115200)
    link._serial = Mock(is_open=True)
    packet = packet_module.CommandPacket(
        node_id=14,
        ttl=3,
        command=21,
        parameter=10,
        global_timestamp_ms=0x12345678,
    )

    with pytest.raises(ValueError, match="cannot carry a packet containing a newline byte"):
        link.send(packet)

    link._serial.write.assert_not_called()


def test_serial_port_selection_prefers_usb_device_over_macos_pseudo_ports() -> None:
    ports = [
        "/dev/cu.debug-console",
        "/dev/cu.wlan-debug",
        "/dev/cu.Bluetooth-Incoming-Port",
        "/dev/cu.usbmodem01",
    ]

    usable_ports = main.usable_serial_ports(ports)
    assert usable_ports == ["/dev/cu.usbmodem01"]
    assert main.preferred_serial_port_index(usable_ports) == 0
    assert main.preferred_serial_port_index(["/dev/cu.usbmodem02", "/dev/cu.usbmodem01"]) == 1
    assert main.preferred_serial_port_index(["COM3", "COM4"]) == 0


def test_global_time_formats_milliseconds_as_hours_minutes_seconds() -> None:
    assert main.format_global_time(3_723_000) == "01:02:03"
    assert main.format_global_time(86_401_000) == "00:00:01"


def test_global_time_parser_accepts_integer_json_and_firmware_text() -> None:
    assert main.parse_global_time(1234) == 1234
    assert main.parse_global_time('{"globalTime": 1234}') == 1234
    assert main.parse_global_time({"globalTime": 1234}) == 1234
    assert main.parse_global_time("globalTime:1234") == 1234
    assert main.parse_global_time("1234") == 1234


def test_beam_indicator_tracks_recent_updates_and_stops_grey() -> None:
    assert main.beam_indicator_state(False, False, None, None, 10.0) == "stopped"
    assert main.beam_indicator_state(True, False, 10.0, None, 10.5) == "stopped"
    assert main.beam_indicator_state(True, True, 10.0, None, 10.9) == "starting"
    assert main.beam_indicator_state(True, True, 10.0, None, 11.0) == "lost"
    assert main.beam_indicator_state(True, True, 10.0, 10.0, 10.9) == "connected"
    assert main.beam_indicator_state(True, True, 10.0, 10.0, 11.0) == "lost"


def test_start_bridge_routes_serial_responses_to_gui_thread() -> None:
    app = main.BridgeApp.__new__(main.BridgeApp)
    app.running = False
    app._beam_status_timer = Mock()
    app._refresh_beam_indicator = Mock()
    app.start_button = DummyButton()
    app.midi_input = None
    app.serial_link = None
    app.midi_combo = DummyCombo("(no MIDI ports)")
    app.serial_combo = DummyCombo("(no serial ports)")
    app.log_text = Mock()
    app._log = Mock()
    app._schedule_log = Mock()
    app._refresh_node_view = Mock()
    app.serial_message_received = Mock()

    with patch("main.SerialLink") as serial_cls, patch("main.MidiInput") as midi_cls:
        serial_instance = serial_cls.return_value
        serial_instance.on_receive = None
        midi_instance = midi_cls.return_value

        app.start_bridge()

    assert callable(app.serial_link.on_receive)
    assert app.serial_link.on_receive.__name__ == "_queue_serial_response"
    assert app.serial_link.on_receive.__self__ is app
    assert app.serial_link is not None
    assert app.midi_input is midi_instance


def test_espnow_messages_strip_the_text_prefix_before_parsing() -> None:
    packet = bytearray(250)
    packet[0] = 0x02
    packet[1] = 0x03
    packet[2] = 0x03
    packet[25:27] = (3300).to_bytes(2, byteorder="little")
    packet[27] = 0x50

    raw = b"ESP_NOW_FROM 48:F6:EE:70:43:50 " + bytes(packet) + b"\n"

    extracted = packet_module.extract_espnow_payload(raw)

    assert extracted == bytes(packet)
    parsed = packet_module.StatusPacket.from_bytes(extracted)
    assert parsed is not None
    assert parsed.node_id == 3
    assert parsed.voltage_mv == 3300
    assert parsed.charge_percent == 80

    command_packet = bytearray(250)
    command_packet[0] = 0x01
    command_packet[1] = 0x03
    command_packet[2] = 0x03
    command_packet[11] = 0x0A
    command_packet[12] = 0x20

    command_raw = b"ESP_NOW_FROM 48:F6:EE:70:43:50 " + bytes(command_packet) + b"\n"
    command_parsed = packet_module.CommandPacket.from_bytes(packet_module.extract_espnow_payload(command_raw))
    assert command_parsed is not None
    assert command_parsed.node_id == 3
    assert command_parsed.command == 0x0A
    assert command_parsed.parameter == 0x20


@pytest.mark.parametrize("show_status_messages", [False, True])
def test_status_packet_log_is_controlled_by_checkbox(show_status_messages: bool) -> None:
    app = main.BridgeApp.__new__(main.BridgeApp)
    app.show_status_messages_checkbox = Mock()
    app.show_status_messages_checkbox.isChecked.return_value = show_status_messages
    app._update_beam_global_time = Mock()
    app.node_registry = Mock()
    app.node_registry.update_node_status.return_value = True
    app._refresh_node_view = Mock()
    app._schedule_log = Mock()
    packet = packet_module.StatusPacket(
        node_id=255,
        voltage_mv=0,
        charge_percent=0,
        command=12,
        global_timestamp_ms=1234,
    )

    app._on_esp_response(packet.to_bytes())

    app.node_registry.update_node_status.assert_called_once()
    app._refresh_node_view.assert_called_once()
    if show_status_messages:
        app._schedule_log.assert_called_once_with("Node 255: V=0.00V, Charge=0%, Cmd=12")
    else:
        app._schedule_log.assert_not_called()


def test_beam_binary_serial_stream_frames_partial_packets_without_newline_splitting() -> None:
    first = bytearray(250)
    first[0] = packet_module.TYPE_STATUS
    first[1] = 3
    first[2] = 3
    first[11] = 10
    first[12] = 0x0A

    second = bytearray(first)
    second[1] = 4
    buffer = bytearray()

    buffer.extend(first[:37])
    assert extract_status_frames(buffer) == []

    buffer.extend(first[37:] + second)
    assert extract_status_frames(buffer) == [bytes(first), bytes(second)]
    assert buffer == b""
