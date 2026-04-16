from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import serial
except Exception:  # pragma: no cover
    serial = None


def parse_last_int(text: str) -> Optional[int]:
    nums = re.findall(r"-?\d+", text or "")
    if not nums:
        return None
    return int(nums[-1])


def response_indicates_elmo_error(text: str) -> bool:
    return "?;" in (text or "")


@dataclass(slots=True)
class EthercatSlaveInfo:
    slave_index: int
    name: str
    vendor_id: int
    product_code: int
    revision: int
    serial_number: int | None
    device_name: str | None
    hardware_version: str | None
    software_version: str | None


class BaseElmoClient:
    def open(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def get_mo(self) -> Optional[int]:  # pragma: no cover - interface only
        raise NotImplementedError

    def get_px(self) -> Optional[int]:  # pragma: no cover - interface only
        raise NotImplementedError

    def get_ec(self) -> Optional[int]:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_motor_on(self) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_motor_off(self) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_tc(self, tc: int) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_il(self, il: int) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_um(self, um: int) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_rm(self, rm: int) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def set_pr(self, pr: int) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def begin_motion(self) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def stop_motion(self) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {}


class SerialElmoClient(BaseElmoClient):
    def __init__(self, port: str, baud: int, timeout_s: float = 0.008):
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
        self.ser: Optional[serial.Serial] = None

    def open(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        self.ser = serial.Serial(self.port, self.baud, timeout=max(0.001, float(self.timeout_s)))
        time.sleep(0.05)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

    def send(self, cmd: str, wait: float = 0.001) -> str:
        assert self.ser is not None
        self.ser.write((cmd + "\r").encode("ascii"))
        self.ser.flush()
        time.sleep(wait)
        raw = self.ser.read(self.ser.in_waiting or 128)
        return raw.decode("ascii", errors="replace").strip()

    def get_mo(self) -> Optional[int]:
        return parse_last_int(self.send("MO"))

    def get_px(self) -> Optional[int]:
        return parse_last_int(self.send("PX"))

    def get_ec(self) -> Optional[int]:
        return parse_last_int(self.send("EC"))

    def set_motor_on(self) -> str:
        return self.send("MO=1")

    def set_motor_off(self) -> str:
        return self.send("MO=0")

    def set_tc(self, tc: int) -> str:
        return self.send(f"TC={tc}", wait=0.0)

    def set_il(self, il: int) -> str:
        return self.send(f"IL={il}", wait=0.0)

    def set_um(self, um: int) -> str:
        return self.send(f"UM={int(um)}")

    def set_rm(self, rm: int) -> str:
        return self.send(f"RM={int(rm)}")

    def set_pr(self, pr: int) -> str:
        return self.send(f"PR={int(pr)}", wait=0.0)

    def begin_motion(self) -> str:
        return self.send("BG", wait=0.0)

    def stop_motion(self) -> str:
        return self.send("ST", wait=0.0)

    def describe(self) -> dict[str, Any]:
        return {"transport": "serial", "port": self.port, "baud": self.baud}


class EthercatElmoClient(BaseElmoClient):
    MODE_PROFILE_POSITION = 1
    MODE_PROFILE_VELOCITY = 3
    MODE_PROFILE_TORQUE = 4
    MODE_CSP = 8
    MODE_CSV = 9
    MODE_CST = 10

    def __init__(
        self,
        adapter_match: str,
        slave_index: int,
        profile_velocity: int,
        profile_acceleration: int,
        profile_deceleration: int,
        pysoem_module: Any | None = None,
    ):
        self.adapter_match = adapter_match
        self.slave_index = max(1, int(slave_index))
        self.profile_velocity = int(profile_velocity)
        self.profile_acceleration = int(profile_acceleration)
        self.profile_deceleration = int(profile_deceleration)
        self._pysoem = pysoem_module
        self.master = None
        self.slave = None
        self.adapter_name = ""
        self.adapter_desc = ""
        self.target_position = 0
        self.last_um = 0
        self.last_rm = 0

    def _module(self):
        if self._pysoem is not None:
            return self._pysoem
        import pysoem

        self._pysoem = pysoem
        return pysoem

    def _find_adapter(self) -> tuple[str, str]:
        pysoem = self._module()
        for adapter in pysoem.find_adapters():
            desc = adapter.desc.decode(errors="replace") if isinstance(adapter.desc, (bytes, bytearray)) else str(adapter.desc)
            if self.adapter_match in desc or self.adapter_match in str(adapter.name):
                return adapter.name, desc
        raise RuntimeError(f"EtherCAT adapter not found: {self.adapter_match}")

    def open(self) -> None:
        pysoem = self._module()
        self.adapter_name, self.adapter_desc = self._find_adapter()
        self.master = pysoem.Master()
        self.master.open(self.adapter_name)
        count = self.master.config_init()
        if count < self.slave_index:
            self.master.close()
            raise RuntimeError(f"EtherCAT slave index {self.slave_index} not present; found {count} slaves")
        self.slave = self.master.slaves[self.slave_index - 1]
        self.target_position = self.get_px() or 0
        self._configure_profile_defaults()

    def close(self) -> None:
        if self.master is not None:
            try:
                self.master.close()
            finally:
                self.master = None
                self.slave = None

    def _require_slave(self):
        if self.slave is None:
            raise RuntimeError("EtherCAT drive is not open")
        return self.slave

    def _read(self, index: int, subindex: int = 0) -> bytes:
        slave = self._require_slave()
        return slave.sdo_read(index, subindex)

    def _write(self, index: int, subindex: int, payload: bytes) -> None:
        slave = self._require_slave()
        slave.sdo_write(index, subindex, payload)

    def _read_i8(self, index: int, subindex: int = 0) -> int:
        return int.from_bytes(self._read(index, subindex)[:1], byteorder="little", signed=True)

    def _read_u16(self, index: int, subindex: int = 0) -> int:
        return struct.unpack("<H", self._read(index, subindex)[:2])[0]

    def _read_i16(self, index: int, subindex: int = 0) -> int:
        return struct.unpack("<h", self._read(index, subindex)[:2])[0]

    def _read_i32(self, index: int, subindex: int = 0) -> int:
        return struct.unpack("<i", self._read(index, subindex)[:4])[0]

    def _read_u32(self, index: int, subindex: int = 0) -> int:
        return struct.unpack("<I", self._read(index, subindex)[:4])[0]

    def _write_i8(self, index: int, value: int, subindex: int = 0) -> None:
        self._write(index, subindex, int(value).to_bytes(1, byteorder="little", signed=True))

    def _write_u16(self, index: int, value: int, subindex: int = 0) -> None:
        self._write(index, subindex, struct.pack("<H", int(value) & 0xFFFF))

    def _write_i16(self, index: int, value: int, subindex: int = 0) -> None:
        self._write(index, subindex, struct.pack("<h", int(value)))

    def _write_i32(self, index: int, value: int, subindex: int = 0) -> None:
        self._write(index, subindex, struct.pack("<i", int(value)))

    def _write_u32(self, index: int, value: int, subindex: int = 0) -> None:
        self._write(index, subindex, struct.pack("<I", int(value) & 0xFFFFFFFF))

    def _statusword(self) -> int:
        return self._read_u16(0x6041, 0x00)

    def _controlword(self) -> int:
        return self._read_u16(0x6040, 0x00)

    def _write_controlword(self, value: int) -> None:
        self._write_u16(0x6040, value, 0x00)

    def _mode_display(self) -> int:
        return self._read_i8(0x6061, 0x00)

    def _set_mode(self, mode: int) -> None:
        current_mode = self._read_i8(0x6060, 0x00)
        if current_mode != mode:
            self._write_i8(0x6060, mode, 0x00)
        display_mode = self._mode_display()
        if display_mode != mode:
            raise RuntimeError(f"EtherCAT mode change failed: requested {mode}, display {display_mode}")

    def _configure_profile_defaults(self) -> None:
        try:
            self._write_u32(0x6081, max(1, self.profile_velocity), 0x00)
            self._write_u32(0x6083, max(1, self.profile_acceleration), 0x00)
            self._write_u32(0x6084, max(1, self.profile_deceleration), 0x00)
        except Exception:
            return

    def _reset_fault_if_present(self) -> None:
        status = self._statusword()
        if status & 0x0008:
            self._write_controlword(0x0080)
            time.sleep(0.02)

    def _wait_for_status(self, predicate: Callable[[int], bool], timeout_s: float = 0.25) -> int:
        deadline = time.time() + timeout_s
        last = self._statusword()
        while time.time() < deadline:
            last = self._statusword()
            if predicate(last):
                return last
            time.sleep(0.01)
        return last

    def _ensure_operation_enabled(self) -> int:
        self._reset_fault_if_present()
        self._write_controlword(0x0006)
        self._wait_for_status(lambda sw: (sw & 0x006F) in (0x0021, 0x0023, 0x0027))
        self._write_controlword(0x0007)
        switched_on = self._wait_for_status(lambda sw: (sw & 0x006F) in (0x0023, 0x0027))
        self._write_controlword(0x000F)
        status = self._wait_for_status(lambda sw: (sw & 0x006F) == 0x0027, timeout_s=0.08)
        if (status & 0x006F) == 0x0027:
            return status

        if status & 0x0008:
            self._write_controlword(0x0080)
            time.sleep(0.02)
            self._write_controlword(0x0006)
            self._wait_for_status(lambda sw: (sw & 0x006F) in (0x0021, 0x0023, 0x0027))
            self._write_controlword(0x0007)
            switched_on = self._wait_for_status(lambda sw: (sw & 0x006F) in (0x0023, 0x0027), timeout_s=0.08)

        return switched_on

    def get_mo(self) -> Optional[int]:
        state = self._statusword() & 0x006F
        return 1 if state in (0x0021, 0x0023, 0x0027) else 0

    def get_px(self) -> Optional[int]:
        return self._read_i32(0x6064, 0x00)

    def get_ec(self) -> Optional[int]:
        status = self._statusword()
        if status & 0x0008:
            try:
                return self._read_u16(0x603F, 0x00)
            except Exception:
                return 1
        return 0

    def set_motor_on(self) -> str:
        status = self._ensure_operation_enabled()
        return f"statusword=0x{status:04x}"

    def set_motor_off(self) -> str:
        self._write_controlword(0x0000)
        status = self._wait_for_status(lambda sw: bool(sw & 0x0040) or not (sw & 0x0004))
        return f"statusword=0x{status:04x}"

    def set_tc(self, tc: int) -> str:
        self._ensure_operation_enabled()
        self._set_mode(self.MODE_CST)
        value = max(-32767, min(32767, int(tc)))
        self._write_i16(0x6071, value, 0x00)
        return f"mode={self.MODE_CST};target_torque={value}"

    def set_il(self, il: int) -> str:
        self._ensure_operation_enabled()
        self._set_mode(self.MODE_PROFILE_TORQUE)
        value = max(-32767, min(32767, int(il)))
        self._write_i16(0x6071, value, 0x00)
        return f"mode={self.MODE_PROFILE_TORQUE};target_torque={value}"

    def set_um(self, um: int) -> str:
        self.last_um = int(um)
        mode_map = {
            5: self.MODE_PROFILE_POSITION,
            2: self.MODE_PROFILE_VELOCITY,
            1: self.MODE_CST,
        }
        if um in mode_map:
            self._set_mode(mode_map[int(um)])
            return f"mode={mode_map[int(um)]}"
        return f"ignored_um={int(um)}"

    def set_rm(self, rm: int) -> str:
        self.last_rm = int(rm)
        return f"rm={self.last_rm}"

    def set_pr(self, pr: int) -> str:
        self._ensure_operation_enabled()
        self._set_mode(self.MODE_PROFILE_POSITION)
        self._configure_profile_defaults()
        if self.target_position == 0:
            self.target_position = self.get_px() or 0
        self.target_position += int(pr)
        self._write_i32(0x607A, self.target_position, 0x00)
        return f"mode={self.MODE_PROFILE_POSITION};target_position={self.target_position}"

    def begin_motion(self) -> str:
        self._ensure_operation_enabled()
        self._write_controlword(0x003F)
        time.sleep(0.002)
        self._write_controlword(0x000F)
        status = self._statusword()
        return f"statusword=0x{status:04x}"

    def stop_motion(self) -> str:
        try:
            self._write_i16(0x6071, 0, 0x00)
        except Exception:
            pass
        self._write_controlword(0x010F)
        time.sleep(0.002)
        self._write_controlword(0x000F)
        status = self._statusword()
        return f"statusword=0x{status:04x}"

    def describe(self) -> dict[str, Any]:
        serial_number = None
        try:
            serial_number = self._read_u32(0x1018, 0x04)
        except Exception:
            pass
        return {
            "transport": "ethercat",
            "adapter_name": self.adapter_name,
            "adapter_desc": self.adapter_desc,
            "slave_index": self.slave_index,
            "slave_name": getattr(self._require_slave(), "name", ""),
            "vendor_id": getattr(self._require_slave(), "man", 0),
            "product_code": getattr(self._require_slave(), "id", 0),
            "revision": getattr(self._require_slave(), "rev", 0),
            "serial_number": serial_number,
            "mode_command": self._read_i8(0x6060, 0x00),
            "mode_display": self._mode_display(),
            "statusword": self._statusword(),
            "position_actual": self.get_px(),
        }


def build_elmo_client(cfg: dict) -> BaseElmoClient:
    transport = str(cfg.get("elmo_transport", "serial")).strip().lower()
    if transport == "ethercat":
        return EthercatElmoClient(
            adapter_match=str(cfg.get("ethercat_adapter_match", "Realtek Gaming USB 2.5GbE Family Controller")),
            slave_index=int(cfg.get("ethercat_slave_index", 1)),
            profile_velocity=int(cfg.get("ethercat_profile_velocity", 120000)),
            profile_acceleration=int(cfg.get("ethercat_profile_acceleration", 250000)),
            profile_deceleration=int(cfg.get("ethercat_profile_deceleration", 250000)),
        )
    return SerialElmoClient(
        str(cfg.get("elmo_port", "COM13")),
        int(cfg.get("elmo_baud", 115200)),
        float(cfg.get("serial_timeout_s", 0.008)),
    )


def scan_ethercat_bus(cfg: dict, pysoem_module: Any | None = None) -> list[EthercatSlaveInfo]:
    client = EthercatElmoClient(
        adapter_match=str(cfg.get("ethercat_adapter_match", "Realtek Gaming USB 2.5GbE Family Controller")),
        slave_index=int(cfg.get("ethercat_slave_index", 1)),
        profile_velocity=int(cfg.get("ethercat_profile_velocity", 120000)),
        profile_acceleration=int(cfg.get("ethercat_profile_acceleration", 250000)),
        profile_deceleration=int(cfg.get("ethercat_profile_deceleration", 250000)),
        pysoem_module=pysoem_module,
    )
    pysoem = client._module()
    adapter_name, adapter_desc = client._find_adapter()
    master = pysoem.Master()
    infos: list[EthercatSlaveInfo] = []
    try:
        master.open(adapter_name)
        master.config_init()
        for slave_index, slave in enumerate(master.slaves, start=1):
            info = EthercatSlaveInfo(
                slave_index=slave_index,
                name=str(getattr(slave, "name", "")),
                vendor_id=int(getattr(slave, "man", 0)),
                product_code=int(getattr(slave, "id", 0)),
                revision=int(getattr(slave, "rev", 0)),
                serial_number=None,
                device_name=None,
                hardware_version=None,
                software_version=None,
            )
            try:
                info.serial_number = struct.unpack("<I", slave.sdo_read(0x1018, 0x04)[:4])[0]
            except Exception:
                pass
            try:
                info.device_name = slave.sdo_read(0x1008, 0x00).decode(errors="replace").strip("\x00") or None
            except Exception:
                pass
            try:
                info.hardware_version = slave.sdo_read(0x1009, 0x00).decode(errors="replace").strip("\x00") or None
            except Exception:
                pass
            try:
                info.software_version = slave.sdo_read(0x100A, 0x00).decode(errors="replace").strip("\x00") or None
            except Exception:
                pass
            infos.append(info)
    finally:
        try:
            master.close()
        except Exception:
            pass
    _ = adapter_desc
    return infos