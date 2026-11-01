from __future__ import annotations

import json
import time

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
    assert second.command_timestamp is not None
    assert first.actual_command is None
    assert second.actual_command is None
    assert registry.recent_nodes() == []


def test_control_change_update_clears_the_note_parameter() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    node = NodeState(
        number=1,
        name="Node 1",
        address="0x01",
        parameter=60,
        listen_channels=[True] + [False] * 15,
    )
    registry.add_node(node)

    registry.apply_midi_message(channel=0, command=127, parameter=None)

    assert node.command == 127
    assert node.parameter is None


def test_recent_nodes_only_returns_nodes_seen_within_the_window() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    recent = NodeState(number=1, name="Recent", address="0x01", last_seen_at=time.time() - 30)
    stale = NodeState(number=2, name="Stale", address="0x02", last_seen_at=time.time() - 120)
    registry.add_node(recent)
    registry.add_node(stale)

    visible = registry.recent_nodes(max_age_seconds=60)

    assert visible == [recent]


def test_received_node_status_marks_only_that_node_as_recent() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    node_3 = NodeState(number=3, name="Node 3", address="0x03")
    node_5 = NodeState(number=5, name="Node 5", address="0x05")
    node_255 = NodeState(number=255, name="Node 255", address="0xff")
    registry.add_node(node_3)
    registry.add_node(node_5)
    registry.add_node(node_255)

    assert registry.update_node_status(node_number=255, voltage=3.3, charge=90)

    assert registry.recent_nodes() == [node_255]


def test_first_status_seeds_desired_state_without_overwriting_pending_command() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    node = NodeState(number=14, name="Node 14", address="0x0e")
    registry.add_node(node)

    registry.update_node_status(
        node_number=14,
        actual_command=21,
        actual_parameter=122,
        actual_constant_commands=bytes(range(12)),
        actual_command_timestamp_ms=456,
    )

    assert node.command == 21
    assert node.parameter == 122
    assert node.constant_commands == list(range(12))

    registry.update_desired_command(14, 30, 90, bytes(range(12)), 789)
    registry.update_node_status(node_number=14, actual_command=21, actual_parameter=122)

    assert node.command == 30
    assert node.parameter == 90
    assert node.command_timestamp_ms == 789


def test_nodes_for_midi_channel_uses_configured_listen_channels() -> None:
    registry = NodeRegistry(initialize_default_nodes=False)
    node_1 = NodeState(number=1, name="Node 1", address="0x01", listen_channels=[False] * 16)
    node_14 = NodeState(number=14, name="Node 14", address="0x14", listen_channels=[False] * 16)
    node_255 = NodeState(number=255, name="Node 255", address="0xff", listen_channels=[False] * 16)
    node_1.listen_channels[13] = True
    node_14.listen_channels[13] = True
    node_255.listen_channels[13] = True
    registry.add_node(node_1)
    registry.add_node(node_14)
    registry.add_node(node_255)

    targets = registry.nodes_for_midi_channel(13)

    assert [node.number for node in targets] == [1, 14, 255]
