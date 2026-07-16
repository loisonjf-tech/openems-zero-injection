"""Read-only Hoymiles DTU Pro-S register definitions and decoders.

The protocol stores multi-register values as big-endian 16-bit words.  Each
word is also big-endian; the host byte order is never used.
"""

from __future__ import annotations

from dataclasses import dataclass

REG_DTU_SERIAL = 0x3000
REG_METER_COUNT = 0x3003
REG_INVERTER_COUNT = 0x3004
REG_TOTAL_ENERGY = 0x3100
REG_DAILY_ENERGY = 0x3104
REG_TOTAL_ACTIVE_POWER = 0x3108
REG_TOTAL_REACTIVE_POWER = 0x310A

REG_DTU_SERIAL_COUNT = 3
REG_METER_COUNT_COUNT = 1
REG_INVERTER_COUNT_COUNT = 1
REG_TOTAL_ENERGY_COUNT = 4
REG_DAILY_ENERGY_COUNT = 4
REG_TOTAL_ACTIVE_POWER_COUNT = 2
REG_TOTAL_REACTIVE_POWER_COUNT = 2

ACTIVE_POWER_SCALE = 0.1
REACTIVE_POWER_SCALE = 0.1


class RegisterDecodeError(ValueError):
    """Raised when a documented DTU register payload is invalid."""


def _validate_registers(registers: list[int], expected_count: int) -> None:
    if len(registers) != expected_count:
        raise RegisterDecodeError(
            f"Expected {expected_count} registers, received {len(registers)}"
        )
    if any(not isinstance(value, int) or not 0 <= value <= 0xFFFF for value in registers):
        raise RegisterDecodeError("Registers must be uint16 values")


def _decode_unsigned(registers: list[int], expected_count: int) -> int:
    _validate_registers(registers, expected_count)
    value = 0
    for register in registers:
        value = (value << 16) | register
    return value


def decode_uint16(registers: list[int]) -> int:
    """Decode one big-endian 16-bit register."""
    return _decode_unsigned(registers, 1)


def decode_uint32(registers: list[int]) -> int:
    """Decode two big-endian 16-bit registers into an unsigned 32-bit value."""
    return _decode_unsigned(registers, 2)


def decode_uint64(registers: list[int]) -> int:
    """Decode four big-endian 16-bit registers into an unsigned 64-bit value."""
    return _decode_unsigned(registers, 4)


def decode_dtu_serial(registers: list[int]) -> str:
    """Decode the documented three-word DTU serial payload as uppercase hex.

    The serial encoding must be validated on real hardware before it is used as
    a Home Assistant device identifier.
    """
    _validate_registers(registers, REG_DTU_SERIAL_COUNT)
    return "".join(f"{register:04X}" for register in registers)


@dataclass(frozen=True, slots=True)
class RegisterDefinition:
    """Description of an implemented read-only input-register range."""

    address: int
    count: int
    description: str

