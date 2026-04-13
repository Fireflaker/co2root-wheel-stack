# Elmo Gold Direct Drive Wheel — Full Wheel-to-Game Toolchain

## Architecture

```
[Game/Sim]
    ↕  DirectInput FFB effects + telemetry
[SimHub]  ←— reads game FFB, outputs over WebSocket (default)
    ↕  WebSocket (ws://127.0.0.1:8888)
[elmo_ffb_bridge.py]  ←— Python bridge (this repo)
    ↕  USB serial (Elmo ASCII protocol)
[Elmo Gold Drive]
    ↕  Motor phases + encoder
[Motor / Steering Wheel]
    ↓  Encoder position
[vJoy virtual HID]  ←— vJoy axis X = steering angle
    ↕  DirectInput axis
[Game/Sim]
```

**Component roles:**
| Component | Role | Install? |
|-----------|------|---------|
| EAS II | One-time drive config (torque mode, limits) | Already installed |
| vJoy | Exposes wheel angle as Windows joystick | Download (free) |
| SimHub | Reads game FFB, outputs to serial | Download (free) |
| elmo_ffb_bridge.py | Bridges everything in real-time | This repo |

---

## Part 1 — EAS II Drive Configuration

**Do this once. These settings survive power-off (saved to NVM).**

### 1.1 Open a Terminal Session in EAS II
- Connect to drive via USB
- In EAS II: **Communication → Terminal**
- All commands below are typed in that terminal followed by Enter

### 1.2 Verify Current Mode
```
UM
```
Note the current value. You will be changing it.

### 1.3 Disable Motor (Safety)
```
MO=0
```

### 1.4 Switch to the Validated Control Mode
```
UM=5
```
> On this COM13 setup, `UM=4` was rejected and `UM=5` was accepted. Use the EAS II **Wizards → Operating Mode** GUI if your drive reports different UM values.

Confirm:
```
UM
```
Response should echo `4` (or whatever mode the wizard selected for current control).

### 1.5 Configure Reference Source
On this drive firmware, `RF` returned unsupported. Use `RM=1` in the runtime script/config so commands are sourced from the host serial session.

### 1.6 Set Steering Angle Limits
Calculate encoder counts per full revolution first. In EAS terminal:
```
EG
```
This prints the encoder resolution (counts/rev). A typical value might be 4096, 8192, or 16384 counts/rev.

For **±2.5 turns** (900° total, common for sim racing):
```
counts_per_rev = EG result
positive_limit = counts_per_rev * 2.5
negative_limit = -positive_limit
```

Set the limits:
```
PL[1]=-204800    (example: 8192 * 2.5 * 10 — adjust to your actual counts)
PL[2]=204800
```
> **Tip:** Start narrow (±1 turn) and increase once everything is functioning.

Enable position limit enforcement:
```
LF=1
```

### 1.7 Set Current Limits
Set peak current to a safe FFB level — **start low**:
```
CL[1]=2          (2A peak — increase gradually once feel is validated)
CL[2]=2
```
Rated current for your 10A drive: never exceed 8–9A for a steering wheel application.

### 1.8 Current Loop Gains
If not already tuned by the Simple Tune wizard, run the current loop auto-tune from EAS II:
- **Wizards → Auto Tune → Current Loop Tune**
- Or leave default values if the motor was already running well.

### 1.9 Save All Settings to Flash
```
BN
```
Drive will reboot. Reconnect in EAS II afterwards and verify `UM` still reads correctly.

### 1.10 Re-enable Motor
After reconnect, confirm settings, then:
```
MO=1
```
The motor is now enabled. On this firmware, direct `TC=` control was rejected in live serial tests; use the adapter PR fallback mode below if `TC=` returns `?;`.

---

## Part 2 — Windows Software Stack

### 2.1 Install vJoy
1. Download: https://github.com/jshafer817/vJoy/releases (latest)
2. Install the driver
3. Run **vJoy Config** (from Start menu):
   - Device 1: enable
   - Axes: enable **X** (steering), **Y** optional (accelerator/brake)
   - Buttons: 32 (in case you want paddle shifters later)
4. Apply and reboot if prompted

Verify with **vJoy Monitor** — the X axis should be movable via the test slider.

### 2.3 Install SimHub
1. Download: https://www.simhubdash.com/
2. Install and launch
3. On first launch, let it auto-detect your installed games

#### Configure SimHub WebSocket Output (Recommended)
1. Open SimHub and go to plugin/settings area where the WebSocket server is configured.
2. Ensure server is enabled on port **8888**.
3. Keep localhost binding so the bridge can connect to **ws://127.0.0.1:8888**.

