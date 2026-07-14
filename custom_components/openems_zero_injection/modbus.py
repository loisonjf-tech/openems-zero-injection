"""Minimal Modbus TCP transport for the Hoymiles DTU Pro-S."""

from __future__ import annotations

import logging

from pymodbus.client import AsyncModbusTcpClient

_LOGGER = logging.getLogger(__name__)


class DtuConnectionError(Exception):
    """Raised when the DTU Modbus TCP transport cannot be reached."""


class DtuProSModbusClient:
    """Own the Modbus TCP connection without accessing any register."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._client = AsyncModbusTcpClient(
            host, port=port, timeout=5, retries=0, reconnect_delay=0
        )

    @property
    def connected(self) -> bool:
        """Return whether the TCP transport is connected."""
        return self._client.connected

    async def async_connect(self) -> bool:
        """Connect to the DTU Modbus TCP service without issuing a request."""
        if self._client.connected:
            return True

        _LOGGER.debug("Connecting to DTU at %s:%s...", self.host, self.port)
        try:
            connected = await self._client.connect()
        except (OSError, TimeoutError) as err:
            raise DtuConnectionError(str(err)) from err
        except Exception as err:
            # Pymodbus may wrap a transport failure in its own exception type.
            raise DtuConnectionError(str(err)) from err

        if connected:
            _LOGGER.debug("Connected to DTU at %s:%s.", self.host, self.port)
            return True

        raise DtuConnectionError("Connection failed")

    async def async_check_connectivity(self) -> bool:
        """Perform the Build001 connectivity check.

        A successful Modbus TCP session is the minimal safe check. No DTU
        register map has been approved for this build, so no register is read.
        """
        return await self.async_connect()

    async def async_disconnect(self) -> None:
        """Close the TCP transport."""
        if self._client.connected:
            _LOGGER.debug("Closing DTU connection at %s:%s.", self.host, self.port)
        self._client.close()
