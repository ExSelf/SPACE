# BEAM Binary Protocol Specification v2.0

**Total Packet Size:** 250 bytes (ESP-NOW maximum)
**Format:** Binary (not text/CSV)
**Byte Order:** Little-endian throughout
**Reliability:** Handled by BEAM controller (no checksums needed)

## Packet Types

| Value | Type | Purpose |
|-------|------|---------|
| 1 | COMMAND | Command sent to node |
| 2 | STATUS | Status update from node |
| 3 | ACK | Acknowledgment (reserved for future) |
| 4 | HEARTBEAT | Node alive pulse (reserved for future) |
| 5+ | RESERVED | Future extensions |

## Command Packet (Type 1)

**Purpose:** Send commands from SPACE bridge to SUN nodes via BEAM

**Size:** 250 bytes total

### Header (Bytes 0-24, 25 bytes)
```
Offset  Size  Type       Name                 Description
──────  ────  ─────────  ──────────────────   ─────────────────────────────
0       1     uint8      packet_type          Always 0x01 for COMMAND
1       1     uint8      node_id              Target node (1-255)
2       1     uint8      ttl                  Time-to-live hops (1-12)
3       4     uint32_le  global_timestamp_ms  Milliseconds (wraps every 49 days)
7       4     uint32_le  cmd_timestamp_ms     When command was issued
11      1     uint8      command              Command value (0-255)
12      1     uint8      parameter            Parameter value (0-255)
13      12    uint8[12]  constant_commands    State of 12 command registers
25      1     uint8      flags                Bit flags (reserved)
```

### Payload/Extension (Bytes 26-199, 174 bytes)
```
Offset  Size  Type       Name                 Description
──────  ────  ─────────  ──────────────────   ─────────────────────────────
26      174   bytes      future_payload       Reserved for future use
        - Could hold node names
        - Could hold additional command data
        - Could hold program/config uploads
```

### Reserved (Bytes 200-249, 50 bytes)
```
Offset  Size  Type       Name                 Description
──────  ────  ─────────  ──────────────────   ─────────────────────────────
200     50    bytes      reserved             For protocol evolution
```

## Status Packet (Type 2)

**Purpose:** Send status updates from SUN nodes back to SPACE bridge via BEAM

**Size:** 250 bytes total

### Header (Bytes 0-27, 28 bytes)
```
Offset  Size  Type       Name                 Description
──────  ────  ─────────  ──────────────────   ─────────────────────────────
0       1     uint8      packet_type          Always 0x02 for STATUS
1       1     uint8      node_id              Source node (1-255)
2       1     uint8      ttl                  Remaining hops (updated by BEAM)
3       4     uint32_le  global_timestamp_ms  Node's timestamp
7       4     uint32_le  cmd_timestamp_ms     When executing command since
11      1     uint8      command              Currently executing command
12      1     uint8      parameter            Current parameter value
13      12    uint8[12]  constant_commands    Current command register state
25      2     uint16_le  voltage_mv           Supply voltage in millivolts
27      1     uint8      charge_percent       Battery charge (0-100%)
```

### Subnodes Array (Bytes 28-91, 64 bytes)
Up to 8 subnodes, 8 bytes each (e.g., if main node has sub-controllers)
```
For each of 8 subnode slots (bytes 28-91):
  Offset  Size  Type       Name
  ──────  ────  ─────────  ──────────────
  +0      1     uint8      subnode_id        0 = unused slot
  +1      2     uint16_le  voltage_mv        Subnode voltage
  +3      1     uint8      charge_percent    Subnode charge
  +4      4     bytes      reserved          For future use
  
Repeats 8 times: 8 * 8 = 64 bytes total
```

### Reserved (Bytes 92-249, 158 bytes)
```
Offset  Size  Type       Name                 Description
──────  ────  ─────────  ──────────────────   ─────────────────────────────
92      158   bytes      reserved             For protocol evolution
        - Sensor readings
        - Error codes
        - Debug information
        - Performance metrics
```

