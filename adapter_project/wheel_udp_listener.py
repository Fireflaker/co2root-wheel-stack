#!/usr/bin/env python3
"""
Simple UDP listener to receive steering data from wheel_sim_bridge.py
Demonstrates how a game would integrate with the wheel.

Run this while wheel_sim_bridge.py is running with --mode udp
"""
import json
import socket
import sys


def main():
    host = "127.0.0.1"
    port = 5005
    
    print(f"[LISTEN] Waiting for steering data on {host}:{port}...")
    print("[INFO]   Move the motor wheel to see live steering updates\n")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    
    try:
        packet_count = 0
        while True:
            data, addr = sock.recvfrom(1024)
            packet = json.loads(data.decode())
            
            packet_count += 1
            steering_norm = packet["steering_angle_norm"]  # -1.0 to +1.0
            angle_raw = packet["steering_angle_raw"]  # 0-65535
            
            # Visual steering indicator
            bar_width = 40
            bar_pos = int((steering_norm + 1.0) / 2.0 * bar_width)
            bar = "░" * bar_width
            bar_list = list(bar)
            bar_list[bar_pos] = "█"
            bar = "".join(bar_list)
            
            # Degrees: 0-360 mapped from angle_raw
            degrees = (angle_raw / 65535.0) * 360.0
            
            # Print update every 10 packets (~160ms)
            if packet_count % 10 == 0:
                print(
                    f"[{packet_count:05d}] "
                    f"Steering: {steering_norm:+.2f} | "
                    f"{degrees:6.1f}° | "
                    f"[{bar}]"
                )
    
    except KeyboardInterrupt:
        print("\n[STOP] Listener stopped")
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
