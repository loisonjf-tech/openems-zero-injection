"""Asynchronous, read-only Modbus TCP client for the Hoymiles DTU Pro-S."""

from __future__ import annotations

import logging

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .const import DEFAULT_DEVICE_ID, MODBUS_TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)


class DtuConnectionError(Exception):
    """Raised when the DTU cannot be connected to or read safely."""


class DtuProSModbusClient:
    """Read documented DTU input registers; this class has no write methods."""

    def __init__(
        self, host: str, port: int, device_id: int = DEFAULT_DEVICE_ID
    ) -> None:
        self.host = host
        self.port = port
        self.device_id = device_id
        self._client = AsyncModbusTcpClient(
            host,
            port=port,
            timeout=MODBUS_TIMEOUT_SECONDS,
            retries=0,
            reconnect_delay=0.1,
        )

    @property
    def connected(self) -> bool:
        """Return the transport's current connection state."""
        return self._client.connected

    async def async_connect(self) -> bool:
        """Connect to the DTU without blocking Home Assistant's event loop."""
        if self.connected:
            return True
        _LOGGER.debug("Connecting to DTU at %s:%s...", self.host, self.port)
        try:
            connected = await self._client.connect()
        except (ModbusException, OSError, TimeoutError) as err:
            raise DtuConnectionError(str(err)) from err
        if not connected:
            raise DtuConnectionError("Connection failed")
        _LOGGER.info("Connected to DTU Modbus TCP service.")
        return True

    async def async_check_connectivity(self) -> bool:
        """Verify that a Modbus TCP session can be established."""
        return await self.async_connect()

    async def async_read_input_registers(self, address: int, count: int) -> list[int]:
        """Read one documented input-register range using Modbus function 0x04."""
        await self.async_connect()
        _LOGGER.debug("Reading %s input registers at 0x%04X.", count, address)
        try:
            response = await self._client.read_input_registers(
                address, count=count, device_id=self.device_id
            )
        except (ModbusException, OSError, TimeoutError) as err:
            raise DtuConnectionError(str(err)) from err
        if response.isError():
            raise DtuConnectionError(f"Modbus exception response at 0x{address:04X}")
        registers = getattr(response, "registers", None)
        if not isinstance(registers, list) or len(registers) != count:
            raise DtuConnectionError(f"Invalid register response at 0x{address:04X}")
        _LOGGER.debug("Raw registers at 0x%04X: %s", address, registers)
        return registers

    async def async_disconnect(self) -> None:
        """Close the Modbus TCP connection cleanly."""
        if self.connected:
            _LOGGER.debug("Closing DTU connection at %s:%s.", self.host, self.port)
        self._client.close()
