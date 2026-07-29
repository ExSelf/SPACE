from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Optional

import mido

from space import config
from space.midi_input import MidiInput, list_input_ports
from space.node_registry import NodeRegistry, NodeState
from space.packet import Packet, TYPE_COMMAND
from space.serial_link import SerialLink


def midi_to_packet(message: mido.Message) -> Packet | None:
    """Translate one MIDI message into a command Packet."""
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


def midi_to_registry_update(message: mido.Message) -> tuple[int, int, int] | None:
    """Convert a MIDI message into the values applied to all matching nodes."""
    if message.type in ("note_on", "note_off"):
        return message.channel, message.note, message.velocity if message.type == "note_on" else 0
    if message.type == "control_change":
        return message.channel, message.control, message.value
    return None


class BridgeApp:
    """A desktop app that listens for MIDI and forwards it to an ESP32 over USB serial."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SPACE MIDI Bridge")
        self.root.geometry("900x700")

        self.midi_input: Optional[MidiInput] = None
        self.serial_link: Optional[SerialLink] = None
        self.running = False
        self.settings_path = Path(__file__).with_name("node_settings.json")
        self.node_registry = NodeRegistry(initialize_default_nodes=False)
        self.node_registry.load_from_file(self.settings_path)

        self._build_ui()
        self._populate_ports()
        self._refresh_node_view()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="MIDI input").grid(row=0, column=0, sticky="w")
        self.midi_var = tk.StringVar()
        self.midi_combo = ttk.Combobox(container, textvariable=self.midi_var, state="readonly")
        self.midi_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        ttk.Label(container, text="Serial port").grid(row=1, column=0, sticky="w")
        self.serial_var = tk.StringVar()
        self.serial_combo = ttk.Combobox(container, textvariable=self.serial_var, state="readonly")
        self.serial_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        button_row = ttk.Frame(container)
        button_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.start_button = ttk.Button(button_row, text="Start", command=self.start_bridge)
        self.start_button.pack(side=tk.LEFT)
        ttk.Button(button_row, text="Stop", command=self.stop_bridge).pack(side=tk.LEFT, padx=(8, 0))

        self.log_text = tk.Text(container, height=10, wrap=tk.WORD)
        self.log_text.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.log_text.configure(state="disabled")

        self.node_tree = ttk.Treeview(container, columns=("number", "name", "address", "command", "actual_command", "parameter", "actual_parameter", "voltage", "charge"), show="headings")
        self.node_tree.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.node_tree.heading("number", text="Node")
        self.node_tree.heading("name", text="Name")
        self.node_tree.heading("address", text="Address")
        self.node_tree.heading("command", text="Cmd")
        self.node_tree.heading("actual_command", text="Actual Cmd")
        self.node_tree.heading("parameter", text="Param")
        self.node_tree.heading("actual_parameter", text="Actual Param")
        self.node_tree.heading("voltage", text="Voltage")
        self.node_tree.heading("charge", text="Charge")
        self.node_tree.bind("<<TreeviewSelect>>", self._on_node_selected)

        self.channel_panel = ttk.LabelFrame(container, text="Node channels")
        self.channel_panel.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.channel_vars: list[tk.BooleanVar] = []
        for index in range(16):
            var = tk.BooleanVar()
            self.channel_vars.append(var)
            ttk.Checkbutton(self.channel_panel, text=f"Ch {index + 1}", variable=var, command=self._save_selected_node_channels).grid(row=index // 8, column=index % 8, padx=6, pady=4, sticky="w")

        container.columnconfigure(1, weight=1)
        container.rowconfigure(3, weight=1)
        container.rowconfigure(4, weight=1)
        container.rowconfigure(5, weight=1)

    def _populate_ports(self) -> None:
        midi_ports = list_input_ports()
        serial_ports = SerialLink.list_ports()
        self.midi_combo["values"] = midi_ports or ["(no MIDI ports)"]
        self.serial_combo["values"] = serial_ports or ["(no serial ports)"]

        if midi_ports:
            self.midi_var.set(midi_ports[0])
        elif self.midi_var.get() not in {"", "(no MIDI ports)"}:
            self.midi_var.set("(no MIDI ports)")
        else:
            self.midi_var.set("(no MIDI ports)")

        if serial_ports:
            self.serial_var.set(serial_ports[0])
        elif self.serial_var.get() not in {"", "(no serial ports)"}:
            self.serial_var.set("(no serial ports)")
        else:
            self.serial_var.set("(no serial ports)")

    def _refresh_node_view(self) -> None:
        for item in self.node_tree.get_children():
            self.node_tree.delete(item)

        for node in self.node_registry.nodes:
            self.node_tree.insert(
                "",
                tk.END,
                values=(
                    node.number,
                    node.name,
                    node.address,
                    node.command,
                    node.actual_command,
                    node.parameter,
                    node.actual_parameter,
                    node.voltage,
                    node.charge,
                ),
            )

    def _on_node_selected(self, _event: tk.Event | None = None) -> None:
        selected_node = self._get_selected_node()
        if selected_node is None:
            return
        for index, var in enumerate(self.channel_vars):
            var.set(selected_node.listen_channels[index])

    def _save_selected_node_channels(self) -> None:
        selected_node = self._get_selected_node()
        if selected_node is None:
            return
        selected_node.listen_channels = [var.get() for var in self.channel_vars]
        self.node_registry.save_to_file(self.settings_path)
        self._refresh_node_view()

    def _get_selected_node(self) -> NodeState | None:
        selection = self.node_tree.selection()
        if not selection:
            return None
        item_id = selection[0]
        item_values = self.node_tree.item(item_id, "values")
        if not item_values:
            return None
        node_number = int(item_values[0])
        return next((candidate for candidate in self.node_registry.nodes if candidate.number == node_number), None)

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _schedule_log(self, message: str) -> None:
        self.root.after(0, lambda: self._log(message))

    def start_bridge(self) -> None:
        if self.running:
            return

        self._log("Starting bridge...")
        self.running = True
        self.start_button.config(state=tk.DISABLED)

        midi_port = self.midi_var.get() if self.midi_var.get() not in {"", "(no MIDI ports)"} else None
        serial_port = self.serial_var.get() if self.serial_var.get() not in {"", "(no serial ports)"} else None
        if midi_port is None:
            self._log("No MIDI input ports were detected. Install the RTMidi backend or use a MIDI device that exposes an input port.")

        self.serial_link = SerialLink(serial_port, config.BAUD_RATE)
        self.serial_link.on_packet = self._on_status_packet
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
        self.start_button.config(state=tk.NORMAL)
        if self.midi_input is not None:
            self.midi_input.close()
        if self.serial_link is not None:
            self.serial_link.close()
        self._log("Bridge stopped.")

    def _on_status_packet(self, packet: Packet) -> None:
        self._schedule_log(f"Packet sent to ESP32: node={packet.node} command={packet.command}")


def main() -> None:
    root = tk.Tk()
    app = BridgeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
