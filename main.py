from __future__ import annotations

import json
import os
import re
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Optional

import mido
from PySide6 import QtCore, QtGui, QtWidgets

from space import config
from space.midi_input import MidiInput, list_input_ports
from space.node_registry import NodeRegistry, NodeState
from space.packet import CommandPacket, StatusPacket, extract_espnow_payload
from space.serial_link import SerialLink


def format_global_time(global_time_ms: int) -> str:
    """Format a millisecond global-time counter as HH:mm:ss."""
    seconds = (int(global_time_ms) // 1000) % (24 * 60 * 60)
    hours, seconds = divmod(seconds, 60 * 60)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def parse_global_time(response: object) -> int | None:
    """Extract a millisecond global-time value from BEAM text or JSON."""
    if isinstance(response, dict):
        for key in ("globalTime", "global_time", "global_timestamp_ms"):
            value = response.get(key)
            if value is not None:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    return None
                return parsed if parsed >= 0 else None
        return None

    if isinstance(response, bool):
        return None
    if isinstance(response, int):
        return response if response >= 0 else None
    if not isinstance(response, str):
        return None

    text = response.strip()
    if text.isdecimal():
        return int(text)
    if text.startswith("{"):
        try:
            return parse_global_time(json.loads(text))
        except json.JSONDecodeError:
            return None
    match = re.fullmatch(r"(?:globalTime|global_time|global_timestamp_ms)\s*[:=,]\s*(\d+)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def beam_indicator_state(
    running: bool,
    serial_open: bool,
    opened_at: float | None,
    received_at: float | None,
    now: float,
) -> str:
    """Show whether BEAM packets have reached SPACE within the last second."""
    if not running or not serial_open:
        return "stopped"
    reference_time = received_at if received_at is not None else opened_at
    if reference_time is None:
        return "stopped"
    if now - reference_time >= 1.0:
        return "lost"
    return "connected" if received_at is not None else "starting"


def midi_channel_number(channel: int) -> int:
    """Return the user-facing MIDI channel number (1-16).

    mido stores MIDI channels as 0-15 internally. When we display or log
    channel numbers to users, we convert back to the standard 1-based MIDI
    numbering expected by musicians and DAWs.
    """
    return channel + 1


def usable_serial_ports(ports: list[str]) -> list[str]:
    """Remove macOS pseudo-ports that cannot connect to the BEAM board."""
    unused_names = ("/cu.debug-console", "/cu.wlan-debug", "/cu.bluetooth-incoming-port")
    return [port for port in ports if not port.lower().endswith(unused_names)]


def preferred_serial_port_index(ports: list[str]) -> int:
    """Prefer the known BEAM USB modem, then another USB serial device."""
    for index, port in enumerate(ports):
        if port.lower().endswith("/cu.usbmodem01"):
            return index
    for index, port in enumerate(ports):
        lowered = port.lower()
        if "usbmodem" in lowered or "usbserial" in lowered:
            return index
    return 0


def midi_to_packet(message: mido.Message, ttl: int = 3, node_id: int | None = None) -> CommandPacket | None:
    """Translate one MIDI message into a CommandPacket with TTL.

    When a specific target node is provided, that node is used; otherwise the
    legacy channel-to-node fallback keeps the original behavior for single-node
    routing scenarios.
    """
    target_node = node_id if node_id is not None else message.channel + 1
    if message.type == "note_on":
        return CommandPacket(
            node_id=target_node,
            ttl=ttl,
            command=message.note,
            parameter=message.velocity,
        )
    if message.type == "control_change":
        const_cmds = bytearray(12)
        const_cmds[0] = message.value
        return CommandPacket(
            node_id=target_node,
            ttl=ttl,
            constant_commands=bytes(const_cmds),
        )
    return None


def midi_to_packets(message: mido.Message, ttl: int = 3, node_registry: NodeRegistry | None = None) -> list[CommandPacket]:
    """Map a MIDI message to all target nodes that listen to that MIDI channel."""
    if node_registry is not None:
        targets = [node.number for node in node_registry.nodes_for_midi_channel(message.channel)]
        if targets:
            return [
                midi_to_packet(message, ttl=ttl, node_id=node_id)
                for node_id in targets
                if midi_to_packet(message, ttl=ttl, node_id=node_id) is not None
            ]

    packet = midi_to_packet(message, ttl=ttl)
    return [packet] if packet is not None else []


def midi_to_registry_update(message: mido.Message) -> tuple[int, int, int | None] | None:
    """Convert a MIDI message into the command and parameter shown for matching nodes."""
    if message.type == "note_on":
        return message.channel, message.note, message.velocity
    if message.type == "control_change":
        return message.channel, message.value, None
    return None


class BridgeWindow(QtWidgets.QWidget):
    """A desktop app that listens for MIDI and forwards it to an ESP32 over USB serial."""

    log_message = QtCore.Signal(str)
    midi_message_received = QtCore.Signal(object)
    serial_message_received = QtCore.Signal(bytes)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SPACE MIDI Bridge")
        self.resize(900, 700)
        self.setMinimumSize(760, 560)

        self.midi_input: Optional[MidiInput] = None
        self.serial_link: Optional[SerialLink] = None
        self.running = False
        self.start_time: Optional[float] = None
        self._beam_monitor_started_at: float | None = None
        self._beam_global_time_received_at: float | None = None
        self.settings_path = Path(__file__).with_name("node_settings.json")
        self.node_registry = NodeRegistry(initialize_default_nodes=False)
        self.node_registry.load_from_file(self.settings_path)

        self.log_message.connect(self._log)
        self.midi_message_received.connect(self._process_midi)
        self.serial_message_received.connect(self._on_esp_response)

        self._build_ui()
        self._beam_status_timer = QtCore.QTimer(self)
        self._beam_status_timer.setInterval(100)
        self._beam_status_timer.timeout.connect(self._refresh_beam_indicator)
        self._set_beam_indicator("stopped")
        self._populate_ports()
        self._refresh_node_view()

    def _build_ui(self) -> None:
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QtWidgets.QLabel("MIDI input"), 0, 0, QtCore.Qt.AlignLeft)
        self.midi_combo = QtWidgets.QComboBox()
        self.midi_combo.setEditable(False)
        layout.addWidget(self.midi_combo, 0, 1)

        layout.addWidget(QtWidgets.QLabel("Serial port"), 1, 0, QtCore.Qt.AlignLeft)
        self.serial_combo = QtWidgets.QComboBox()
        self.serial_combo.setEditable(False)
        layout.addWidget(self.serial_combo, 1, 1)

        # TTL Slider
        layout.addWidget(QtWidgets.QLabel("TTL (1-12)"), 2, 0, QtCore.Qt.AlignLeft)
        ttl_container = QtWidgets.QWidget()
        ttl_layout = QtWidgets.QHBoxLayout(ttl_container)
        ttl_layout.setContentsMargins(0, 0, 0, 0)
        ttl_layout.setSpacing(8)
        
        self.ttl_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.ttl_slider.setMinimum(1)
        self.ttl_slider.setMaximum(12)
        self.ttl_slider.setValue(3)
        self.ttl_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.ttl_slider.setTickInterval(1)
        ttl_layout.addWidget(self.ttl_slider)
        
        self.ttl_label = QtWidgets.QLabel("3")
        self.ttl_label.setMinimumWidth(20)
        self.ttl_slider.sliderMoved.connect(lambda v: self.ttl_label.setText(str(v)))
        self.ttl_slider.valueChanged.connect(lambda v: self.ttl_label.setText(str(v)))
        ttl_layout.addWidget(self.ttl_label)
        
        layout.addWidget(ttl_container, 2, 1)

        button_row = QtWidgets.QWidget()
        button_layout = QtWidgets.QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.clicked.connect(self.start_bridge)
        button_layout.addWidget(self.start_button)
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_bridge)
        button_layout.addWidget(self.stop_button)
        self.show_status_messages_checkbox = QtWidgets.QCheckBox("Show node status messages")
        self.show_status_messages_checkbox.setChecked(False)
        button_layout.addWidget(self.show_status_messages_checkbox)
        self.beam_indicator = QtWidgets.QLabel()
        self.beam_indicator.setFixedSize(12, 12)
        self.beam_indicator.setAccessibleName("BEAM communication status")
        self.beam_time_label = QtWidgets.QLabel("--:--:--")
        self.beam_time_label.setMinimumWidth(68)
        self.beam_time_label.setAlignment(QtCore.Qt.AlignCenter)
        self.beam_time_label.setToolTip("Latest global time received from BEAM")
        button_layout.addWidget(self.beam_indicator)
        button_layout.addWidget(self.beam_time_label)
        layout.addWidget(button_row, 3, 0, 1, 2, QtCore.Qt.AlignLeft)

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(140)
        layout.addWidget(self.log_text, 4, 0, 1, 2)

        self.node_tree = QtWidgets.QTreeWidget()
        self.node_tree.setColumnCount(9)
        self.node_tree.setHeaderLabels([
            "Node",
            "Name",
            "Address",
            "Cmd",
            "Actual Cmd",
            "Param",
            "Actual Param",
            "Voltage",
            "Charge",
        ])
        self.node_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.node_tree.setAlternatingRowColors(True)
        self.node_tree.itemSelectionChanged.connect(self._on_node_selected)
        self.node_tree.header().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.node_tree, 5, 0, 1, 2)

        self.channel_panel = QtWidgets.QGroupBox("Node channels")
        channel_layout = QtWidgets.QGridLayout()
        self.channel_vars: list[QtWidgets.QCheckBox] = []
        for index in range(16):
            checkbox = QtWidgets.QCheckBox(f"Ch {index + 1}")
            checkbox.toggled.connect(self._save_selected_node_channels)
            self.channel_vars.append(checkbox)
            channel_layout.addWidget(checkbox, index // 8, index % 8)
        self.channel_panel.setLayout(channel_layout)
        layout.addWidget(self.channel_panel, 6, 0, 1, 2)

        layout.setRowStretch(4, 1)
        layout.setRowStretch(5, 2)
        layout.setRowStretch(6, 1)
        layout.setColumnStretch(1, 1)

    def _populate_ports(self) -> None:
        midi_ports = list_input_ports()
        serial_ports = usable_serial_ports(SerialLink.list_ports())

        self.midi_combo.clear()
        self.serial_combo.clear()

        self.midi_combo.addItems(midi_ports or ["(no MIDI ports)"])
        self.serial_combo.addItems(serial_ports or ["(no serial ports)"])

        if midi_ports:
            self.midi_combo.setCurrentIndex(0)
        if serial_ports:
            self.serial_combo.setCurrentIndex(preferred_serial_port_index(serial_ports))

    def _refresh_node_view(self) -> None:
        self.node_tree.clear()
        for node in self.node_registry.recent_nodes(max_age_seconds=60):
            item = QtWidgets.QTreeWidgetItem(
                [
                    str(node.number),
                    node.name,
                    node.address,
                    str(node.command),
                    str(node.actual_command),
                    str(node.parameter),
                    str(node.actual_parameter),
                    str(node.voltage),
                    str(node.charge),
                ]
            )
            self.node_tree.addTopLevelItem(item)

    def _on_node_selected(self) -> None:
        selected_node = self._get_selected_node()
        if selected_node is None:
            return
        for index, checkbox in enumerate(self.channel_vars):
            checkbox.blockSignals(True)
            checkbox.setChecked(selected_node.listen_channels[index])
            checkbox.blockSignals(False)

    def _save_selected_node_channels(self) -> None:
        selected_node = self._get_selected_node()
        if selected_node is None:
            return
        selected_node.listen_channels = [checkbox.isChecked() for checkbox in self.channel_vars]
        self.node_registry.save_to_file(self.settings_path)
        self._refresh_node_view()

    def _get_selected_node(self) -> NodeState | None:
        items = self.node_tree.selectedItems()
        if not items:
            return None
        node_number = int(items[0].text(0))
        return next((candidate for candidate in self.node_registry.nodes if candidate.number == node_number), None)

    def _log(self, message: str) -> None:
        self.log_text.append(message)

    def _schedule_log(self, message: str) -> None:
        self.log_message.emit(message)

    def _on_midi_message(self, message: mido.Message) -> None:
        self.midi_message_received.emit(message)

    def _queue_serial_response(self, data: bytes) -> None:
        """Post serial traffic back to the main GUI thread for safe UI updates."""
        self.serial_message_received.emit(data)

    def _set_beam_indicator(self, state: str) -> None:
        colors = {
            "stopped": ("#858585", "Bridge stopped"),
            "starting": ("#858585", "USB port open; waiting for the first BEAM packet"),
            "connected": ("#2e9b50", "BEAM packet received by SPACE within the last second"),
            "lost": ("#d64545", "No BEAM packet received by SPACE for at least one second"),
        }
        color, description = colors[state]
        self.beam_indicator.setStyleSheet(
            f"QLabel {{ background-color: {color}; border: 1px solid {color}; border-radius: 6px; }}"
        )
        self.beam_indicator.setToolTip(description)

    def _refresh_beam_indicator(self) -> None:
        serial_open = self.serial_link is not None and self.serial_link.is_open()
        self._set_beam_indicator(
            beam_indicator_state(
                running=self.running,
                serial_open=serial_open,
                opened_at=self._beam_monitor_started_at,
                received_at=self._beam_global_time_received_at,
                now=time.monotonic(),
            )
        )

    def _update_beam_global_time(self, global_time_ms: int) -> None:
        if global_time_ms < 0:
            return
        self.beam_time_label.setText(format_global_time(global_time_ms))
        self._beam_global_time_received_at = time.monotonic()
        self._refresh_beam_indicator()

    def _process_midi(self, message: mido.Message) -> None:
        ttl = self.ttl_slider.value()
        update = midi_to_registry_update(message)
        if update is not None:
            channel, command, parameter = update
            self.node_registry.apply_midi_message(channel=channel, command=command, parameter=parameter)
            self._refresh_node_view()
            self._schedule_log(
                f"MIDI {message.type} -> channel {midi_channel_number(channel)} "
                f"cmd {command} param {parameter}"
            )

        packets = midi_to_packets(message, ttl, self.node_registry)
        if packets and self.serial_link is None:
            self._schedule_log("MIDI packet not sent: serial link is unavailable.")
            return
        for packet in packets:
            try:
                self.serial_link.send(packet)
            except Exception as exc:
                self._schedule_log(f"MIDI packet not sent: {exc}")

    def _get_elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds since bridge start."""
        if self.start_time is None:
            return 0
        return int((time.time() - self.start_time) * 1000)

    def start_bridge(self) -> None:
        if self.running:
            return

        self.start_time = time.time()
        self._beam_monitor_started_at = None
        self._beam_global_time_received_at = None
        self._beam_status_timer.start()
        self._refresh_beam_indicator()
        self._log("Starting bridge...")
        self.running = True
        self.start_button.setEnabled(False)

        midi_port = self.midi_combo.currentText()
        serial_port = self.serial_combo.currentText()
        if midi_port in {"", "(no MIDI ports)"}:
            midi_port = None
            self._log(
                "No MIDI input ports were detected. Install the RTMidi backend or use a MIDI device that exposes an input port."
            )
        if serial_port in {"", "(no serial ports)"}:
            serial_port = None

        self.serial_link = SerialLink(serial_port, config.BAUD_RATE)
        self.serial_link.on_packet = self._on_status_packet
        self.serial_link.on_receive = self._queue_serial_response
        try:
            self.serial_link.open()
            self._beam_monitor_started_at = time.monotonic()
            self._log("Serial link ready.")
            self._refresh_beam_indicator()
        except Exception as exc:
            self._log(f"Serial link unavailable: {exc}")
            self.serial_link = None
            self._beam_monitor_started_at = None

        # Route MIDI callbacks through the Qt signal to ensure thread-safety.
        # The MIDI callback may run on a background thread; emitting the
        # `midi_message_received` signal ensures `_process_midi` runs on the
        # Qt main thread and avoids interacting with UI objects from another
        # thread (which can cause crashes).
        self.midi_input = MidiInput(midi_port, self._on_midi_message)
        self.midi_input.open()
        self._log("Bridge running. Waiting for MIDI input...")

    def stop_bridge(self) -> None:
        if not self.running:
            return
        self.running = False
        self._beam_monitor_started_at = None
        self._beam_status_timer.stop()
        self._refresh_beam_indicator()
        self.start_button.setEnabled(True)
        if self.midi_input is not None:
            self.midi_input.close()
        if self.serial_link is not None:
            self.serial_link.close()
        self._log("Bridge stopped.")

    def _on_status_packet(self, packet: Packet) -> None:
        pass

    def _on_esp_response(self, data: bytes) -> None:
        """Handle responses from SUN nodes via BEAM."""
        try:
            payload = extract_espnow_payload(data)

            # Try to parse as a binary status packet first.
            status_packet = StatusPacket.from_bytes(payload)
            if status_packet is not None:
                self._update_beam_global_time(status_packet.global_timestamp_ms or 0)
                updated = self.node_registry.update_node_status(
                    node_number=status_packet.node_id,
                    voltage=status_packet.voltage_mv / 1000.0,
                    charge=status_packet.charge_percent,
                    actual_command=status_packet.command,
                    actual_parameter=status_packet.parameter,
                )
                if updated:
                    self._refresh_node_view()
                    if self.show_status_messages_checkbox.isChecked():
                        self._schedule_log(
                            f"Node {status_packet.node_id}: V={status_packet.voltage_mv/1000.0:.2f}V, "
                            f"Charge={status_packet.charge_percent}%, Cmd={status_packet.command}"
                        )
                return

            command_packet = CommandPacket.from_bytes(payload)
            if command_packet is not None:
                self._update_beam_global_time(command_packet.global_timestamp_ms or 0)
                self._schedule_log(
                    f"Node {command_packet.node_id}: command packet cmd={command_packet.command} "
                    f"param={command_packet.parameter} ttl={command_packet.ttl}"
                )
                return

            response_str = payload.decode('utf-8', errors='ignore').strip()
            if not response_str.startswith("{"):
                text_global_time = parse_global_time(response_str)
                if text_global_time is not None:
                    self._update_beam_global_time(text_global_time)
                    return

            try:
                response = json.loads(response_str)

                json_global_time = parse_global_time(response)
                if json_global_time is not None:
                    self._update_beam_global_time(json_global_time)

                if isinstance(response, dict) and response.get("type") == "ack":
                    node = response.get("node", "?")
                    status = response.get("status", "?")
                    self._schedule_log(f"Node {node}: ACK ({status})")

                elif isinstance(response, dict) and response.get("type") == "status":
                    node = response.get("node", "?")
                    voltage = response.get("voltage", "?")
                    charge = response.get("charge", "?")
                    if self.show_status_messages_checkbox.isChecked():
                        self._schedule_log(f"Node {node}: Voltage={voltage}V, Charge={charge}%")
                    self.node_registry.update_node_status(node, voltage, charge)
                    self._refresh_node_view()

                else:
                    if json_global_time is None:
                        self._schedule_log(f"Response: {response_str}")

            except json.JSONDecodeError:
                if response_str:
                    self._schedule_log(f"Response: {response_str}")

        except Exception as exc:
            print(f"Error processing response: {exc}")


BridgeApp = BridgeWindow


def main() -> None:
    app = QtWidgets.QApplication([])
    if sys.platform == "darwin":
        app.setStyle("macintosh")
    else:
        app.setStyle("Fusion")
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#f2f2f2"))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#f2f2f2"))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#1d1d1f"))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#e8e8ec"))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#1d1d1f"))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#007aff"))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        app.setPalette(palette)

    app.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)

    font = QtGui.QFont()
    font.setFamily("SF Pro Text,Segoe UI,Helvetica Neue,Arial,sans-serif")
    font.setPointSize(10)
    app.setFont(font)

    app.setStyleSheet(
        """
        QWidget {
            font-family: Segoe UI, Arial, sans-serif;
            font-size: 9pt;
        }
        QPushButton, QComboBox, QTextEdit, QTreeWidget, QGroupBox, QCheckBox {
            font-family: Segoe UI, Arial, sans-serif;
        }
        """
    )

    window = BridgeWindow()
    window.setObjectName("BridgeWindow")
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
