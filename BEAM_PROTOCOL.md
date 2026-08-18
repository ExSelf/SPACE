# SPACE MIDI Bridge - BEAM/SUN Protocol Implementation

## Overview

This application acts as a MIDI-to-BEAM bridge, translating MIDI commands from a DAW into packets that are sent through the BEAM (Bidirectional Engine for Asynchronous Messaging) to control SUN (Sevtlitsa Universal Node) nodes.

## Architecture

```
DAW (MIDI Output)
    ↓
SPACE MIDI Bridge (This App)
    ↓
BEAM (Wireless Mesh)
    ↓
SUN Nodes (execute commands, send status)
```

## Packet Protocol

### Command Packets (MIDI → SUN)

Command packets are sent from the SPACE bridge to SUN nodes via BEAM. They use a comma-separated format.

**Format:**
```
key,ttl,node,time_b0,time_b1,time_b2,time_b3,cmd0,cmd1,...,cmd11
```

**Fields:**
- `key` (1): Always `1` for command packets
- `ttl` (1-12): Time-To-Live value
  - Set via UI slider (default: 3)
  - When a node receives a command not for it, TTL is decreased and packet is bounced to neighbors
  - Commands are only executed by the target node
- `node` (1-255): Target node ID
- `time_b0, time_b1, time_b2, time_b3` (0-255): Timestamp in milliseconds (little-endian 32-bit)
- `cmd0...cmd11` (0-255): 12 command bytes representing node state
  - Usually initialized from MIDI control_change messages
  - Each byte represents a control parameter

**Example:**
```
1,3,5,237,183,135,21,0,0,0,0,0,0,0,0,0,0,0,0
│ │ │ └─────┬─────┘ └──────────┬──────────┘
│ │ │       │                  └─ 12 command bytes (all zeros)
│ │ │       └─ Timestamp (little-endian)
│ │ └─ Node 5
│ └─ TTL 3 (will bounce through 3 hops if not for target)
└─ Command packet type
```

### Status Packets (SUN → MIDI)

Status packets are sent from SUN nodes back through BEAM to inform the bridge of node status. These arrive ~10-100 times per second per node.

**Format:**
```
node,voltage,charge,actual_command,actual_parameter
```

**Fields:**
- `node` (1-255): Source node ID
- `voltage` (float): Current supply voltage in volts
- `charge` (0-100): Battery charge percentage
- `actual_command` (0-255): Currently executing command
- `actual_parameter` (0-255): Current command parameter value

**Example:**
```
3,3.3,85,100,50
│ │   │  │   └─ Current parameter value
│ │   │  └─ Currently executing command (100)
│ │   └─ Battery at 85%
│ └─ Supply voltage 3.3V
└─ From node 3
```

## UI Features

### TTL Slider
Located in the main bridge controls, allows adjustment of the Time-To-Live value from 1 to 12 hops.
- **Default:** 3
- **Purpose:** Controls how far through the BEAM mesh a command can travel
- **Lower values (1-2):** Direct commands to nearby nodes only
- **Higher values (8-12):** Commands can reach distant nodes through multiple hops

### Node Status Display
The node tree displays real-time status information from all SUN nodes:
- **Node:** Node identifier (1-255)
- **Name:** User-assigned node name
- **Address:** Hexadecimal address
- **Cmd:** Last command sent to this node
- **Actual Cmd:** Currently executing command on the node
- **Param:** Last parameter sent
- **Actual Param:** Current parameter value on node
- **Voltage:** Current supply voltage
- **Charge:** Battery charge percentage

## MIDI to Packet Mapping

The bridge translates MIDI messages into command packets:

### Note On Messages
```
MIDI Note On (channel, note, velocity)
    ↓
Packet:
  node = channel + 1
  command = note (60-127)
  parameter = velocity (0-127)
```

