"""Manual, temporary DTU power-limit number entities for Build003."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfPower
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
        + [
            OpenEMSControllerNumber(
                coordinator, entry, "target_grid_power", "OpenEMS Target Grid Power", -200, 200, 5, UnitOfPower.WATT
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "deadband", "OpenEMS Deadband", 0, 200, 5, UnitOfPower.WATT
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "stabilization_delay", "OpenEMS Stabilization Delay", 10, 60, 1, "s"
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "watts_per_percent", "OpenEMS Watts per Percent", 1, 100, 1, "W/%"
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "maximum_step", "OpenEMS Maximum Step", 1, 20, 1, PERCENTAGE
            ),
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


class OpenEMSControllerNumber(CoordinatorEntity[DtuProSCoordinator], NumberEntity):
    """A local controller parameter; changing it never writes Modbus directly."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: DtuProSCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        minimum: float,
        maximum: float,
        step: float,
        unit: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        endpoint = f"{entry.data[CONF_DTU_HOST]}:{entry.data[CONF_DTU_PORT]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, endpoint)},
            manufacturer="Hoymiles",
            model="DTU Pro-S",
            name="Hoymiles DTU Pro-S",
        )

    @property
    def native_value(self) -> float:
        controller = self.coordinator.controller
        fields = {
            "target_grid_power": "target_grid_power_w",
            "deadband": "deadband_w",
            "stabilization_delay": "stabilization_delay_seconds",
            "watts_per_percent": "watts_per_percent",
            "maximum_step": "maximum_step_percent",
        }
        return float(getattr(controller, fields[self._key]))

    async def async_set_native_value(self, value: float) -> None:
        """Set one local, bounded controller parameter."""
        controller = self.coordinator.controller
        setters = {
            "target_grid_power": controller.set_target_grid_power,
            "deadband": controller.set_deadband,
            "stabilization_delay": controller.set_stabilization_delay,
            "watts_per_percent": controller.set_watts_per_percent,
            "maximum_step": controller.set_maximum_step,
        }
        setters[self._key](int(value) if self._key != "watts_per_percent" else value)
        self.async_write_ha_state()
