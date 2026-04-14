from __future__ import annotations

import json
from pathlib import Path


STATE_PATH = Path(__file__).resolve().parent / "runtime" / "vjoy_input_state.json"


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def pedal_to_vjoy_axis(value: float) -> int:
    # LFS interprets the low end of these pedal axes as fully pressed.
    # Expose GUI semantics instead: 0.0 = released, 1.0 = fully pressed.
    return max(0, min(32767, int(round((1.0 - clamp_unit(value)) * 32767.0))))


def released_pedal_vjoy_axis() -> int:
    return pedal_to_vjoy_axis(0.0)


def load_input_state() -> dict[str, float]:
    if not STATE_PATH.exists():
        return {"throttle": 0.0, "brake": 0.0}

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"throttle": 0.0, "brake": 0.0}

    return {
        "throttle": clamp_unit(float(data.get("throttle", 0.0))),
        "brake": clamp_unit(float(data.get("brake", 0.0))),
    }


def save_input_state(throttle: float, brake: float) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "throttle": clamp_unit(throttle),
        "brake": clamp_unit(brake),
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="ascii")