"""Safety interlock for manual DTU temporary power-limit writes."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN
from .coordinator import DtuProSCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the off-by-default manual-write safety interlock."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DtuManualWritesSwitch(coordinator, entry)])


class DtuManualWritesSwitch(CoordinatorEntity[DtuProSCoordinator], SwitchEntity):
    """Require an explicit local opt-in before a Number can send function 0x06."""

    _attr_name = "Enable Manual DTU Writes"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:shield-lock-outline"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_enable_manual_dtu_writes"
        endpoint = f"{entry.data[CONF_DTU_HOST]}:{entry.data[CONF_DTU_PORT]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, endpoint)},
            manufacturer="Hoymiles",
            model="DTU Pro-S",
            name="Hoymiles DTU Pro-S",
        )

    @property
    def is_on(self) -> bool:
        """Return whether manual writes have been explicitly enabled."""
        return self.coordinator.manual_writes_enabled

    async def async_turn_on(self, **kwargs: object) -> None:
        """Allow manual writes for the current Home Assistant session."""
        await self.coordinator.async_set_manual_writes_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Immediately block all manual writes."""
        await self.coordinator.async_set_manual_writes_enabled(False)
