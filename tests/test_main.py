from __future__ import annotations

from unittest.mock import Mock, patch

import main
import space.midi_input as midi_input


class DummyButton:
    def __init__(self) -> None:
        self.state = None

    def config(self, **kwargs) -> None:
        self.state = kwargs.get("state")


class DummyVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value


def test_list_input_ports_uses_windows_fallback_when_mido_is_unavailable() -> None:
    with patch("space.midi_input.platform.system", return_value="Windows"), patch(
        "space.midi_input._enumerate_windows_input_ports", return_value=["Microsoft GS Wavetable Synth"]
    ):
        assert midi_input.list_input_ports() == ["Microsoft GS Wavetable Synth"]


def test_start_bridge_keeps_running_when_serial_open_fails() -> None:
    app = main.BridgeApp.__new__(main.BridgeApp)
    app.running = False
    app.start_button = DummyButton()
    app.root = Mock()
    app.root.after = Mock()
    app.midi_input = None
    app.serial_link = None
    app.midi_var = DummyVar("(no MIDI ports)")
    app.serial_var = DummyVar("(no serial ports)")
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
