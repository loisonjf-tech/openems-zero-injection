# Build003 Specification — Safe temporary power-limit control

**Version:** V0.3.0-alpha.1  
**Build:** 003 RC1  
**Status:** implementation candidate pending real-hardware validation

## Objective

Provide manual, temporary, per-port DTU power-limit control. This build is not
a zero-injection controller and contains no automatic decision, schedule,
Zendure integration, battery logic, or permanent power-limit write.

## Phase A — read-only discovery

Read with Modbus TCP function `0x03` only the six official REV1.2 registers:

| Port | Temporary | Permanent |
| --- | ---: | ---: |
| 1 | `0xD007` | `0xD008` |
| 2 | `0xD00D` | `0xD00E` |
| 3 | `0xD013` | `0xD014` |

Each value is exposed through a diagnostic sensor. A failed or invalid read
makes only that entity unavailable. It does not stop the integration.

## Phase B — opt-in temporary writes

`Enable Manual DTU Writes` is off after every integration start. While off,
Number entities cannot send a Modbus frame. While on, only `0xD007`, `0xD00D`,
and `0xD013` can be written, and only with one `0x06` request containing an
integer `uint16` value from 2 to 100 inclusive.

After the `0x06` echo is validated, the integration immediately reads the same
register using `0x03` and requires an identical value. Any failure leaves the
last confirmed Home Assistant value unchanged and sends no automatic recovery
write.

The all-inverter registers `0xD001` and `0xD002`, and the permanent per-port
registers `0xD008`, `0xD00E`, and `0xD014`, cannot be write targets in this
build.

## Validation required

No tag or release is created before validation on the actual DTU. Confirm the
active ports, use compatible third-generation HMS hardware, and test one
manual temporary command at a time.
