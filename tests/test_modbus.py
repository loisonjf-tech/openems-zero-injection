"""Tests for the DTU TCP connectivity check."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.openems_zero_injection.modbus import (
    DtuConnectionError,
    DtuProSModbusClient,
)


async def test_connectivity_check_opens_tcp_connection() -> None:
    """A successful TCP handshake reports the DTU as connected."""
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        new_callable=AsyncMock,
    ) as open_connection:
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        writer.is_closing.return_value = False
        open_connection.return_value = (MagicMock(), writer)
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        assert await modbus.async_check_connectivity() is True
        open_connection.assert_awaited_once_with("192.0.2.10", 502)


async def test_connectivity_check_raises_on_failed_connection() -> None:
    """A refused transport is exposed as a dedicated connection error."""
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        new_callable=AsyncMock,
        side_effect=OSError("Connection refused"),
    ):
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        with pytest.raises(DtuConnectionError, match="Connection refused"):
            await modbus.async_check_connectivity()


async def test_disconnect_closes_client() -> None:
    """Unloading the integration closes the TCP connection."""
    with patch(
        "custom_components.openems_zero_injection.modbus.asyncio.open_connection",
        new_callable=AsyncMock,
    ) as open_connection:
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        writer.is_closing.return_value = False
        open_connection.return_value = (MagicMock(), writer)
        modbus = DtuProSModbusClient("192.0.2.10", 502)
        await modbus.async_connect()
        await modbus.async_disconnect()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
