"""Connection coordinator for the Hoymiles DTU Pro-S."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN, SCAN_INTERVAL
from .modbus import DtuConnectionError, DtuProSModbusClient

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConnectionStatus:
    """The current state of the DTU TCP connection."""

    connected: bool
    last_error: str | None = None


class DtuProSCoordinator(DataUpdateCoordinator[ConnectionStatus]):
    """Maintain and periodically verify the DTU Pro-S Modbus connection."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self._modbus = DtuProSModbusClient(
            entry.data[CONF_DTU_HOST], entry.data[CONF_DTU_PORT]
        )

    async def _async_update_data(self) -> ConnectionStatus:
        """Connect or report a transport error without accessing registers."""
        was_connected = self.data is not None and self.data.connected
        if self.data is not None and not was_connected:
            _LOGGER.debug("Reconnecting to DTU...")
        try:
            connected = await self._modbus.async_check_connectivity()
        except DtuConnectionError as err:
            if was_connected:
                _LOGGER.warning("DTU connection lost.")
            else:
                _LOGGER.debug("DTU connection failed: %s", err)
            return ConnectionStatus(connected=False, last_error=str(err))

        if not connected:
            return ConnectionStatus(connected=False, last_error="Connection failed")
        return ConnectionStatus(connected=True)

    async def async_shutdown(self) -> None:
        """Close the Modbus TCP connection during integration unload."""
        await self._modbus.async_disconnect()
