#!/usr/bin/env python3
"""Direct control verification for Adapter project on Elmo COM port."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from elmo_transport import build_elmo_client


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--transport", choices=["serial", "ethercat"], default="serial")
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--ethercat-adapter-match", default="Realtek Gaming USB 2.5GbE Family Controller")
    p.add_argument("--ethercat-slave-index", type=int, default=1)
    p.add_argument("--tc", type=int, default=140)
    p.add_argument("--hold-ms", type=int, default=250)
    p.add_argument("--json-out", default="")
    p.add_argument("--leave-enabled", action="store_true")
    args = p.parse_args()

    cfg = {
        "elmo_transport": args.transport,
        "elmo_port": args.port,
        "elmo_baud": args.baud,
        "ethercat_adapter_match": args.ethercat_adapter_match,
        "ethercat_slave_index": args.ethercat_slave_index,
        "ethercat_profile_velocity": 120000,
        "ethercat_profile_acceleration": 250000,
        "ethercat_profile_deceleration": 250000,
        "serial_timeout_s": 0.2,
    }

    result = {
        "transport": args.transport,
        "port": args.port,
        "baud": args.baud,
        "ethercat_adapter_match": args.ethercat_adapter_match,
        "ethercat_slave_index": args.ethercat_slave_index,
        "tc": args.tc,
        "mo": None,
        "px_before": None,
        "px_after": None,
        "px_delta": None,
        "pass": False,
    }

    client = build_elmo_client(cfg)
    client.open()
    try:
        try:
            details = client.describe()
            result.update({f"detail_{key}": value for key, value in details.items()})
        except Exception:
            pass

        mo = client.get_mo()
        if mo != 1:
            client.set_motor_on()
            time.sleep(0.08)
            mo = client.get_mo()
        result["mo"] = mo

        px_before = client.get_px()
        result["px_before"] = px_before

        # Small bidirectional pulse for safe movement proof.
        client.set_tc(args.tc)
        time.sleep(args.hold_ms / 1000.0)
        client.set_tc(-args.tc)
        time.sleep(args.hold_ms / 1000.0)
        client.set_tc(0)
        time.sleep(0.1)

        px_after = client.get_px()
        result["px_after"] = px_after

        if not args.leave_enabled:
            client.set_tc(0)
            client.stop_motion()
            client.set_motor_off()
    finally:
        client.close()

    if px_before is not None and px_after is not None:
        result["px_delta"] = abs(px_after - px_before)
        result["pass"] = result["px_delta"] >= 100

    print(json.dumps(result, indent=2))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="ascii")

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