## Field Specifications

### packet_type (1 byte)
- Values: 1 (COMMAND), 2 (STATUS)
- Identifies packet purpose
- Used by BEAM and SPACE to route and parse

### node_id (1 byte)
- Range: 1-255
- 0 is reserved (invalid)
- BEAM broadcasts if 255 (reserved for future)

### ttl (1 byte)
- Range: 1-12
- Command: Starting hops
- Status: Remaining hops (updated by BEAM)
- Decremented by each BEAM hop

### Timestamps (4 bytes each, uint32_le)
Both expressed as milliseconds since Unix epoch
```
Bytes 3-6:   global_timestamp_ms
  - When SPACE sent command or node generated status
  - Wraps every 49.7 days (acceptable)
  - Allows ordering of events
  - Not for absolute time, just sequencing

Bytes 7-10:  cmd_timestamp_ms
  - Command: When MIDI message arrived
  - Status: How long node has been executing current command
  - Tracks command duration on node
```

### command (1 byte)
- Range: 0-255
- Meaning depends on SUN node implementation
- Could be: light intensity, motor speed, parameter select, etc.

### parameter (1 byte)
- Range: 0-255
- Additional parameter for the command
- Meaning depends on SUN node implementation

### constant_commands (12 bytes)
- Array of uint8[12]
- Persistent state registers
- Command: What we want node to maintain
- Status: What node currently has
- Allows complex multi-register states

### voltage_mv (2 bytes, uint16_le)
- Millivolts (0-65535 mV = 0-65.535V)
- Example: 3300 mV = 3.3V
- Enough precision for lithium (2.8-4.2V)

### charge_percent (1 byte)
- Range: 0-100%
- Battery level indicator
- 255 if not battery-powered

### subnode_id (1 byte)
- 0 = unused slot
- 1-254 = valid subnode ID
- Up to 8 subnodes per main node

## Examples

### Command Packet (hex)
```
01              packet_type = COMMAND
05              node_id = 5
03              ttl = 3
ED B7 87 15     global_timestamp_ms = 360485101 (little-endian)
00 01 02 03     cmd_timestamp_ms = 50333184 (little-endian)
64              command = 100
32              parameter = 50
00 00 00 00 00 00 00 00 00 00 00 00
                constant_commands[12] = all zeros
00              flags = 0
[174 bytes of future_payload - all zeros]
[50 bytes of reserved - all zeros]
```

### Status Packet (hex)
```
02              packet_type = STATUS
05              node_id = 5
03              ttl = 3
ED B7 87 15     global_timestamp_ms
A0 C2 12 00     cmd_timestamp_ms = 1234080 (executing for 1.2 seconds)
64              command = 100 (executing)
32              parameter = 50
00 00 00 00 00 00 00 00 00 00 00 00
                constant_commands[12]
DC 0C           voltage_mv = 3292 (3.292V, little-endian)
55              charge_percent = 85%

Subnode 1:
  03            subnode_id = 3
  C8 0C         voltage_mv = 3272
  50            charge_percent = 80%
  00 00 00 00   reserved

Subnode 2:
  07            subnode_id = 7
  D0 0C         voltage_mv = 3280
  58            charge_percent = 88%
  00 00 00 00   reserved

Subnodes 3-8:
  00 [7 bytes of padding per slot]

[158 bytes of reserved - all zeros]
```

## Protocol Extensions (Future)

Reserved space allows for:

1. **Node Names** (future_payload in COMMAND or STATUS)
   - Variable-length string (max 174 bytes)
   - Configure at runtime

2. **Sensor Data** (reserved in STATUS)
   - Temperature, humidity, light, motion, etc.
   - 158 bytes available

3. **Error Codes** (reserved in STATUS)
   - Hardware faults, communication errors
   - Allows debugging

4. **Performance Metrics** (reserved in STATUS)
   - Command execution time
   - Memory usage
   - Signal strength

5. **Firmware Updates** (multiple packets)
   - 174-byte payload per packet
   - Sequence in ttl or future field