### Control Change Messages
```
MIDI CC (channel, controller, value)
    ↓
Packet:
  node = channel + 1
  constant_commands[0] = CC value
  (remaining 11 bytes = 0)
```

## Node Configuration

Nodes are configured in `node_settings.json` with:
- **number:** Node ID (1-255)
- **name:** Display name
- **listen_channels:** Array of 16 booleans
  - When a MIDI channel is enabled for a node, all note_on/control_change messages on that channel trigger the node
  - This allows one MIDI channel to control multiple nodes or one node to listen to multiple MIDI channels

**Example:**
```json
{
  "nodes": [
    {
      "number": 1,
      "name": "Front Light",
      "listen_channels": [true, false, false, ...]
    },
    {
      "number": 2,
      "name": "Back Light",
      "listen_channels": [false, true, false, ...]
    }
  ]
}
```

## Status Update Handling

The bridge maintains a real-time display of node status:

1. **High-Frequency Updates:** SUN nodes send status 10-100 times per second
2. **Aggregation:** The serial link's receive thread queues all incoming data
3. **UI Update:** Status packets trigger registry updates and UI tree refresh
4. **Timestamp Tracking:** Each node records `last_timestamp_received` for monitoring connection health

## Implementation Details

### Classes

#### `Packet`
Command packet representation with CSV serialization
- Properties: type, node, ttl, command, parameter, constant_commands, timestamp_ms
- Method: `to_wire_payload()` → bytes (CSV format)

#### `StatusPacket`
Status packet representation with CSV deserialization
- Properties: node, voltage, charge, actual_command, actual_parameter, timestamp
- Method: `from_wire_payload(data: bytes)` → StatusPacket | None

#### `NodeRegistry`
Node management and status tracking
- Method: `update_node_status()` - Updates node with status packet data
- Method: `apply_midi_message()` - Broadcasts MIDI to all listening nodes
- Method: `get_node()` - Retrieve a specific node

#### `SerialLink`
USB serial communication with BEAM controller
- Manages bidirectional communication
- Spawns receive thread for async status updates
- Handles packet serialization and response parsing

### Data Flow

**Outbound (MIDI → SUN):**
```
MIDI Message
    ↓ midi_to_packet(msg, ttl)
Packet object
    ↓ .to_wire_payload()
CSV bytes: "1,3,5,237,183,135,21,0,0,0,0,0,0,0,0,0,0,0,0"
    ↓ serial_link.send()
USB Serial → BEAM Controller → SUN Node
```

**Inbound (SUN → MIDI):**
```
USB Serial ← BEAM Controller ← SUN Node
CSV bytes: "3,3.3,85,100,50"
    ↓ StatusPacket.from_wire_payload()
StatusPacket object
    ↓ node_registry.update_node_status()
NodeState updated
    ↓ _refresh_node_view()
UI tree updated with voltage, charge, actual_command
```

## Testing

Run tests to verify implementation:
```bash
python -m pytest tests/ -v
```

All 6 tests pass, covering:
- MIDI input port detection
- Bridge initialization and error handling
- Node registry creation and persistence
- MIDI message application to listening nodes
- Channel configuration

## Usage Notes

- **TTL Values:** Start with 3-5 for most setups. Increase if nodes aren't responding, decrease if commands are taking too long.
- **Status Updates:** High frequency updates (10-100/sec) provide real-time feedback but shouldn't be logged or displayed at full rate - use timestamp debouncing for UI.
- **Node Addressing:** Nodes 1-255 are supported. MIDI channels 0-15 map to nodes 1-16 (if configured).
- **Voltage Monitoring:** Watch for drops below 3.0V which may indicate connection or power issues.

## References

- BEAM: https://github.com/ExSelf/BEAM
- SUN: https://github.com/ExSelf/SUN
- Legacy SPACE: https://github.com/ExSelf/MIDI-Bridge-legacy
- Legacy BEAM: https://github.com/ExSelf/ESP-to-Serial-Legacy
