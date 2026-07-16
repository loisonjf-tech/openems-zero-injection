"""Read-only DTU telemetry sensors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN
from .coordinator import DtuProSCoordinator
from .models import DtuMeasurements


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up all Build002 read-only DTU sensors."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DtuConnectionSensor(coordinator, entry),
            DtuValueSensor(coordinator, entry, "inverter_count", "DTU Inverter Count", EntityCategory.DIAGNOSTIC),
            DtuValueSensor(coordinator, entry, "meter_count", "DTU Meter Count", EntityCategory.DIAGNOSTIC),
            DtuValueSensor(coordinator, entry, "active_power_w", "DTU Active Power", device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, unit=UnitOfPower.WATT),
            DtuValueSensor(coordinator, entry, "daily_energy_wh", "DTU Daily Energy", device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL_INCREASING, unit=UnitOfEnergy.WATT_HOUR),
            DtuValueSensor(coordinator, entry, "total_energy_wh", "DTU Total Energy", device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL_INCREASING, unit=UnitOfEnergy.WATT_HOUR),
            DtuValueSensor(coordinator, entry, "response_time_ms", "DTU Response Time", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT, unit=UnitOfTime.MILLISECONDS),
            DtuValueSensor(coordinator, entry, "last_success", "DTU Last Communication", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
        ]
    )


class _DtuSensorBase(CoordinatorEntity[DtuProSCoordinator], SensorEntity):
    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry, suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        endpoint = f"{entry.data[CONF_DTU_HOST]}:{entry.data[CONF_DTU_PORT]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, endpoint)},
            manufacturer="Hoymiles",
            model="DTU Pro-S",
            name="Hoymiles DTU Pro-S",
        )


class DtuConnectionSensor(_DtuSensorBase):
    """Report the DTU Modbus connection state."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"
    _attr_name = "OpenEMS Connection"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "connection_status")

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return "Connected" if data and data.connected else "Disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        data = self.coordinator.data
        return {"last_communication_error": data.last_error} if data and data.last_error else {}


class DtuValueSensor(_DtuSensorBase):
    """Expose one decoded measurement only when its value is valid."""

    def __init__(
        self,
        coordinator: DtuProSCoordinator,
        entry: ConfigEntry,
        field: str,
        name: str,
        category: EntityCategory | None = None,
        *,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry, field)
        self._field = field
        self._attr_name = name
        self._attr_entity_category = category
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None and getattr(self.coordinator.data, self._field) is not None

    @property
    def native_value(self) -> Any:
        data: DtuMeasurements | None = self.coordinator.data
        return getattr(data, self._field) if data else None
