import struct
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elmo_transport import (  # noqa: E402
    EthercatElmoClient,
    SerialElmoClient,
    build_elmo_client,
    scan_ethercat_bus,
)


class FakeAdapter:
    def __init__(self, name: str, desc: str):
        self.name = name
        self.desc = desc


class FakeSlave:
    def __init__(self, serial_number: int, fail_enable_operation: bool = False):
        self.name = "Whistle"
        self.man = 154
        self.id = 198948
        self.rev = 66550
        self.fail_enable_operation = fail_enable_operation
        self.storage = {
            (0x6040, 0x00): struct.pack("<H", 0),
            (0x6041, 0x00): struct.pack("<H", 0x0250),
            (0x6060, 0x00): (0).to_bytes(1, byteorder="little", signed=True),
            (0x6061, 0x00): (0).to_bytes(1, byteorder="little", signed=True),
            (0x6064, 0x00): struct.pack("<i", 1000),
            (0x607A, 0x00): struct.pack("<i", 1000),
            (0x6071, 0x00): struct.pack("<h", 0),
            (0x6081, 0x00): struct.pack("<I", 0),
            (0x6083, 0x00): struct.pack("<I", 0),
            (0x6084, 0x00): struct.pack("<I", 0),
            (0x1018, 0x04): struct.pack("<I", serial_number),
            (0x1008, 0x00): b"Whistle\x00",
            (0x1009, 0x00): b"1.1.3.0\x00",
            (0x100A, 0x00): b"Whistle 01.01.09.00\x00",
            (0x603F, 0x00): struct.pack("<H", 0),
        }
        self.write_log = []

    def sdo_read(self, index, subindex):
        return self.storage[(index, subindex)]

    def sdo_write(self, index, subindex, payload):
        self.write_log.append((index, subindex, bytes(payload)))
        self.storage[(index, subindex)] = bytes(payload)
        if (index, subindex) == (0x6040, 0x00):
            value = struct.unpack("<H", payload[:2])[0]
            if value == 0x0006:
                self.storage[(0x6041, 0x00)] = struct.pack("<H", 0x0231)
            elif value == 0x0007:
                self.storage[(0x6041, 0x00)] = struct.pack("<H", 0x0233)
            elif value == 0x000F:
                if self.fail_enable_operation:
                    self.storage[(0x6041, 0x00)] = struct.pack("<H", 0x1208)
                    self.storage[(0x603F, 0x00)] = struct.pack("<H", 0xFF10)
                else:
                    self.storage[(0x6041, 0x00)] = struct.pack("<H", 0x0237)
            elif value == 0x0000:
                self.storage[(0x6041, 0x00)] = struct.pack("<H", 0x0250)
            elif value == 0x0080:
                self.storage[(0x6041, 0x00)] = struct.pack("<H", 0x0250)
        if (index, subindex) == (0x6060, 0x00):
            self.storage[(0x6061, 0x00)] = bytes(payload)


class FakeMaster:
    def __init__(self, slaves):
        self.slaves = slaves
        self.opened_name = None
        self.closed = False

    def open(self, name):
        self.opened_name = name

    def config_init(self):
        return len(self.slaves)

    def close(self):
        self.closed = True


class FakePysoem:
    def __init__(self, slaves):
        self._slaves = slaves
        self.find_adapters_calls = 0

    def find_adapters(self):
        self.find_adapters_calls += 1
        return [FakeAdapter(r"\Device\NPF_FAKE", "Realtek Gaming USB 2.5GbE Family Controller")]

    def Master(self):
        return FakeMaster(self._slaves)


class ElmoTransportTests(unittest.TestCase):
    def test_factory_selects_serial_and_ethercat(self):
        serial_client = build_elmo_client({"elmo_transport": "serial", "elmo_port": "COM13", "elmo_baud": 115200})
        ethercat_client = build_elmo_client({"elmo_transport": "ethercat"})
        self.assertIsInstance(serial_client, SerialElmoClient)
        self.assertIsInstance(ethercat_client, EthercatElmoClient)

    def test_ethercat_enable_sequence_and_torque_write(self):
        fake_module = FakePysoem([FakeSlave(111)])
        client = EthercatElmoClient(
            adapter_match="Realtek Gaming USB 2.5GbE Family Controller",
            slave_index=1,
            profile_velocity=120000,
            profile_acceleration=250000,
            profile_deceleration=250000,
            pysoem_module=fake_module,
        )

        client.open()
        try:
            response = client.set_tc(120)
            self.assertIn("target_torque=120", response)
            self.assertEqual(client.get_mo(), 1)
            self.assertEqual(client.describe()["mode_display"], 10)
        finally:
            client.close()

    def test_ethercat_profile_position_accumulates_target(self):
        fake_module = FakePysoem([FakeSlave(222)])
        client = EthercatElmoClient(
            adapter_match="Realtek Gaming USB 2.5GbE Family Controller",
            slave_index=1,
            profile_velocity=120000,
            profile_acceleration=250000,
            profile_deceleration=250000,
            pysoem_module=fake_module,
        )

        client.open()
        try:
            first = client.set_pr(500)
            second = client.set_pr(-100)
            client.begin_motion()
            self.assertIn("target_position=1500", first)
            self.assertIn("target_position=1400", second)
            self.assertEqual(client._read_i32(0x607A, 0x00), 1400)
            self.assertEqual(client.describe()["mode_display"], 1)
        finally:
            client.close()

    def test_ethercat_enable_requires_explicit_degraded_opt_in(self):
        fake_module = FakePysoem([FakeSlave(333, fail_enable_operation=True)])

        strict_client = EthercatElmoClient(
            adapter_match="Realtek Gaming USB 2.5GbE Family Controller",
            slave_index=1,
            profile_velocity=120000,
            profile_acceleration=250000,
            profile_deceleration=250000,
            allow_degraded_enable=False,
            pysoem_module=fake_module,
        )
        strict_client.open()
        try:
            with self.assertRaisesRegex(RuntimeError, "failed to reach Operation Enabled"):
                strict_client.set_motor_on()
        finally:
            strict_client.close()

        degraded_client = EthercatElmoClient(
            adapter_match="Realtek Gaming USB 2.5GbE Family Controller",
            slave_index=1,
            profile_velocity=120000,
            profile_acceleration=250000,
            profile_deceleration=250000,
            allow_degraded_enable=True,
            pysoem_module=fake_module,
        )
        degraded_client.open()
        try:
            response = degraded_client.set_motor_on()
            self.assertIn("statusword=0x0233", response)
        finally:
            degraded_client.close()

    def test_scan_ethercat_bus_reads_identity_strings(self):
        fake_module = FakePysoem([FakeSlave(101), FakeSlave(202)])
        infos = scan_ethercat_bus({"ethercat_adapter_match": "Realtek Gaming USB 2.5GbE Family Controller"}, pysoem_module=fake_module)
        self.assertEqual(len(infos), 2)
        self.assertEqual(infos[0].vendor_id, 154)
        self.assertEqual(infos[0].device_name, "Whistle")
        self.assertEqual(infos[1].serial_number, 202)


if __name__ == "__main__":
    unittest.main()