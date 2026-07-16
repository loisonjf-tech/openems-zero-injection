"""Manual, temporary DTU power-limit number entities for Build003."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN
from .coordinator import DtuProSCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one temporary manual power-limit control per confirmed active port."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DtuTemporaryPowerLimitNumber(coordinator, entry, port)
            for port in coordinator.active_temporary_power_limit_ports()
        ]
    )


class DtuTemporaryPowerLimitNumber(CoordinatorEntity[DtuProSCoordinator], NumberEntity):
    """A gated manual control for one temporary, per-port limit only."""

    _attr_native_min_value = 2
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: DtuProSCoordinator, entry: ConfigEntry, port: int
    ) -> None:
        super().__init__(coordinator)
        self._port = port
        self._field = f"port_{port}_temporary_power_limit_percent"
        self._attr_unique_id = f"{entry.entry_id}_port_{port}_temporary_power_limit"
        self._attr_name = f"DTU Port {port} Temporary Power Limit"
        endpoint = f"{entry.data[CONF_DTU_HOST]}:{entry.data[CONF_DTU_PORT]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, endpoint)},
            manufacturer="Hoymiles",
            model="DTU Pro-S",
            name="Hoymiles DTU Pro-S",
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and getattr(self.coordinator.data, self._field) is not None
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return float(getattr(data, self._field)) if data else None

    async def async_set_native_value(self, value: float) -> None:
        """Request one gated manual temporary-limit write and its verification."""
        if not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError("DTU power limit must be a whole percentage")
        await self.coordinator.async_set_temporary_power_limit(self._port, int(value))
