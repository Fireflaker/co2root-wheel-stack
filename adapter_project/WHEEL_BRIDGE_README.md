# Racing Sim Wheel Bridge - Setup Guide

## Overview
Connects Elmo servo motor encoder to racing sim games. Outputs steering angle via vJoy (universal) or UDP (network).

## Quick Start

### Option 1: vJoy (Recommended for Windows sims)
```bash
# Install vJoy first
pip install pyvjoy

# Run bridge
python wheel_sim_bridge.py --mode vjoy
```

Most racing sims (iRacing, rFactor2, Assetto Corsa, ACC) will auto-detect vJoy as a gamepad.

### Option 2: UDP (Network output)
```bash
# Run on local network - sends JSON packets
python wheel_sim_bridge.py --mode udp --udp-host 127.0.0.1 --udp-port 5005
```

Your sim can listen on 127.0.0.1:5005 for steering data.

---

## Integration Examples

### iRacing with vJoy
1. Install vJoy from `https://sourceforge.net/projects/vjoystick/`
2. Run `wheel_sim_bridge.py --mode vjoy`
3. In iRacing, go Simulation > Wheel Settings
4. Assign vJoy device as steering input
5. Motor encoder now controls steering wheel in-game

### UDP Receiver (Python game mod)
```python
import socket
import json

def listen_steering():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 5005))
    
    while True:
        data, _ = sock.recvfrom(1024)
        packet = json.loads(data.decode())
        
        steering_angle = packet["steering_angle_norm"]  # -1.0 to +1.0
        print(f"Steering: {steering_angle:.3f}")
        
        # Update your game physics here
```

### SimHub Integration (if available)
SimHub can listen to UDP and route to telemetry overlay:
```
SimHub → UDP Input → Parse JSON → Display steering indicator
```

---

## Output Format

### vJoy Mode
- Joystick axis X (steering): 0-32767 (left-center-right)
- Auto-detected by most DirectInput/XInput games

### UDP Mode
Each packet (60Hz):
```json
{
  "timestamp": 1712973600.123,
  "steering_angle_norm": 0.45,
  "steering_angle_raw": 41943,
  "encoder_counts": -162700000
}
```

- `steering_angle_norm`: -1.0 = hard left, 0.0 = center, +1.0 = hard right
- `steering_angle_raw`: 0-65535 (direct 16-bit mapped to 360°)
- `encoder_counts`: raw motor encoder position

---

## Troubleshooting

**vJoy not detected:**
- Ensure vJoy is installed and running: `https://sourceforge.net/projects/vjoystick/`
- Check Device Manager: should show "vJoy Device"
- Verify game recognizes it: Game Controller settings

**UDP packets not arriving:**
- Check firewall isn't blocking UDP 5005
- Test with: `netstat -an | find "5005"`
- Verify receiving app is listening on same port

**Steering oscillating/jittery:**
- Motor encoder noise - add 5Hz LPF smoothing
- Check serial baud rate: must be 115200
- Verify motor power supply is stable

---

## Advanced: Custom Forces (Haptic Feedback)

For force feedback back to motor:
```python
# In wheel_sim_bridge.py, add FFB listener:
class FFBListener:
    def receive_force(self, force_newtons):
        # force_newtons: -100 to +100
        # Convert to TC (torque command)
        tc_value = int(force_newtons * 2.5)  # Scale to Elmo range
        ser.write(f"TC={tc_value}\r".encode())
```

This enables:
- Road feel feedback (bumps, curbs)
- Collision impacts
- Wheel spin slip feedback
- Tire load sensing

---

## Files

- `wheel_sim_bridge.py` - Main bridge (vJoy/UDP output)
- `wheel_poller_1khz_fast.py` - Encoder polling (alternate standalone mode)
- `encoder_roundtrip_loop_v2.py` - Validation/testing loop

## Performance

- Polling rate: 600+ Hz (serial limited at 115200 baud)
- Latency: ~2-5ms end-to-end
- Steering resolution: 16-bit (65,536 positions per 360°)

Suitable for all consumer racing sims.
