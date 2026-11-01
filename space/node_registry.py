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
    command_timestamp_ms: int | None = None
    actual_command_timestamp_ms: int | None = None
    constant_commands: List[int] = field(default_factory=lambda: [0] * 12)
    actual_constant_commands: List[int] = field(default_factory=lambda: [0] * 12)
    voltage: float | None = None
    charge: int | None = None
    last_timestamp_received: str | None = None
    last_seen_at: float | None = None
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
                last_seen_at=None,
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
                    last_seen_at=None,
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
                        last_seen_at=None,
                        listen_channels=[False] * 16,
                    )
                )

        self.nodes = loaded_nodes[:255]

    def recent_nodes(self, max_age_seconds: float = 60.0) -> List[NodeState]:
        """Return nodes seen within the recent activity window."""
        cutoff = time() - max_age_seconds
        return [
            node
            for node in self.nodes
            if node.last_seen_at is not None and node.last_seen_at >= cutoff
        ]

    def nodes_for_midi_channel(self, channel: int) -> List[NodeState]:
        """Return all configured nodes that listen to a given MIDI channel."""
        if not 0 <= channel < 16:
            return []

        return [node for node in self.nodes if node.listen_channels[channel]]

    def apply_midi_message(self, channel: int, command: int, parameter: int | None) -> None:
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

    def update_sent_command(self, node_number: int, command: int, parameter: int | None) -> bool:
        """Record a command successfully sent to one node."""
        node = self.get_node(node_number)
        if node is None:
            return False
        node.command = command
        node.parameter = parameter
        node.command_timestamp = time()
        return True

    def update_desired_command(self, node_number: int, command: int, parameter: int,
                               constant_commands: bytes, command_timestamp_ms: int) -> bool:
        """Store the full command state SPACE is retrying until SUN confirms it."""
        node = self.get_node(node_number)
        if node is None:
            return False
        node.command = command
        node.parameter = parameter
        node.constant_commands = list(constant_commands[:12].ljust(12, b"\x00"))
        node.command_timestamp = time()
        node.command_timestamp_ms = command_timestamp_ms & 0xFFFFFFFF
        return True

    def update_node_status(self, node_number: int, voltage: float | None = None, 
                          charge: int | None = None, actual_command: int | None = None,
                          actual_parameter: int | None = None,
                          actual_constant_commands: bytes | None = None,
                          actual_command_timestamp_ms: int | None = None) -> bool:
        """
        Update a node's actual status from a status packet received from the node.
        Returns True if the node was found and updated, False otherwise.
        """
        for node in self.nodes:
            if node.number == node_number:
                if voltage is not None:
                    node.voltage = voltage
                if charge is not None:
                    node.charge = charge
                now = time()
                if actual_command is not None:
                    node.actual_command = actual_command
                    node.command_timestamp_actual = now
                if actual_parameter is not None:
                    node.actual_parameter = actual_parameter
                    node.command_timestamp_actual = now
                if actual_constant_commands is not None:
                    node.actual_constant_commands = list(actual_constant_commands[:12].ljust(12, b"\x00"))
                if actual_command_timestamp_ms is not None:
                    node.actual_command_timestamp_ms = actual_command_timestamp_ms
                if node.command_timestamp_ms is None:
                    if actual_command is not None:
                        node.command = actual_command
                    if actual_parameter is not None:
                        node.parameter = actual_parameter
                    if actual_constant_commands is not None:
                        node.constant_commands = list(actual_constant_commands[:12].ljust(12, b"\x00"))
                node.last_seen_at = now

                # Format timestamp as readable string
                from datetime import datetime
                node.last_timestamp_received = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                
                return True
        return False

    def get_node(self, node_number: int) -> NodeState | None:
        """Get a node by its number, or None if not found."""
        for node in self.nodes:
            if node.number == node_number:
                return node
        return None
