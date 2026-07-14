"""Tests for the DTU Modbus TCP transport."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.openems_zero_injection.modbus import (
    DtuConnectionError,
    DtuProSModbusClient,
)


async def test_connectivity_check_opens_tcp_connection() -> None:
    """A successful TCP handshake reports the DTU as connected."""
    with patch(
        "custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient"
    ) as client_class:
        client = client_class.return_value
        client.connected = False
        client.connect = AsyncMock(return_value=True)
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        assert await modbus.async_check_connectivity() is True
        client.connect.assert_awaited_once()


async def test_connectivity_check_raises_on_failed_connection() -> None:
    """A refused transport is exposed as a dedicated connection error."""
    with patch(
        "custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient"
    ) as client_class:
        client = client_class.return_value
        client.connected = False
        client.connect = AsyncMock(return_value=False)
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        with pytest.raises(DtuConnectionError, match="Connection failed"):
            await modbus.async_check_connectivity()


async def test_disconnect_closes_client() -> None:
    """Unloading the integration closes the TCP client."""
    with patch(
        "custom_components.openems_zero_injection.modbus.AsyncModbusTcpClient"
    ) as client_class:
        client = client_class.return_value
        client.connected = True
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        await modbus.async_disconnect()
        client.close.assert_called_once()