#### Optional Serial Fallback (Only if you want COM mode)
1. Install com0com and create COM10 ↔ COM11.
2. In SimHub: Controllers and Inputs → Arduino → Custom serial output.
3. Formula: $[ffb]$
4. Start output on COM10; bridge listens on COM11.

### 2.4 Install Python Dependencies
```powershell
& e:\Co2Root\.venv\Scripts\Activate.ps1
pip install pyvjoy pyserial
```
`pyserial` is already installed; `pyvjoy` wraps the vJoy SDK.

---

## Part 3 — elmo_ffb_bridge.py Configuration

### Firmware Note (Important)
- If `TC=<value>` returns `?;` with `EC=21`, use `adapter_project/adapter_main.py` in `pr` command mode (`UM=5`) instead of torque mode.
- Validated motion paths on COM13 were:
    - `UM=2` with `JV/BG` (velocity)
    - `UM=5` with `PA/PR/BG` (position profile)

Edit the top of elmo_ffb_bridge.py to match your system:

```python
ELMO_PORT    = "COM3"                   # Elmo USB serial port
FFB_SOURCE   = "websocket"              # websocket (default), serial, inject
SIMHUB_WS_URL = "ws://127.0.0.1:8888"   # SimHub WebSocket
SIMHUB_PORT  = "COM11"                  # only used if FFB_SOURCE=serial
ELMO_BAUD    = 115200
SIMHUB_BAUD  = 115200

# Steering range in encoder counts (match PL[1]/PL[2] from EAS)
MAX_POSITION_COUNTS = 204800   # ±this many counts = full steering range

# Torque scaling: SimHub outputs ±10000, Elmo TC accepts ±<max_tc>
# Set this to the maximum TC value that feels good without oscillation
MAX_TC = 500   # start at 500, increase carefully

VJOY_DEVICE_ID = 1
```

---

## Part 4 — Running the Toolchain

**Order matters:**
1. Power on Elmo drive, verify MO=1 in EAS terminal
2. Start **vJoy Monitor** (confirm device is active)
3. Start **SimHub** (confirm game detected and WebSocket server enabled)
4. Run the bridge:
   ```powershell
   & e:\Co2Root\.venv\Scripts\Activate.ps1
   python e:\Co2Root\elmo_ffb_bridge.py
   ```
5. Launch your game/sim
6. In game controller settings, select **vJoy Device** as steering axis
7. Calibrate axes in-game

---

## Part 5 — Game-Side Setup

### Assetto Corsa / ACC
- Settings → Controls → select vJoy device
- Steering axis: Axis X
- Steering lock: match to your PL[1]/PL[2] physical range
- FFB gain: start at 50%, adjust

### iRacing
- Use **irFFB** middleware between iRacing and SimHub for best results with direct drive wheels
- Or use SimHub's iRacing support directly

### BeamNG.drive
- Settings → Controls → Steering = vJoy Axis X
- FFB: uses DirectInput, works with SimHub

### Any game with DirectInput support
- The vJoy X axis appears as **Axis X** on **vJoy 1** in any controller mapping screen

---

## Part 6 — Tuning

### FFB Too Strong / Oscillating
1. Reduce `MAX_TC` in bridge config (half it, test again)
2. Reduce `CL[1]` in EAS (motor current limit)
3. In SimHub, reduce overall FFB gain %

### FFB Too Weak / No Feel
1. Increase `MAX_TC` gradually (never exceed ~70% of motor rated current)  
2. Increase SimHub FFB gain

### Steering Center Drift
- `TC=0` should mean zero torque. Check bridge is sending 0 when SimHub FFB = 0.
- If motor creeps at center: check EAS offset parameter `OF` = 0

### Position Lag / Jitter
- Reduce polling interval in bridge (default 5ms / 200Hz is usually fine)
- Check USB serial latency: in Device Manager → COM port → Advanced → uncheck "Allow the computer to manage the port's power"

### Wheel Doesn't Return to Center
- That's normal for torque-mode direct drive — the game's FFB spring effect handles centering
- In SimHub, make sure "Spring" effect is enabled

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Drive shows safety fault | STO not asserted | Check STO wiring per `ELMO_GOLD_200V_10A_STO_WIRING.md` |
| `TC=` command ignored | Not in torque mode | Re-check `UM=4` in EAS terminal |
| vJoy axis not moving | pyvjoy not finding device | Run vJoy Config, set Device 1 enabled |
| No FFB from SimHub | Wrong COM port | Check com0com pair assignment |
| Motor oscillates wildly | MAX_TC too high | Halve it immediately, run `TC=0` |
| Game doesn't see wheel | vJoy not calibrated | Open Game Controllers in Windows, calibrate vJoy 1 |
