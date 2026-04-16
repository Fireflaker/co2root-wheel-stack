# Elmo EtherCAT Validation - 2026-04-15

This folder captures the EtherCAT validation work done directly from a Windows laptop using a Realtek USB 2.5GbE adapter, Npcap, and small `pysoem` probes.

## What was verified

- The laptop can discover the EtherCAT bus directly from the PC NIC.
- Exactly 4 EtherCAT slaves were found on the bus.
- The slaves identify as Elmo Whistle drives with:
  - vendor id `154`
  - product code `198948`
  - revision `66550`
- Read-only EtherCAT SDO communication works.
- Non-motion command writes work.
- Standard CiA402 operating mode writes work.
- The last written operating mode remained in place after closing and reopening the EtherCAT master.

## What was not verified

- Persistence across a full power cycle was not tested.
- Actual motor motion was not tested in this pass.
- Plain IP access to the drives was not discovered from the direct raw EtherCAT setup.
- Elmo Application Studio II direct management over this raw PC-to-slave EtherCAT path was not established.

## Main conclusion

The drives are reachable and controllable over raw EtherCAT from the PC, but that does not automatically provide the connection model Elmo Application Studio II expects. The results support using a real EtherCAT master workflow for bus control, while EAS II likely still needs USB, plain Ethernet/UDP, or an EoE or Maestro style gateway path.

## Files

- `scan_result.txt`: EtherCAT bus discovery showing 4 slaves.
- `readonly_probe_result.txt`: Read-only SDO identity and version reads.
- `command_probe_result.txt`: Non-motion controlword write and statusword response.
- `mode_probe_result.txt`: Operating mode writes and reconnect persistence check.
