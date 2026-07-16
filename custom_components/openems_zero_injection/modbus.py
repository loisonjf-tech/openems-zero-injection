"""TCP connectivity check for the Hoymiles DTU Pro-S."""

from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)


class DtuConnectionError(Exception):
    """Raised when the DTU TCP service cannot be reached."""


class DtuProSModbusClient:
    """Own a TCP connection to the DTU without exchanging Modbus data."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._writer: asyncio.StreamWriter | None = None

    @property
    def connected(self) -> bool:
        """Return whether the TCP transport is connected."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> bool:
        """Open the DTU TCP port without issuing a request."""
        if self.connected:
            return True

        _LOGGER.debug("Connecting to DTU at %s:%s...", self.host, self.port)
        try:
            async with asyncio.timeout(5):
                _, self._writer = await asyncio.open_connection(self.host, self.port)
        except (OSError, TimeoutError) as err:
            raise DtuConnectionError(str(err)) from err

        _LOGGER.debug("Connected to DTU at %s:%s.", self.host, self.port)
        return True

    async def async_check_connectivity(self) -> bool:
        """Perform the Build001 connectivity check.

        This check only opens the DTU TCP port. No Modbus frame, register read,
        or register write is performed.
        """
        return await self.async_connect()

    async def async_disconnect(self) -> None:
        """Close the TCP transport."""
        writer = self._writer
        self._writer = None
        if writer is None:
            return

        if not writer.is_closing():
            _LOGGER.debug("Closing DTU connection at %s:%s.", self.host, self.port)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            _LOGGER.debug("DTU TCP connection closed with a transport error.")
