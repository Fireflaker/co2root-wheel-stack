# Motor Encoder → Game Integration - Technical Reference

## Architecture Diagram

```
┌─────────────────────────────────┐
│  Motor Encoder (Elmo Gold)      │
│  COM13 @ 115200 baud            │
│  131,072 counts/revolution      │
└──────────────┬──────────────────┘
               │
               ↓ (QueryPX)
┌─────────────────────────────────┐
│  wheel_sim_bridge.py            │
│  • Poll encoder 620+ Hz          │
│  • Convert to 16-bit angle      │
│  • Map to steering axis         │
└──────────┬────────────┬─────────┘
           │            │
        vJoy           UDP
           │            │
    ┌──────↓────┐   ┌───↓──────────┐
    │ Windows   │   │ Network/Mod  │
    │ DirectInput   │ Games         │
    └──────┬────┘   └───┬──────────┘
           │            │
    ┌──────↓────────────↓──────┐
    │   iRacing, rF2, AC, etc  │
    │   Steering Wheel Input   │
    └──────────────────────────┘
```

---

## Data Format

### Raw Encoder Query
```powershell
# Query motor position
Command: PX
Response: ">PX\r\n-162889540;\r\n>"
Result: pos = -162889540 (arbitrary offset, deltas matter)
```

### Converted Streaming Data (UDP)
```json
{
  "timestamp": 1712973600.123,
  "steering_angle_norm": -0.21,
  "steering_angle_raw": 25619,
  "encoder_counts": -162889540
}
```

### Mapping Reference

| Raw Counts | Angle (°) | 16-bit Value | Steering (%) |
|-----------|-----------|------------|-------------|
| -131072   | -180°     | 32768      | -100% (left) |
| -65536    | -90°      | 49152      | -50% |
| 0         | 0°        | 0          | 0% (center) |
| 65536     | +90°      | 16384      | +50% |
| 131072    | +180°     | 65535      | +100% (right) |

**Formula:**
```
angle_16bit = (raw_counts >> 5) & 0xFFFF
steering_norm = (angle_16bit / 65535.0) * 2.0 - 1.0
degrees = (angle_16bit / 65535.0) * 360.0
```

---

## Implementation Modes

### Mode 1: vJoy (Virtual Gamepad)
**Best for:** iRacing, rFactor2, Assetto Corsa, BeamNG

**How it works:**
```
Motor → wheel_sim_bridge.py (vJoy mode)
  ↓
Updates vJoy Axis X (0-32767)
  ↓
Windows DirectInput Layer
  ↓
Game detects "vJoy Device" as steering wheel
  ↓
Game applies steering to simulation
```

**Advantages:**
- ✅ Native support in all major sims
- ✅ No game modification needed
- ✅ Plug-and-play after vJoy install
- ✅ Force feedback capable

**File:** `wheel_sim_bridge.py --mode vjoy`

---

### Mode 2: UDP Network
**Best for:** Custom mods, network sims, visualization

**How it works:**
```
Motor → wheel_sim_bridge.py (UDP mode)
  ↓
Broadcasts JSON packets on 127.0.0.1:5005
  ↓
Any application listens on UDP 5005
  ↓
Game/mod receives steering packets
  ↓
Game applies to physics engine
```

**Advantages:**
- ✅ No external dependencies
- ✅ Works across network
- ✅ Transparent packet inspection
- ✅ Easy mod integration

**Packet Structure:**
```python
{
    "timestamp": float,              # Unix timestamp
    "steering_angle_norm": float,    # -1.0 to +1.0
    "steering_angle_raw": int,       # 0-65535
    "encoder_counts": int            # Raw motor counts
}
```

**File:** `wheel_sim_bridge.py --mode udp`

---

## Game Integration Examples

### iRacing with vJoy
```
1. Launch wheel_sim_bridge.py --mode vjoy
2. Open iRacing
3. Options → Game → Wheel Controller
4. Select "vJoy Device" as steering input
5. Calibrate (full left, center, full right)
6. Drive!
```

