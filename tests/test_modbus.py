"""Tests for the read-only DTU Modbus client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.openems_zero_injection.modbus import DtuConnectionError, DtuProSModbusClient


def _client_mock() -> MagicMock:
    client = MagicMock()
    client.connected = False
    client.connect = AsyncMock(return_value=True)
    client.read_input_registers = AsyncMock(return_value=MagicMock(isError=lambda: False, registers=[2]))
    return client


async def test_connection_and_read_are_successful() -> None:
    with patch("custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient") as cls:
        client = _client_mock()
        cls.return_value = client
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        assert await modbus.async_read_input_registers(0x3004, 1) == [2]
        client.read_input_registers.assert_awaited_once_with(0x3004, count=1, device_id=1)


@pytest.mark.parametrize("side_effect", [OSError("refused"), TimeoutError()])
async def test_connection_errors_are_wrapped(side_effect: Exception) -> None:
    with patch("custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient") as cls:
        client = _client_mock()
        client.connect = AsyncMock(side_effect=side_effect)
        cls.return_value = client
        with pytest.raises(DtuConnectionError):
            await DtuProSModbusClient("192.0.2.10", 502).async_connect()


async def test_modbus_error_response_is_wrapped() -> None:
    with patch("custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient") as cls:
        client = _client_mock()
        client.read_input_registers = AsyncMock(return_value=MagicMock(isError=lambda: True))
        cls.return_value = client
        with pytest.raises(DtuConnectionError, match="exception response"):
            await DtuProSModbusClient("192.0.2.10", 502).async_read_input_registers(0x3004, 1)


async def test_disconnect_closes_client_and_no_write_api_exists() -> None:
    with patch("custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient") as cls:
        client = _client_mock()
        cls.return_value = client
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        await modbus.async_disconnect()
        client.close.assert_called_once()
        assert not any(name.startswith("async_write") for name in dir(modbus))
