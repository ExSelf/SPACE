SPACE is short for Svetlitsa Proprietary Application for Command and Execution.

This repo now contains a desktop MIDI-to-ESP32 bridge app. It listens to MIDI input, converts MIDI commands into packets, and sends them to an ESP32 over USB serial.

## What it does
- Reads MIDI note_on/note_off and control_change messages
- Converts them into compact JSON packets for the ESP32
- Sends packets over USB serial using pyserial
- Runs as a desktop app on macOS and Windows

## Install
```bash
python -m pip install -r requirements.txt
```

## Run the app
```bash
python main.py
```

## Build a standalone app
On macOS and Windows, build with PyInstaller:

```bash
pyinstaller --name SPACE --onefile --windowed main.py
```

The executable will be created in the dist/ folder.
