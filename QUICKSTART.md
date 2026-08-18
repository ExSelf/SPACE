# SPACE MIDI Bridge - Quick Start Guide

## 5-Minute Setup

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Connect Hardware
- Connect BEAM controller to computer via USB
- Power on SUN nodes
- Open DAW and enable MIDI output

### 3. Start the App
```bash
python main.py
```

### 4. Configure
1. Select your MIDI input port from "MIDI input" dropdown
2. Select the serial port for BEAM controller (usually COM port on Windows)
3. Set TTL slider to 3 (default is fine for most setups)
4. Click **Start**

### 5. Test
1. Play a MIDI note in your DAW
2. Watch the "Node 1" entry in the tree update with:
   - Sent command (Cmd column)
   - Node's actual execution state (Actual Cmd column)
3. Status updates should appear in the log

## Understanding TTL

**TTL (Time-To-Live)** controls how far commands travel through the wireless mesh:

| TTL | Reach | Best For |
|-----|-------|----------|
| 1-2 | Direct only | Nodes close to BEAM controller |
| 3-5 | Medium range | Typical multi-room setups |
| 6-8 | Long range | Large buildings |
| 9-12 | Maximum | Ensure remote nodes are reached |

**Default: 3** - works for most setups

## Assigning Nodes to MIDI Channels

By default, all nodes listen to all MIDI channels. To change this:

1. Select a node in the tree view
2. In the "Node channels" panel, check which MIDI channels control that node
3. Settings are saved automatically

**Example:**
- Node 1 "Front Light" → Check only "Ch 1"
- Node 2 "Back Light" → Check only "Ch 2"
- Now MIDI channel 1 only controls Front Light

## What the Tree View Shows

```
Node │ Name        │ Cmd │ Actual Cmd │ Param │ Actual Param │ Voltage │ Charge
─────┼─────────────┼─────┼────────────┼───────┼──────────────┼─────────┼────────
1    │ Front Light │ 100 │ 100        │ 50    │ 50           │ 3.3V    │ 85%
2    │ Back Light  │ 60  │ 0          │ 30    │ 0            │ 3.1V    │ 92%
```

- **Cmd** = Last command sent from DAW
- **Actual Cmd** = What node is currently executing
- **Param** = Last parameter value sent
- **Actual Param** = Current parameter on node
- **Voltage** = Node's power supply voltage
- **Charge** = Battery percentage (if battery-powered)

## Troubleshooting

### "No MIDI ports detected"
- Ensure DAW is running and has MIDI output enabled
- On Windows, try opening Device Manager to check USB driver
- Restart the app

### "No serial ports detected"
- Check USB cable between computer and BEAM controller
- Install USB-to-Serial driver if needed
- Try a different USB port
- Restart the app

### Nodes not responding
- Increase TTL to 8-10
- Check that node names are correctly configured in `node_settings.json`
- Verify nodes have power
- Check BEAM controller is powered and connected

### Status shows zeros or doesn't update
- Verify MIDI channel assignments (node must listen to the channel you're using)
- Check that MIDI is actually being sent from DAW
- Try with a different MIDI channel
- Increase TTL value

## MIDI Note Example

**DAW sends:** MIDI Note On, Channel 1, Note 60, Velocity 100

**SPACE bridge translates to:**
```
Node: 1 (Channel 0 + 1)
Command: 60 (the note number)
Parameter: 100 (the velocity)
TTL: 3 (slider value)
```

**Sends packet:** `1,3,1,237,183,135,21,0,0,0,0,0,0,0,0,0,0,0,0`

**Node 1 receives it and executes** command=60 with parameter=100

## File Locations

- **Log:** Check the text area in the app (all activity logged there)
- **Settings:** `node_settings.json` in the same folder as main.py
- **Config:** `space/config.py` for serial port defaults

## Customization

### Change Default TTL
Edit the slider value in the UI, or modify `space/packet.py` default in `midi_to_packet()` function.

### Change Baud Rate
Edit `space/config.py`:
```python
BAUD_RATE = 115200  # Change this if your BEAM uses different rate
```

### Add More Nodes
Edit `node_settings.json` to add nodes 1-255 with custom names.

## Performance Tips

1. **High Status Update Rate:** Nodes send status 10-100 times per second
   - Normal and expected (shows real-time feedback)
   - Don't log every update (will slow UI)

2. **Large Networks:** With many nodes (50+)
   - Status updates may not display every 10ms
   - UI refresh is throttled automatically
   - Communication is still real-time

3. **Range Issues:**
   - If nodes miss commands, increase TTL by 2-3 hops
   - If commands get stuck in mesh, decrease TTL
   - Normal range without obstacles: ~100m per hop

## Next Steps

1. Read [BEAM Protocol Reference](BEAM_PROTOCOL.md) for protocol details
2. Read [API Reference](API_REFERENCE.md) to extend the bridge programmatically
3. Check `tests/` folder for usage examples

## Support

- For BEAM issues: https://github.com/ExSelf/BEAM
- For SUN firmware: https://github.com/ExSelf/SUN
- For legacy reference: https://github.com/ExSelf/MIDI-Bridge-legacy
