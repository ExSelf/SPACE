from __future__ import annotations

import os
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
from space.packet import Packet, TYPE_COMMAND
from space.serial_link import SerialLink


def midi_to_packet(message: mido.Message) -> Packet | None:
    """Translate one MIDI message into a command Packet."""
    if message.type == "note_on":
        node = message.channel + 1
        return Packet(
            type=TYPE_COMMAND,
            node=node,
            command=message.note,
            parameter=message.velocity,
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


def midi_to_registry_update(message: mido.Message) -> tuple[int, int, int] | None:
    """Convert a MIDI message into the values applied to all matching nodes."""
    if message.type == "note_on":
        return message.channel, message.note, message.velocity
    if message.type == "control_change":
        return message.channel, message.control, message.value
    return None


class BridgeWindow(QtWidgets.QWidget):
    """A desktop app that listens for MIDI and forwards it to an ESP32 over USB serial."""

    log_message = QtCore.Signal(str)
    midi_message_received = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SPACE MIDI Bridge")
        self.resize(900, 700)
        self.setMinimumSize(760, 560)

        self.midi_input: Optional[MidiInput] = None
        self.serial_link: Optional[SerialLink] = None
        self.running = False
        self.start_time: Optional[float] = None
        self.settings_path = Path(__file__).with_name("node_settings.json")
        self.node_registry = NodeRegistry(initialize_default_nodes=False)
        self.node_registry.load_from_file(self.settings_path)

        self.log_message.connect(self._log)
        self.midi_message_received.connect(self._process_midi)

        self._build_ui()
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
        layout.addWidget(button_row, 2, 0, 1, 2, QtCore.Qt.AlignLeft)

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(140)
        layout.addWidget(self.log_text, 3, 0, 1, 2)

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
        layout.addWidget(self.node_tree, 4, 0, 1, 2)

        self.channel_panel = QtWidgets.QGroupBox("Node channels")
        channel_layout = QtWidgets.QGridLayout()
        self.channel_vars: list[QtWidgets.QCheckBox] = []
        for index in range(16):
            checkbox = QtWidgets.QCheckBox(f"Ch {index + 1}")
            checkbox.toggled.connect(self._save_selected_node_channels)
            self.channel_vars.append(checkbox)
            channel_layout.addWidget(checkbox, index // 8, index % 8)
        self.channel_panel.setLayout(channel_layout)
        layout.addWidget(self.channel_panel, 5, 0, 1, 2)

        layout.setRowStretch(3, 1)
        layout.setRowStretch(4, 2)
        layout.setRowStretch(5, 1)
        layout.setColumnStretch(1, 1)

    def _populate_ports(self) -> None:
        midi_ports = list_input_ports()
        serial_ports = SerialLink.list_ports()

        self.midi_combo.clear()
        self.serial_combo.clear()

        self.midi_combo.addItems(midi_ports or ["(no MIDI ports)"])
        self.serial_combo.addItems(serial_ports or ["(no serial ports)"])

        if midi_ports:
            self.midi_combo.setCurrentIndex(0)
        if serial_ports:
            self.serial_combo.setCurrentIndex(0)

    def _refresh_node_view(self) -> None:
        self.node_tree.clear()
        for node in self.node_registry.nodes:
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

    def _process_midi(self, message: mido.Message) -> None:
        packet = midi_to_packet(message)
        update = midi_to_registry_update(message)
        if update is not None:
            channel, command, parameter = update
            self.node_registry.apply_midi_message(channel=channel, command=command, parameter=parameter)
            self._refresh_node_view()
            self._schedule_log(f"MIDI {message.type} -> channel {channel} cmd {command} param {parameter}")
        if packet is not None and self.serial_link is not None:
            self.serial_link.send(packet)

    def _get_elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds since bridge start."""
        if self.start_time is None:
            return 0
        return int((time.time() - self.start_time) * 1000)

    def start_bridge(self) -> None:
        if self.running:
            return

        self.start_time = time.time()
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
        self.serial_link.on_receive = self._on_esp_response
        try:
            self.serial_link.open()
            self._log("Serial link ready.")
        except Exception as exc:
            self._log(f"Serial link unavailable: {exc}")
            self.serial_link = None

        def handle_midi(message: mido.Message) -> None:
            packet = midi_to_packet(message)
            update = midi_to_registry_update(message)
            if update is not None:
                channel, command, parameter = update
                self.node_registry.apply_midi_message(channel=channel, command=command, parameter=parameter)
                self._refresh_node_view()
                self._schedule_log(f"MIDI {message.type} -> channel {channel} cmd {command} param {parameter}")
            if packet is not None:
                if self.serial_link is not None:
                    self.serial_link.send(packet)

        self.midi_input = MidiInput(midi_port, handle_midi)
        self.midi_input.open()
        self._log("Bridge running. Waiting for MIDI input...")

    def stop_bridge(self) -> None:
        if not self.running:
            return
        self.running = False
        self.start_button.setEnabled(True)
        if self.midi_input is not None:
            self.midi_input.close()
        if self.serial_link is not None:
            self.serial_link.close()
        self._log("Bridge stopped.")

    def _on_status_packet(self, packet: Packet) -> None:
        pass

    def _on_esp_response(self, data: bytes) -> None:
        """Handle responses from the ESP32."""
        try:
            # Decode the response
            response_str = data.decode('utf-8', errors='ignore').strip()
            
            # Try to parse as JSON (if ESP32 sends JSON responses)
            try:
                import json
                response = json.loads(response_str)
                
                # Process different response types
                if response.get("type") == "ack":
                    # Acknowledge command reception
                    node = response.get("node", "?")
                    status = response.get("status", "?")
                    self._schedule_log(f"ESP32 Node {node}: ACK ({status})")
                
                elif response.get("type") == "sensor":
                    # Sensor data from ESP32
                    node = response.get("node", "?")
                    voltage = response.get("voltage", "?")
                    charge = response.get("charge", "?")
                    self._schedule_log(f"ESP32 Node {node}: Voltage={voltage}V, Charge={charge}%")
                    
                    # Update the node registry if available
                    for node_state in self.node_registry.nodes:
                        if node_state.number == node:
                            node_state.voltage = voltage
                            node_state.charge = charge
                            self._refresh_node_view()
                            break
                
                else:
                    # Unknown JSON response type
                    self._schedule_log(f"ESP32: {response_str}")
            
            except json.JSONDecodeError:
                # Not JSON, just log the raw response
                self._schedule_log(f"ESP32: {response_str}")
        
        except Exception as exc:
            print(f"Error processing ESP32 response: {exc}")


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
