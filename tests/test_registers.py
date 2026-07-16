"""Deterministic tests for documented DTU register decoders."""

import pytest

from custom_components.openems_zero_injection.registers import (
    RegisterDecodeError,
    decode_dtu_serial,
    decode_uint16,
    decode_uint32,
    decode_uint64,
)


def test_decode_unsigned_registers() -> None:
    assert decode_uint16([0x1234]) == 0x1234
    assert decode_uint32([0x1234, 0x5678]) == 0x12345678
    assert decode_uint64([0x0001, 0x2345, 0x6789, 0xABCD]) == 0x000123456789ABCD


def test_decode_power_scale_input() -> None:
    assert decode_uint32([0, 1234]) * 0.1 == 123.4


@pytest.mark.parametrize("registers", [[], [1, 2], [-1], [0x10000]])
def test_decode_rejects_invalid_registers(registers: list[int]) -> None:
    with pytest.raises(RegisterDecodeError):
        decode_uint16(registers)


def test_decode_dtu_serial_known_data() -> None:
    assert decode_dtu_serial([0x1234, 0xABCD, 0x0001]) == "1234ABCD0001"
