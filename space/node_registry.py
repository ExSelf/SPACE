from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import List


@dataclass
class NodeState:
    """Represents a node discovered or configured for the bridge UI."""

    number: int
    name: str
    address: str
    command: int | None = None
    actual_command: int | None = None
    parameter: int | None = None
    actual_parameter: int | None = None
    command_timestamp: float | None = None
    command_timestamp_actual: float | None = None
    constant_commands: List[int] = field(default_factory=lambda: [0] * 12)
    actual_constant_commands: List[int] = field(default_factory=lambda: [0] * 12)
    voltage: float | None = None
    charge: int | None = None
    last_timestamp_received: str | None = None
    listen_channels: List[bool] = field(default_factory=lambda: [False] * 16)


class NodeRegistry:
    """Stores the node list used by the UI and any future runtime logic."""

    def __init__(self, initialize_default_nodes: bool = False) -> None:
        self.nodes: List[NodeState] = []
        if initialize_default_nodes:
            self._initialize_default_nodes()

    def _initialize_default_nodes(self) -> None:
        self.nodes = [
            NodeState(
                number=index,
                name=f"Node {index}",
                address=f"0x{index:02x}",
                command=None,
                actual_command=None,
                parameter=None,
                actual_parameter=None,
                command_timestamp=None,
                command_timestamp_actual=None,
                constant_commands=[0x00] * 12,
                actual_constant_commands=[0x00] * 12,
                voltage=None,
                charge=None,
                last_timestamp_received=None,
                listen_channels=[False] * 16,
            )
            for index in range(1, 256)
        ]

    def add_node(self, node: NodeState) -> None:
        if len(self.nodes) >= 255 and not any(existing.number == node.number for existing in self.nodes):
            raise ValueError("The node registry supports at most 255 nodes.")
        if any(existing.number == node.number for existing in self.nodes):
            self.nodes = [existing if existing.number != node.number else node for existing in self.nodes]
            return
        self.nodes.append(node)

    def create_dummy_node(self) -> NodeState:
        if not self.nodes:
            node = NodeState(
                number=1,
                name="Dummy Node",
                address="0x01",
                command=0x90,
                actual_command=0x90,
                parameter=127,
                actual_parameter=127,
                command_timestamp=time(),
                command_timestamp_actual=time(),
                constant_commands=[0x00] * 12,
                actual_constant_commands=[0x00] * 12,
                voltage=3.3,
                charge=100,
                last_timestamp_received="--",
                listen_channels=[True] * 16,
            )
            self.add_node(node)
            return node

        node = self.nodes[0]
        node.name = "Dummy Node"
        node.address = "0x01"
        node.command = 0x90
        node.actual_command = 0x90
        node.parameter = 127
        node.actual_parameter = 127
        node.command_timestamp = time()
        node.command_timestamp_actual = time()
        node.constant_commands = [0x00] * 12
        node.actual_constant_commands = [0x00] * 12
        node.voltage = 3.3
        node.charge = 100
        node.last_timestamp_received = "--"
        node.listen_channels = [True] * 16
        return node

    def save_to_file(self, path: str | Path) -> None:
        payload = {
            "nodes": [
                {
                    "number": node.number,
                    "name": node.name,
                    "listen_channels": node.listen_channels,
                }
                for node in self.nodes
            ]
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_from_file(self, path: str | Path) -> None:
        file_path = Path(path)
        if not file_path.exists():
            self._initialize_default_nodes()
            return

        payload = json.loads(file_path.read_text(encoding="utf-8"))
        nodes_payload = payload.get("nodes", [])
        if not nodes_payload:
            self._initialize_default_nodes()
            return

        loaded_nodes: List[NodeState] = []
        for entry in nodes_payload[:255]:
            loaded_nodes.append(
                NodeState(
                    number=entry.get("number", len(loaded_nodes) + 1),
                    name=entry.get("name", f"Node {len(loaded_nodes) + 1}"),
                    address=f"0x{len(loaded_nodes) + 1:02x}",
                    command=None,
                    actual_command=None,
                    parameter=None,
                    actual_parameter=None,
                    command_timestamp=None,
                    command_timestamp_actual=None,
                    constant_commands=[0x00] * 12,
                    actual_constant_commands=[0x00] * 12,
                    voltage=None,
                    charge=None,
                    last_timestamp_received=None,
                    listen_channels=list(entry.get("listen_channels", [False] * 16)),
                )
            )

        if len(loaded_nodes) < 255:
            for index in range(len(loaded_nodes) + 1, 256):
                loaded_nodes.append(
                    NodeState(
                        number=index,
                        name=f"Node {index}",
                        address=f"0x{index:02x}",
                        command=None,
                        actual_command=None,
                        parameter=None,
                        actual_parameter=None,
                        command_timestamp=None,
                        command_timestamp_actual=None,
                        constant_commands=[0x00] * 12,
                        actual_constant_commands=[0x00] * 12,
                        voltage=None,
                        charge=None,
                        last_timestamp_received=None,
                        listen_channels=[False] * 16,
                    )
                )

        self.nodes = loaded_nodes[:255]

    def apply_midi_message(self, channel: int, command: int, parameter: int) -> None:
        """Update every node that listens to the provided MIDI channel."""
        timestamp = time()
        for node in self.nodes:
            if not 0 <= channel < len(node.listen_channels):
                continue
            if not node.listen_channels[channel]:
                continue
            node.command = command
            node.parameter = parameter
            node.command_timestamp = timestamp
            node.actual_command = command
            node.actual_parameter = parameter
            node.command_timestamp_actual = timestamp
