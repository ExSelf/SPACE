SPACE is short for Svetlitsa Proprietary Application for Command and Execution.

A desktop MIDI-to-BEAM bridge application that listens to MIDI input, converts MIDI commands into BEAM packets, and sends them through a wireless mesh to SUN (Sevtlitsa Universal Node) devices.

## Architecture

```
DAW (MIDI Output) → SPACE Bridge → BEAM Controller → SUN Nodes
                ↑__________________ Status Updates _____|
```

- **SPACE:** This Python/Qt application (MIDI input listener and packet bridge)
- **BEAM:** Bidirectional Engine for Asynchronous Messaging (wireless mesh controller)
- **SUN:** Sevtlitsa Universal Node (ESP32-based command executors)

## What It Does

- **Listens** to MIDI note_on/note_off and control_change messages
- **Converts** MIDI into CSV-formatted command packets with TTL routing
- **Sends** packets over USB serial to BEAM controller
- **Receives** status updates from SUN nodes (voltage, charge, command execution state)
- **Displays** real-time node status in a tree view UI
- **Routes** commands through BEAM mesh with configurable Time-To-Live (1-12 hops)
- **Persists** node configuration (names, MIDI channel assignments) to JSON

## Features

### User Interface
- **MIDI Input Selection:** Choose from available MIDI ports
- **Serial Port Selection:** Connect to BEAM controller
- **TTL Slider:** Control command reach (1-12 hops through mesh)
- **Node Tree View:** Real-time display of:
  - Node ID and name
  - Command/parameter sent and actual executing
  - Supply voltage and battery charge
  - Last update timestamp
- **Channel Configuration:** Assign MIDI channels to nodes

### Protocol
- **Command Packets:** CSV format with TTL, node ID, timestamp, 12 command bytes
- **Status Packets:** Incoming updates from nodes (~10-100 Hz per node)
- **Efficient Encoding:** Compact comma-separated values (not JSON for status)
- **Mesh Routing:** TTL-based command delivery through BEAM

## Install

### Requirements
- Python 3.10+
- macOS, Windows, or Linux

### Setup
```bash
# Clone or download this repository
cd SPACE

# Create virtual environment
python -m venv .venv

# Activate it
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Run the App

```bash
python main.py
```

## Configuration

### Node Settings (`node_settings.json`)

Configure which MIDI channels control which nodes:

```json
{
  "nodes": [
    {
      "number": 1,
      "name": "Front Light",
      "listen_channels": [true, false, false, ...]
    }
  ]
}
```

The app auto-creates this file with 255 nodes on first run.

## Documentation

- **[BEAM Protocol Reference](BEAM_PROTOCOL.md)** - Detailed protocol specification
- **[API Reference](API_REFERENCE.md)** - Python class and method documentation

## Development

### Run Tests
```bash
python -m pytest tests/ -v
```

### Run Linter
```bash
pylint space/ main.py
```

### Code Structure
```
.
├── main.py                  # Qt application and MIDI/packet handling
├── space/
│   ├── __init__.py
│   ├── config.py            # Serial port configuration
│   ├── midi_input.py        # MIDI listener (Windows native support)
│   ├── node_registry.py     # Node management and status tracking
│   ├── packet.py            # Packet serialization/deserialization
│   └── serial_link.py       # USB serial communication with BEAM
├── tests/
│   ├── test_main.py
│   └── test_node_registry.py
├── node_settings.json       # Persisted node configuration
└── requirements.txt
```

## Build Standalone App

On macOS and Windows, create a single executable:

```bash
pyinstaller --name SPACE --onefile --windowed main.py
```

The executable will be in the `dist/` folder.

## References

- **BEAM:** https://github.com/ExSelf/BEAM
- **SUN:** https://github.com/ExSelf/SUN
- **Legacy SPACE:** https://github.com/ExSelf/MIDI-Bridge-legacy
- **Legacy BEAM:** https://github.com/ExSelf/ESP-to-Serial-Legacy

## Performance

- Handles 10-100 status updates per second per node
- Supports 1-255 nodes
- TTL-based mesh routing for reliable delivery
- Real-time UI updates (configurable refresh rate)

## License

See LICENSE file.

