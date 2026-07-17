"""Controller mode selector for Build004."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DTU_HOST, CONF_DTU_PORT, ControllerMode, DOMAIN
from .coordinator import DtuProSCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the disabled-by-default controller mode selector."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OpenEMSControllerModeSelect(coordinator, entry)])


class OpenEMSControllerModeSelect(CoordinatorEntity[DtuProSCoordinator], SelectEntity):
    """Explicitly choose Disabled, Simulation, or Production."""

    _attr_name = "Mode du contrôleur"
    _attr_options = ["Désactivé", "Simulation", "Production"]
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_controller_mode"
        endpoint = f"{entry.data[CONF_DTU_HOST]}:{entry.data[CONF_DTU_PORT]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, endpoint)},
            manufacturer="Hoymiles",
            model="DTU Pro-S",
            name="Hoymiles DTU Pro-S",
        )

    @property
    def current_option(self) -> str:
        return {
            ControllerMode.DISABLED: "Désactivé",
            ControllerMode.SIMULATION: "Simulation",
            ControllerMode.PRODUCTION: "Production",
        }[self.coordinator.controller.mode]

    async def async_select_option(self, option: str) -> None:
        """Apply an explicit mode choice; no mode is restored automatically."""
        modes = {
            "Désactivé": ControllerMode.DISABLED.value,
            "Simulation": ControllerMode.SIMULATION.value,
            "Production": ControllerMode.PRODUCTION.value,
        }
        await self.coordinator.controller.async_set_mode(modes[option])
        self.async_write_ha_state()