6. **Configuration** (new packet type)
   - Calibration data
   - Timing parameters
   - Threshold values

## Packet Creation (Python)

```python
import struct

def create_command_packet(node_id, ttl, command, parameter, 
                          constant_commands=None, global_ts=None, cmd_ts=None):
    """Create a 250-byte command packet."""
    if constant_commands is None:
        constant_commands = bytes(12)
    if global_ts is None:
        import time
        global_ts = int(time.time() * 1000) & 0xFFFFFFFF
    if cmd_ts is None:
        cmd_ts = 0
    
    packet = bytearray(250)
    
    # Header
    packet[0] = 0x01  # COMMAND
    packet[1] = node_id
    packet[2] = ttl
    struct.pack_into('<I', packet, 3, global_ts)
    struct.pack_into('<I', packet, 7, cmd_ts)
    packet[11] = command
    packet[12] = parameter
    packet[13:25] = constant_commands[:12]
    packet[25] = 0  # flags
    
    # Rest is zeros (already initialized)
    
    return bytes(packet)

def parse_status_packet(data):
    """Parse a 250-byte status packet."""
    if len(data) < 28:
        return None
    
    status = {
        'type': data[0],
        'node_id': data[1],
        'ttl': data[2],
        'global_timestamp_ms': struct.unpack_from('<I', data, 3)[0],
        'cmd_timestamp_ms': struct.unpack_from('<I', data, 7)[0],
        'command': data[11],
        'parameter': data[12],
        'constant_commands': bytes(data[13:25]),
        'voltage_mv': struct.unpack_from('<H', data, 25)[0],
        'charge_percent': data[27],
        'subnodes': []
    }
    
    # Parse subnodes
    for i in range(8):
        offset = 28 + (i * 8)
        subnode_id = data[offset]
        if subnode_id > 0:
            status['subnodes'].append({
                'id': subnode_id,
                'voltage_mv': struct.unpack_from('<H', data, offset+1)[0],
                'charge_percent': data[offset+3]
            })
    
    return status
```

## Packet Parsing (Python)

```python
def parse_command_packet(data):
    """Parse a 250-byte command packet."""
    if len(data) < 25 or data[0] != 0x01:
        return None
    
    return {
        'type': 'command',
        'node_id': data[1],
        'ttl': data[2],
        'global_timestamp_ms': struct.unpack_from('<I', data, 3)[0],
        'cmd_timestamp_ms': struct.unpack_from('<I', data, 7)[0],
        'command': data[11],
        'parameter': data[12],
        'constant_commands': bytes(data[13:25])
    }
```

## Migration from CSV Protocol

**Old Command:** `1,3,5,237,183,135,21,0,0,0,0,0,0,0,0,0,0,0,0`
**New Command:** 250-byte binary packet (more structured, efficient)

**Old Status:** `3,3.3,85,100,50`
**New Status:** 250-byte binary packet (includes subnodes, proper voltage encoding)

Mapping:
- CSV ttl → binary packet[2]
- CSV node → binary packet[1]
- CSV time_bytes → binary packet[3:7] (proper uint32_le)
- CSV voltage string → binary voltage_mv (uint16_le millivolts)
- CSV charge → binary charge_percent (uint8)

## Size Efficiency

| Field | Bytes | Benefit |
|-------|-------|---------|
| Binary encoding | 250 total | All data in fixed, known structure |
| Struct packing | Optimal | No delimiter parsing overhead |
| Little-endian | Standard | Native on ARM (ESP32) |
| Reserved space | 158 + 174 bytes | Room for 10+ major features |
| 4-byte timestamps | 8 total | Proper uint32 instead of split bytes |
| 2-byte voltage | 2 total | Precision without floating point |

## Reliability Notes

- BEAM handles retransmission
- No CRC needed (ESP-NOW adds MAC layer check)
- Packet type field allows validation
- Reserved bytes enable versioning
- Subnodes optional (unused = 0)
