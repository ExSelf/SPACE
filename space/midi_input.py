"""MIDI input wrapper for listening to commands from a MIDI device."""

from __future__ import annotations

import ctypes
import platform
from ctypes import wintypes
from typing import Callable

import mido

if platform.system() == "Windows":
    try:
        _winmm = ctypes.windll.winmm
    except Exception:  # pragma: no cover - runtime environment specific
        _winmm = None

    class _MIDIINCAPS(ctypes.Structure):
        _fields_ = [
            ("wMid", ctypes.c_ushort),
            ("wPid", ctypes.c_ushort),
            ("vDriverVersion", ctypes.c_ulong),
            ("szPname", ctypes.c_wchar * 32),
            ("dwSupport", ctypes.c_ulong),
        ]

    _MIDIINCAPS_PTR = ctypes.POINTER(_MIDIINCAPS)
    _CALLBACK_FN = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    _MIM_DATA = 0x3C3
    _MIM_OPEN = 0x3C1
    _MIM_CLOSE = 0x3C2
    _MIM_LONGDATA = 0x3C4
    _MIM_ERROR = 0x3C5
    _MIM_LONGERROR = 0x3C6
    _MIM_MOREDATA = 0x3C7
    _CALLBACK_FUNCTION = 0x00030000

    if _winmm is not None:
        _winmm.midiInGetNumDevs.restype = ctypes.c_uint
        _winmm.midiInGetDevCapsW.argtypes = [ctypes.c_uint, _MIDIINCAPS_PTR, ctypes.c_uint]
        _winmm.midiInGetDevCapsW.restype = ctypes.c_int
        _winmm.midiInOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, _CALLBACK_FN, ctypes.c_void_p, ctypes.c_uint]
        _winmm.midiInOpen.restype = ctypes.c_int
        _winmm.midiInStart.argtypes = [ctypes.c_void_p]
        _winmm.midiInStart.restype = ctypes.c_int
        _winmm.midiInStop.argtypes = [ctypes.c_void_p]
        _winmm.midiInStop.restype = ctypes.c_int
        _winmm.midiInClose.argtypes = [ctypes.c_void_p]
        _winmm.midiInClose.restype = ctypes.c_int


def _enumerate_windows_input_ports() -> list[str]:
    """Enumerate MIDI input devices using the native Windows MIDI API."""
    if _winmm is None:
        return []

    try:
        count = _winmm.midiInGetNumDevs()
    except Exception:
        return []

    ports: list[str] = []
    for index in range(int(count)):
        caps = _MIDIINCAPS()
        try:
            if _winmm.midiInGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                name = caps.szPname.strip()
                if name:
                    ports.append(name)
        except Exception:
            continue
    return ports


def list_input_ports() -> list[str]:
    """Return the available MIDI input port names."""
    if platform.system() == "Windows":
        ports = _enumerate_windows_input_ports()
        if ports:
            return ports

    try:
        return list(mido.get_input_names())
    except Exception as exc:
        print(f"MIDI port discovery failed: {exc}")
        return []


class _WindowsMidiInput:
    """Native Windows MIDI input implementation using winmm."""

    def __init__(self, port_name: str | None = None, callback: Callable | None = None):
        self.port_name = port_name
        self.callback = callback
        self._handle = None
        self._callback = None
        self._closed = True

    def open(self) -> None:
        if _winmm is None:
            raise RuntimeError("Windows MIDI support is unavailable")

        ports = list_input_ports()
        if self.port_name and self.port_name not in ports:
            print(f"Requested MIDI port '{self.port_name}' was not found. Available ports: {ports}")
            self.port_name = None

        device_index = 0
        if self.port_name:
            try:
                device_index = ports.index(self.port_name)
            except ValueError:
                device_index = 0

        handle = ctypes.c_void_p()
        callback = _CALLBACK_FN(self._on_message)
        status = _winmm.midiInOpen(ctypes.byref(handle), device_index, callback, 0, _CALLBACK_FUNCTION)
        if status != 0:
            raise RuntimeError(f"Unable to open Windows MIDI input device {device_index}: {status}")

        self._handle = handle
        self._callback = callback
        _winmm.midiInStart(handle)
        self._closed = False
        print(f"MIDI input ready on: {self.port_name or ports[device_index] if ports else '(default)'}")

    def _on_message(self, _hMidiIn, wMsg, _dwInstance, dwParam1, _dwParam2) -> None:
        if wMsg != _MIM_DATA:
            return

        status = dwParam1 & 0xFF
        data1 = (dwParam1 >> 8) & 0xFF
        data2 = (dwParam1 >> 16) & 0xFF
        if status is None:
            return

        message_type = status & 0xF0
        channel = status & 0x0F
        if message_type == 0x90 and data2 != 0:
            message = mido.Message("note_on", channel=channel, note=data1, velocity=data2)
        elif message_type == 0x90 or message_type == 0x80:
            message = mido.Message("note_off", channel=channel, note=data1, velocity=data2 or 0)
        elif message_type == 0xB0:
            message = mido.Message("control_change", channel=channel, control=data1, value=data2)
        elif message_type == 0xC0:
            message = mido.Message("program_change", channel=channel, program=data1)
        else:
            return

        if self.callback is not None:
            self.callback(message)

    def close(self) -> None:
        if self._handle is not None:
            try:
                _winmm.midiInStop(self._handle)
                _winmm.midiInClose(self._handle)
            except Exception:
                pass
        self._handle = None
        self._callback = None
        self._closed = True
        print("MIDI input closed.")


class MidiInput:
    """Simple wrapper around a MIDI input callback."""

    def __init__(self, port_name: str | None = None, callback: Callable | None = None):
        self.port_name = port_name
        self.callback = callback
        self._port = None
        self._closed = True

    def open(self) -> None:
        """Open the MIDI input and register the callback."""
        ports = list_input_ports()
        if self.port_name and self.port_name not in ports:
            print(f"Requested MIDI port '{self.port_name}' was not found. Available ports: {ports}")
            self.port_name = None

        try:
            if platform.system() == "Windows" and _winmm is not None:
                self._port = _WindowsMidiInput(self.port_name, self.callback)
                self._port.open()
            else:
                self._port = mido.open_input(self.port_name, callback=self.callback)
                print(f"MIDI input ready on: {self.port_name or '(default)'}")
        except Exception as exc:  # pragma: no cover - runtime environment specific
            print(f"Unable to open MIDI input: {exc}")
            self._port = None

        self._closed = self._port is None

    def close(self) -> None:
        """Close the MIDI input."""
        if self._port is not None:
            if hasattr(self._port, "close"):
                self._port.close()
            else:
                self._port.close()
        self._closed = True
        print("MIDI input closed.")
