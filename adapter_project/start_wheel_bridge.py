#!/usr/bin/env python3
"""
Quick-start launcher for racing sim wheel bridge.
Choose game type and auto-configures the best output mode.
"""
import sys
import subprocess
import os


PYTHON_EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable


GAMES = {
    "1": {
        "name": "iRacing",
        "mode": "vjoy",
        "note": "Requires vJoy installed"
    },
    "2": {
        "name": "rFactor 2",
        "mode": "vjoy",
        "note": "DirectInput device"
    },
    "3": {
        "name": "Assetto Corsa",
        "mode": "vjoy",
        "note": "Auto-detects vJoy"
    },
    "4": {
        "name": "Assetto Corsa Competizione",
        "mode": "vjoy",
        "note": "Console port compatibility"
    },
    "5": {
        "name": "BeamNG.drive",
        "mode": "vjoy",
        "note": "Full force feedback support"
    },
    "6": {
        "name": "Custom Game (UDP)",
        "mode": "udp",
        "note": "Listen on 127.0.0.1:5005"
    },
    "7": {
        "name": "Test Listener (Show data)",
        "mode": "listener",
        "note": "Visualize steering in terminal"
    },
}


def print_menu():
    print("\n" + "="*60)
    print("  RACING SIM WHEEL BRIDGE - QUICK START")
    print("="*60)
    print("\nSelect your racing game:\n")
    for key, game in GAMES.items():
        print(f"  {key}) {game['name']:<30} ({game['note']})")
    print("\n  0) Exit\n")


def check_vjoy():
    """Check if vJoy is available."""
    try:
        import pyvjoy
        return True
    except ImportError:
        return False


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print_menu()
    choice = input("Enter choice (0-7): ").strip()
    
    if choice == "0":
        print("Exiting.")
        return 0
    
    if choice not in GAMES:
        print("[ERROR] Invalid choice")
        return 1
    
    game_config = GAMES[choice]
    game_name = game_config["name"]
    mode = game_config["mode"]
    
    print(f"\n{'='*60}")
    print(f"Starting: {game_name}")
    print(f"{'='*60}\n")
    
    if mode == "vjoy":
        if not check_vjoy():
            print("[ERROR] vJoy not installed!")
            print("[INFO] Install from: https://sourceforge.net/projects/vjoystick/")
            print("[INFO] Then: pip install pyvjoy")
            return 1
        
        print(f"[INFO] Launching vJoy mode for {game_name}")
        print("[INFO] Game should auto-detect vJoy device as gamepad\n")
        
        cmd = [PYTHON_EXE, "wheel_sim_bridge.py", "--mode", "vjoy"]
    
    elif mode == "udp":
        print(f"[INFO] UDP mode - game listens on 127.0.0.1:5005")
        print("[INFO] Steering packets: {steering_angle_norm: -1.0 to +1.0}\n")
        
        cmd = [PYTHON_EXE, "wheel_sim_bridge.py", "--mode", "udp"]
    
    elif mode == "listener":
        print("[INFO] Starting test listener - shows live steering data\n")
        cmd = [PYTHON_EXE, "wheel_udp_listener.py"]
    
    print("[CONNECT] Motor encoder on COM13 @ 115200 baud")
    print("[OUTPUT] Streaming at 600+ Hz")
    print("[SAFETY] Bridge defaults to motor disabled (MO=0).")
    print("[PRESS]  Ctrl+C to stop\n")
    
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\n[STOP] Bridge stopped")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
