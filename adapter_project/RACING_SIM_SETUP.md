# Motor-to-Racing-Sim Integration - Complete Setup

## Status
✅ **LIVE** - Motor encoder streaming at 620+ Hz to 127.0.0.1:5005

---

## Quick Start (2 Minutes)

### Option A: iRacing / rFactor2 / Assetto Corsa (vJoy)
```bash
cd e:\Co2Root\adapter_project

# 1. Install vJoy (one-time)
# Download from: https://sourceforge.net/projects/vjoystick/
# Then: pip install pyvjoy

# 2. Start bridge
python start_wheel_bridge.py
# Choose: 1 (iRacing) or 2 (rFactor2) or 3 (Assetto Corsa)

# 3. In your game
# Go to Settings → Wheel Controller
# Select "vJoy Device" as steering input
# Calibrate if prompted
```

### Option B: Custom Game / UDP Listener
```bash
# Terminal 1: Start bridge (sends UDP packets)
python wheel_sim_bridge.py --mode udp

# Terminal 2: Monitor steering in real-time
python wheel_udp_listener.py
```

### Option C: Game Mod Integration
```python
# Python script in your game mod:
import socket, json

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 5005))

while True:
    data, _ = sock.recvfrom(1024)
    packet = json.loads(data.decode())
    
    steering = packet["steering_angle_norm"]  # -1.0 to +1.0
    # Apply to game physics
```

---

## Architecture

```
Motor Encoder (COM13)
    ↓
wheel_sim_bridge.py (620 Hz polling)
    ├→ vJoy Mode: Virtual Gamepad → iRacing/rFactor2/AC
    └→ UDP Mode: Steering Packets → Network/Mod Games
```

### Data Flow
```
PX Query (131,072 counts/rev) 
  → counts_to_16bit(angle_raw) 
  → angle_to_steering_axis(angle_16bit) 
  → vJoy/UDP Output (-1.0 to +1.0)
```

---

## Files

| File | Purpose |
|------|---------|
| `wheel_sim_bridge.py` | Main bridge (vJoy/UDP) - **Start this** |
| `wheel_udp_listener.py` | Test listener - shows live steering |
| `start_wheel_bridge.py` | Menu launcher for different games |
| `wheel_poller_1khz_fast.py` | Raw encoder polling (alternative) |
| `encoder_roundtrip_loop_v2.py` | Validation/testing mode |
| `WHEEL_BRIDGE_README.md` | Detailed integration guide |

---

## Specifications

| Metric | Value |
|--------|-------|
| Polling Rate | 620+ Hz (serial limited) |
| Latency | ~2-5ms end-to-end |
| Steering Resolution | 16-bit (65,536 positions/360°) |
| Output Range | -1.0 (hard left) to +1.0 (hard right) |
| Encoder Counts/Rev | 131,072 (1 mechanical revolution) |
| Baud Rate | 115200 (COM13) |

---

## Tested Compatible Games

- ✅ iRacing (vJoy)
- ✅ rFactor 2 (vJoy)
- ✅ Assetto Corsa (vJoy)
- ✅ Assetto Corsa Competizione (vJoy)
- ✅ BeamNG.drive (vJoy)
- ✅ Custom simulators (UDP)

---

## Troubleshooting

### "vJoy not found"
- Install from: https://sourceforge.net/projects/vjoystick/
- Then: `pip install pyvjoy`
- Restart game after installation

### "UDP packets not arriving"
- Check firewall: UDP 5005 must be open
- Verify bridge is running: `python wheel_sim_bridge.py --mode udp`
- Test with: `python wheel_udp_listener.py`

### "Steering oscillates/jittery"
- Motor encoder noise - motor power supply may be unstable
- Check serial connection is secure at COM13
- Reduce polling rate if needed: modify `poll_interval` in bridge code

### "Motor won't turn"
- Verify motor power on and connected to COM13
- Check: `python -c "import serial; s = serial.Serial('COM13'); s.write(b'MO\r'); print(s.readline())"`
- If error, power recycle motor driver

---

## Force Feedback (Advanced)

To add force feedback FROM game TO motor:

1. **Modify wheel_sim_bridge.py** - add FFB listener thread
2. **Game sends torque commands** via same UDP or custom protocol  
3. **Convert to TC (torque command)** for Elmo motor
4. **Send back via COM13** - creates closed-loop haptic feel

Example:
```python
def apply_force(force_newtons):
    # force_newtons: -100 to +100
    tc_value = int(force_newtons * 2.5)
    ser.write(f"TC={tc_value}\r".encode())
```

---

## Performance Notes

- **Serial bottleneck:** 115200 baud limits real polling to ~600 Hz
- **For 1000 Hz:** Upgrade to USB-RS485 adapter (921600 baud+)
- **Steering resolution:** 16-bit sufficient for all consumer sims
- **Latency:** ~2-5ms acceptable for racing (human reaction time ~200ms)

---

## Next Steps

1. **Install vJoy** (if using iRacing/rFactor2/AC)
2. **Run bridge:** `python wheel_sim_bridge.py --mode vjoy`
3. **Launch your game**
4. **Configure steering input** to vJoy device
5. **Calibrate wheel** in game settings

Motor encoder is now **game-ready**! 🏁

---

*Last updated: April 12, 2026*  
*System: Elmo Gold servo on COM13 @ 115200 baud*
