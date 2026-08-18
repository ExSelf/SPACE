# SPACE MIDI Bridge - API Reference

## Quick Start

### Basic MIDI to SUN Node Command

```python
from space.packet import Packet

# Create a command packet
packet = Packet(
    type="command",
    node=5,              # Target node ID
    ttl=3,              # Time-to-live hops
    command=100,        # Command value
    parameter=50        # Command parameter
)

# Send via serial link
serial_link.send(packet)
```

### Parsing Incoming Status

```python
from space.packet import StatusPacket

# Received data from SUN node
received_data = b"3,3.3,85,100,50"

# Parse it
status = StatusPacket.from_wire_payload(received_data)
if status:
    print(f"Node {status.node}: {status.voltage}V, {status.charge}% charge")
    print(f"Executing: command={status.actual_command}, param={status.actual_parameter}")
```

### Managing Nodes

```python
from space.node_registry import NodeRegistry

# Create registry
registry = NodeRegistry()

# Load from file
registry.load_from_file("node_settings.json")

# Update node status from incoming packet
registry.update_node_status(
    node_number=3,
    voltage=3.3,
    charge=85,
    actual_command=100,
    actual_parameter=50
)

# Get specific node
node = registry.get_node(3)
if node:
    print(f"{node.name}: {node.voltage}V")
```

## Class Reference

### Packet

Command packet sent to SUN nodes.

**Properties:**
- `type`: str = "command"
- `node`: int - Target node ID (1-255)
- `ttl`: int = 3 - Time-to-live (1-12)
- `command`: int | None - Command value (0-255)
- `parameter`: int | None - Parameter value (0-255)
- `constant_commands`: bytes | None - 12 command bytes
- `timestamp_ms`: int | None - Timestamp (auto-set if None)

**Methods:**
```python
def to_wire_payload(self) -> bytes:
    """Serialize to CSV format for transmission."""
    # Returns: b"1,3,5,237,183,135,21,0,0,0,0,0,0,0,0,0,0,0,0"
```

### StatusPacket

Status update from a SUN node.

**Properties:**
- `node`: int - Source node ID
- `voltage`: float - Supply voltage (volts)
- `charge`: int - Battery charge (0-100)
- `actual_command`: int - Currently executing command
- `actual_parameter`: int - Current parameter value
- `timestamp`: float - Reception timestamp

**Methods:**
```python
@staticmethod
def from_wire_payload(data: bytes) -> StatusPacket | None:
    """Parse CSV status packet."""
    # Input: b"3,3.3,85,100,50"
    # Returns: StatusPacket(...) or None if parse fails
```

### NodeRegistry

Manages node collection and status.

**Properties:**
- `nodes`: List[NodeState] - All known nodes

**Methods:**
```python
def add_node(self, node: NodeState) -> None:
    """Add or update a node in registry."""

def get_node(self, node_number: int) -> NodeState | None:
    """Retrieve a node by ID."""

def update_node_status(self, 
                      node_number: int,
                      voltage: float | None = None,
                      charge: int | None = None,
                      actual_command: int | None = None,
                      actual_parameter: int | None = None) -> bool:
    """Update node status from incoming packet."""

def apply_midi_message(self, 
                      channel: int,
                      command: int,
                      parameter: int) -> None:
    """Apply MIDI message to all nodes listening on channel."""

def load_from_file(self, path: str | Path) -> None:
    """Load node configuration from JSON file."""

def save_to_file(self, path: str | Path) -> None:
    """Save node configuration to JSON file."""
```

### NodeState

Individual node status and configuration.

**Properties:**
- `number`: int - Node ID (1-255)
- `name`: str - Display name
- `address`: str - Hex address (0x01-0xFF)
- `command`: int | None - Last sent command
- `actual_command`: int | None - Currently executing command
- `parameter`: int | None - Last sent parameter
- `actual_parameter`: int | None - Current parameter value
- `command_timestamp`: float | None - When command was sent
- `command_timestamp_actual`: float | None - When actual state changed
- `constant_commands`: List[int] - 12-byte command state (sent)
- `actual_constant_commands`: List[int] - 12-byte command state (actual)
- `voltage`: float | None - Supply voltage
- `charge`: int | None - Battery charge percentage
- `last_timestamp_received`: str | None - Last update timestamp (formatted)
- `listen_channels`: List[bool] - 16 MIDI channels (True = listen)

## Usage Patterns

### MIDI Command Forwarding

```python
from space.packet import Packet

def handle_midi_message(message, ttl, registry):
    if message.type == "note_on":
        node = message.channel + 1  # MIDI channel → node ID
        packet = Packet(
            type="command",
            ttl=ttl,
            node=node,
            command=message.note,
            parameter=message.velocity
        )
        return packet
    return None
```

### Status Update Callback

```python
def on_status_received(data, registry):
    status = StatusPacket.from_wire_payload(data)
    if status:
        # Update registry
        registry.update_node_status(
            node_number=status.node,
            voltage=status.voltage,
            charge=status.charge,
            actual_command=status.actual_command,
            actual_parameter=status.actual_parameter
        )
        # Now use status.voltage, status.charge, etc.
        return status
    return None
```

### TTL-Based Routing

```python
def send_with_ttl(packet, ttl_slider_value, serial_link):
    packet.ttl = ttl_slider_value  # 1-12
    
    # Lower TTL = local only, Higher TTL = can reach far nodes
    serial_link.send(packet)
```

### MIDI Channel Filtering

```python
def configure_node_channels(node, enabled_channels):
    """Configure which MIDI channels control this node."""
    node.listen_channels = [False] * 16
    for channel_num in enabled_channels:
        if 0 <= channel_num < 16:
            node.listen_channels[channel_num] = True
```

## Error Handling

### Graceful Degradation

```python
try:
    status = StatusPacket.from_wire_payload(data)
except Exception as e:
    print(f"Failed to parse status: {e}")
    # Fall back to JSON parsing
    response = json.loads(data.decode('utf-8'))
```

### Node Not Found

```python
node = registry.get_node(100)
if node is None:
    print("Node 100 not configured")
    # Create new node
    from space.node_registry import NodeState
    new_node = NodeState(
        number=100,
        name="New Node",
        address="0x64"
    )
    registry.add_node(new_node)
```

## File Formats

### Node Configuration (node_settings.json)

```json
{
  "nodes": [
    {
      "number": 1,
      "name": "Front Light",
      "listen_channels": [true, false, false, false, ...]
    },
    {
      "number": 2,
      "name": "Back Light",
      "listen_channels": [false, true, false, false, ...]
    }
  ]
}
```

## Performance Notes

- Status packets arrive at 10-100 Hz per node
- Serial communication is 115200 baud
- Use timestamp debouncing for UI updates (don't refresh every 10ms)
- CSV format is more efficient than JSON for high-frequency status
- TTL wraps timestamp at 32-bit boundary (~49 days), which is fine for session-based operation

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No serial ports detected" | Check USB connection, driver installation |
| Nodes not responding | Increase TTL value; check node power; verify node IDs |
| Status updates not received | Check BEAM configuration; verify node sending |
| High CPU usage | Reduce UI refresh rate; don't log every status update |
| Timestamp mismatch | Timestamps wrap at 49-day intervals; this is expected |