### Custom SimulinkUnity Game (UDP)
```csharp
// C# Unity example
using System.Net;
using System.Net.Sockets;

class SteeringInput {
    UdpClient client = new UdpClient(5005, AddressFamily.InterNetwork);
    
    void Update() {
        try {
            var result = client.ReceiveAsync().Result;
            string json = System.Text.UTF8Encoding.UTF8.GetString(result.Buffer);
            
            // Parse JSON and extract steering_angle_norm
            float steeringNorm = ParseJson(json)["steering_angle_norm"];
            
            // Apply to physics
            rigidbody.velocity += Vector3.right * steeringNorm * maxTorque;
        } catch {}
    }
}
```

### Mod Telemetry (Python)
```python
import socket
import json

class MotorInput:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 5005))
        self.steering = 0.0
    
    def update(self):
        try:
            data, _ = self.sock.recvfrom(1024)
            packet = json.loads(data)
            self.steering = packet["steering_angle_norm"]
        except:
            pass
        
        return self.steering
```

---

## Serial Protocol (Reference)

### Query Commands
| Command | Response | Meaning |
|---------|----------|---------|
| `PX` | `value;` | Query position (encoder counts) |
| `MO` | `value;` | Motor output status (0=off, 1=on) |
| `UM` | `value;` | Units mode (5=position reference) |
| `ER` | `code;` | Error code (0=no error) |

### Control Commands
| Command | Effect |
|---------|--------|
| `MO=1` | Enable motor output |
| `MO=0` | Disable motor output |
| `ST` | Stop motor (decelerate) |
| `TC=0` | Zero torque command |
| `PR=±131072` | Set position reference (±1 rev) |
| `BG` | Begin motion (in PR/VL mode) |

---

## Performance Tuning

### Increase Polling Rate
**Challenge:** 115200 baud serial limits to ~600 Hz  
**Solution:** Use USB-RS485 adapter at 921600 baud
```bash
# Edit wheel_sim_bridge.py:
ser = serial.Serial(args.port, 921600, timeout=0.01)
# Achieves ~1000+ Hz
```

### Reduce Latency
```python
# Edit polling worker:
ser.write(b"PX\r")
ser.flush()
time.sleep(0.0002)  # Reduce from 0.0005 for faster response
```

### Smooth Steering
```python
# Add LPF (low-pass filter) to steering output
def smooth_steering(new_val, old_val, alpha=0.9):
    return old_val * alpha + new_val * (1 - alpha)
```

---

## Diagnostics

### Check Motor Connection
```bash
python wheel_udp_listener.py
# Should show live steering angle updating
```

### Monitor UDP Stream
```bash
# On Windows (requires nmap-ncat)
nc -u -l 127.0.0.1 5005
# Receive raw packets
```

### Verify vJoy Detection
```bash
python -c "import pyvjoy; j = pyvjoy.VJoyDevice(1); print(j)"
# Should show joystick state
```

---

## Troubleshooting Decision Tree

```
Motor not steering in game?
├─ Check motor is powered
│  └─ Run: python wheel_udp_listener.py
│     └─ If steering shows: vJoy issue
│     └─ If no output: Motor/bridge issue
│
├─ Check vJoy installed
│  └─ Run: python -c "import pyvjoy"
│     └─ If error: Install vJoy + pyvjoy
│
└─ Check game controller mapping
   └─ In game: Settings → Input
      └─ Verify vJoy appears in device list
      └─ Assign steering axis to vJoy X
```

---

## References

- **vJoy Project:** https://sourceforge.net/projects/vjoystick/
- **pyvjoy Library:** https://github.com/r4dian/pyvjoy
- **Elmo Gold Command Reference:** See elmo_com13_command_findings.md
- **UDP Socket Programming:** Python `socket` module docs
- **Steering Wheel Standard:** SAE J2030 (±540° steering range = ±1.0 normalized)

---

*Technical Reference - Motor-to-Game Integration*  
*Last Updated: April 12, 2026*
