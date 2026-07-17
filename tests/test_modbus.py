"""Tests for the deliberately restricted internal Modbus TCP client."""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.openems_zero_injection.modbus import (
    DtuConnectionError,
    DtuProSModbusClient,
)
from custom_components.openems_zero_injection.registers import (
    REG_PORT_1_PERMANENT_POWER_LIMIT,
    REG_PORT_1_TEMPORARY_POWER_LIMIT,
)


def read_response(
    *, tid: int = 1, device: int = 1, function: int = 4, payload: bytes = b"\x00\x02"
) -> list[bytes]:
    """Return the MBAP and PDU chunks for one read response."""
    pdu = bytes([function, len(payload)]) + payload
    return [struct.pack(">HHHB", tid, 0, len(pdu) + 1, device), pdu]


def write_response(
    *, tid: int = 1, device: int = 1, function: int = 6, address: int = 0xD007, value: int = 50
) -> list[bytes]:
    """Return the MBAP and PDU chunks for one write response."""
    pdu = bytes([function]) + struct.pack(">HH", address, value)
    return [struct.pack(">HHHB", tid, 0, len(pdu) + 1, device), pdu]


def exception_response(function: int, code: int = 1) -> list[bytes]:
    """Return one documented Modbus exception response."""
    pdu = bytes([function, code])
    return [struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1), pdu]


def streams(parts: list[bytes | Exception]):
    """Create deterministic mocked asyncio streams."""
    reader = MagicMock()
    reader.readexactly = AsyncMock(side_effect=parts)
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    writer.is_closing.return_value = False
    return reader, writer


async def test_valid_input_register_response() -> None:
    reader, writer = streams(read_response())
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        assert await DtuProSModbusClient("x", 502).async_read_input_registers(0x3004, 1) == [2]


async def test_valid_holding_register_power_limit_response() -> None:
    reader, _writer = streams(read_response(function=3, payload=b"\x00\x32"))
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, _writer)),
    ):
        assert await DtuProSModbusClient("x", 502).async_read_power_limit_register(0xD007) == 50


async def test_holding_register_exception_raises() -> None:
    reader, writer = streams(exception_response(0x83, 0x01))
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        with pytest.raises(DtuConnectionError, match="0x01"):
            await DtuProSModbusClient("x", 502).async_read_power_limit_register(0xD007)


@pytest.mark.parametrize(
    "parts",
    [
        read_response(tid=2),
        read_response(device=2),
        read_response(function=3),
        read_response(function=0x84, payload=b"\x02"),
        read_response(payload=b"\x00"),
    ],
)
async def test_invalid_input_responses_raise(parts) -> None:
    reader, writer = streams(parts)
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        with pytest.raises(DtuConnectionError):
            await DtuProSModbusClient("x", 502).async_read_input_registers(0, 1)


async def test_temporary_write_requires_exact_echo() -> None:
    reader, writer = streams(write_response(value=50))
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        await DtuProSModbusClient("x", 502).async_write_temporary_power_limit(0xD007, 50)
    assert writer.write.call_count == 1
    assert writer.write.call_args.args[0][7] == 0x06


@pytest.mark.parametrize(
    "parts",
    [
        write_response(address=0xD00D),
        write_response(value=51),
    ],
)
async def test_invalid_write_responses_raise(parts) -> None:
    reader, writer = streams(parts)
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        with pytest.raises(DtuConnectionError):
            await DtuProSModbusClient("x", 502).async_write_temporary_power_limit(0xD007, 50)


async def test_write_exception_raises_explicit_error_code() -> None:
    reader, writer = streams(exception_response(0x86, 0x01))
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        with pytest.raises(DtuConnectionError, match="0x01"):
            await DtuProSModbusClient("x", 502).async_write_temporary_power_limit(0xD007, 50)


@pytest.mark.parametrize("value", [1, 101])
async def test_out_of_range_temporary_write_is_refused(value: int) -> None:
    client = DtuProSModbusClient("x", 502)
    with pytest.raises(DtuConnectionError):
        await client.async_write_temporary_power_limit(0xD007, value)


async def test_global_and_permanent_registers_can_never_be_written() -> None:
    client = DtuProSModbusClient("x", 502)
    for address in (0xD001, 0xD002, REG_PORT_1_PERMANENT_POWER_LIMIT):
        with pytest.raises(DtuConnectionError):
            await client.async_write_temporary_power_limit(address, 50)
    assert "async_write_register" not in dir(client)
    assert "async_write_holding_register" not in dir(client)


async def test_truncated_timeout_refused_and_reconnect() -> None:
    reader, writer = streams([asyncio.IncompleteReadError(partial=b"x", expected=7)])
    open_connection = AsyncMock(side_effect=[(reader, writer), OSError("refused")])
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        open_connection,
    ):
        client = DtuProSModbusClient("x", 502)
        with pytest.raises(DtuConnectionError):
            await client.async_read_input_registers(0, 1)
        with pytest.raises(DtuConnectionError):
            await client.async_read_input_registers(0, 1)


async def test_empty_response_closes_then_reconnects_cleanly() -> None:
    """An EOF before MBAP is never reused for the next request."""
    broken_reader, broken_writer = streams(
        [asyncio.IncompleteReadError(partial=b"", expected=7)]
    )
    healthy_reader, healthy_writer = streams(read_response(tid=2))
    open_connection = AsyncMock(
        side_effect=[(broken_reader, broken_writer), (healthy_reader, healthy_writer)]
    )
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        open_connection,
    ):
        client = DtuProSModbusClient("x", 502)
        with pytest.raises(DtuConnectionError):
            await client.async_read_input_registers(0, 1)
        assert await client.async_read_input_registers(0, 1) == [2]

    broken_writer.close.assert_called_once()
    broken_writer.wait_closed.assert_awaited_once()
    assert client.connection_diagnostics()["reconnections"] == 1


async def test_timeout_closes_connection_and_records_error() -> None:
    """A Modbus timeout leaves no half-open stream behind."""
    reader, writer = streams([asyncio.TimeoutError()])
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        client = DtuProSModbusClient("x", 502)
        with pytest.raises(DtuConnectionError, match="Modbus communication failed"):
            await client.async_read_input_registers(0, 1)

    assert not client.connected
    assert client.connection_diagnostics()["total_errors"] == 1
    writer.close.assert_called_once()


async def test_concurrent_requests_are_serialized() -> None:
    """The request lock prevents two Modbus frames from using one stream at once."""
    reader, writer = streams(read_response(tid=1) + read_response(tid=2))
    in_drain = 0
    max_in_drain = 0

    async def drain() -> None:
        nonlocal in_drain, max_in_drain
        in_drain += 1
        max_in_drain = max(max_in_drain, in_drain)
        await asyncio.sleep(0)
        in_drain -= 1

    writer.drain = AsyncMock(side_effect=drain)
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        client = DtuProSModbusClient("x", 502)
        first, second = await asyncio.gather(
            client.async_read_input_registers(0, 1),
            client.async_read_input_registers(1, 1),
        )

    assert first == [2]
    assert second == [2]
    assert max_in_drain == 1
    assert writer.write.call_count == 2


async def test_clean_disconnect() -> None:
    reader, writer = streams(read_response())
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        client = DtuProSModbusClient("x", 502)
        await client.async_connect()
        await client.async_disconnect()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()
