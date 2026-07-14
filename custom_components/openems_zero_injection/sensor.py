"""Diagnostic sensors for OpenEMS Zero Injection."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DtuProSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DTU connection diagnostic sensor."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DtuConnectionSensor(coordinator, entry)])


class DtuConnectionSensor(CoordinatorEntity[DtuProSCoordinator], SensorEntity):
    """Report the DTU Pro-S Modbus TCP connection state."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"
    _attr_name = "OpenEMS Connection"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connection_status"

    @property
    def native_value(self) -> str:
        """Return a stable connection state."""
        return "Connected" if self.coordinator.data.connected else "Disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the latest connection error when available."""
        if self.coordinator.data.last_error:
            return {"last_communication_error": self.coordinator.data.last_error}
        return {}
