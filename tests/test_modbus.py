"""Tests for the internal read-only Modbus TCP client."""
import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from custom_components.openems_zero_injection.modbus import DtuConnectionError, DtuProSModbusClient

def response(tid: int = 1, device: int = 1, function: int = 4, payload: bytes = b"\x00\x02") -> list[bytes]:
    pdu = bytes([function, len(payload)]) + payload
    return [struct.pack(">HHHB", tid, 0, len(pdu) + 1, device), pdu]

def streams(parts: list[bytes]):
    reader = MagicMock(); reader.readexactly = AsyncMock(side_effect=parts)
    writer = MagicMock(); writer.drain = AsyncMock(); writer.wait_closed = AsyncMock(); writer.is_closing.return_value = False
    return reader, writer

async def test_valid_response() -> None:
    reader, writer = streams(response())
    with patch("custom_components.openems_zero_injection.modbus.asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        assert await DtuProSModbusClient("x", 502).async_read_input_registers(0x3004, 1) == [2]

@pytest.mark.parametrize("parts", [response(tid=2), response(device=2), response(function=3), response(function=0x84, payload=b"\x02"), response(payload=b"\x00")])
async def test_invalid_responses_raise(parts) -> None:
    reader, writer = streams(parts)
    with patch("custom_components.openems_zero_injection.modbus.asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        with pytest.raises(DtuConnectionError): await DtuProSModbusClient("x", 502).async_read_input_registers(0, 1)

async def test_truncated_timeout_refused_and_reconnect() -> None:
    reader, writer = streams(
        [asyncio.IncompleteReadError(partial=b"x", expected=7)]
    )
    open_connection = AsyncMock(side_effect=[(reader, writer), OSError("refused")])
    with patch("custom_components.openems_zero_injection.modbus.asyncio.open_connection", open_connection):
        client = DtuProSModbusClient("x", 502)
        with pytest.raises(DtuConnectionError): await client.async_read_input_registers(0, 1)
        with pytest.raises(DtuConnectionError): await client.async_read_input_registers(0, 1)

async def test_no_write_method_and_clean_disconnect() -> None:
    reader, writer = streams(response())
    with patch("custom_components.openems_zero_injection.modbus.asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        client = DtuProSModbusClient("x", 502); await client.async_connect(); await client.async_disconnect()
    writer.close.assert_called_once(); writer.wait_closed.assert_awaited_once()
    assert not any("write" in name for name in dir(client) if name.startswith("async_"))
