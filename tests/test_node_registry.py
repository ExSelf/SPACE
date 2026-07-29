from __future__ import annotations

import json

import pytest

from space.node_registry import NodeRegistry, NodeState


def test_registry_contains_dummy_node_and_respects_capacity() -> None:
    registry = NodeRegistry()
    registry.add_node(NodeState(number=1, name="Dummy", address="0x01"))

    assert len(registry.nodes) == 1
    assert registry.nodes[0].number == 1
    assert registry.nodes[0].name == "Dummy"
    assert registry.nodes[0].address == "0x01"

    for index in range(2, 256):
        registry.add_node(NodeState(number=index, name=f"Node {index}", address=f"0x{index:02x}"))

    with pytest.raises(ValueError):
        registry.add_node(NodeState(number=256, name="Too many", address="0x100"))


def test_dummy_node_helper_builds_a_testable_entry() -> None:
    registry = NodeRegistry()
    node = registry.create_dummy_node()

    assert node.number == 1
    assert node.name == "Dummy Node"
    assert len(node.listen_channels) == 16
    assert len(node.constant_commands) == 12
    assert len(node.actual_constant_commands) == 12


def test_registry_persists_node_names_and_channels(tmp_path) -> None:
    path = tmp_path / "nodes.json"
    registry = NodeRegistry()
    registry.load_from_file(path)

    assert len(registry.nodes) == 255
    registry.nodes[0].name = "Alpha"
    registry.nodes[0].listen_channels[3] = True
    registry.save_to_file(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["nodes"][0]["name"] == "Alpha"
    assert payload["nodes"][0]["listen_channels"][3] is True

    reloaded = NodeRegistry()
    reloaded.load_from_file(path)
    assert reloaded.nodes[0].name == "Alpha"
    assert reloaded.nodes[0].listen_channels[3] is True


def test_apply_midi_message_updates_all_listening_nodes_and_timestamps() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    first = NodeState(number=1, name="Node 1", address="0x01", listen_channels=[False] * 16)
    second = NodeState(number=2, name="Node 2", address="0x02", listen_channels=[False] * 16)
    registry.add_node(first)
    registry.add_node(second)

    first.listen_channels[0] = True
    first.listen_channels[5] = True
    second.listen_channels[1] = True
    second.listen_channels[5] = True

    registry.apply_midi_message(channel=5, command=60, parameter=120)

    assert first.command == 60
    assert first.parameter == 120
    assert second.command == 60
    assert second.parameter == 120
    assert first.command_timestamp is not None
    assert first.command_timestamp_actual is not None
    assert second.command_timestamp is not None
    assert second.command_timestamp_actual is not None
