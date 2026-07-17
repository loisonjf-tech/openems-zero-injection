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
from .controller import display_label
from .coordinator import DtuProSCoordinator
from .models import DtuMeasurements
from .registers import (
    PORT_PERMANENT_POWER_LIMIT_REGISTERS,
    PORT_TEMPORARY_POWER_LIMIT_REGISTERS,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up all Build002 read-only DTU sensors."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DtuConnectionSensor(coordinator, entry),
            DtuValueSensor(coordinator, entry, "inverter_count", "Nombre de micro-onduleurs DTU", EntityCategory.DIAGNOSTIC),
            DtuValueSensor(coordinator, entry, "meter_count", "Nombre de compteurs DTU", EntityCategory.DIAGNOSTIC),
            DtuValueSensor(coordinator, entry, "active_power_w", "Puissance active DTU", device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, unit=UnitOfPower.WATT),
            DtuValueSensor(coordinator, entry, "daily_energy_wh", "Énergie quotidienne DTU", device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL_INCREASING, unit=UnitOfEnergy.WATT_HOUR),
            DtuValueSensor(coordinator, entry, "total_energy_wh", "Énergie totale DTU", device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL_INCREASING, unit=UnitOfEnergy.WATT_HOUR),
            DtuValueSensor(coordinator, entry, "response_time_ms", "Temps de réponse DTU", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT, unit=UnitOfTime.MILLISECONDS),
            DtuValueSensor(coordinator, entry, "last_success", "Dernière communication DTU", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            DtuValueSensor(coordinator, entry, "port_1_temporary_power_limit_percent", "Limite temporaire DTU port 1", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_1_permanent_power_limit_percent", "Limite permanente DTU port 1", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_2_temporary_power_limit_percent", "Limite temporaire DTU port 2", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_2_permanent_power_limit_percent", "Limite permanente DTU port 2", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_3_temporary_power_limit_percent", "Limite temporaire DTU port 3", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_3_permanent_power_limit_percent", "Limite permanente DTU port 3", EntityCategory.DIAGNOSTIC, unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "controller_state", "État du contrôleur"),
            OpenEMSControllerSensor(coordinator, entry, "scheduler_state", "État du planificateur"),
            OpenEMSControllerSensor(coordinator, entry, "current_limit", "Limite DTU réelle", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "calculated_limit", "Limite DTU calculée", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "simulated_limit", "Limite DTU simulée", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "watts_per_percent", "Puissance correspondant à 1 %", EntityCategory.DIAGNOSTIC, unit="W/%"),
            OpenEMSControllerSensor(coordinator, entry, "grid_power", "Puissance réseau", unit=UnitOfPower.WATT),
            OpenEMSControllerSensor(coordinator, entry, "grid_error", "Erreur réseau", unit=UnitOfPower.WATT),
            OpenEMSControllerSensor(coordinator, entry, "next_command", "Prochaine commande autorisée dans", EntityCategory.DIAGNOSTIC, unit=UnitOfTime.SECONDS),
            OpenEMSControllerSensor(coordinator, entry, "last_decision", "Motif de la dernière décision", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_decision_time", "Date de la dernière décision", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            OpenEMSControllerSensor(coordinator, entry, "last_command_result", "Résultat de la dernière commande", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_command_time", "Date de la dernière commande", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            OpenEMSControllerSensor(coordinator, entry, "decision_count", "Décisions évaluées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_sent", "Commandes envoyées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_succeeded", "Commandes exécutées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_failed", "Commandes échouées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_simulated", "Commandes simulées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_error", "Dernière erreur du contrôleur", EntityCategory.DIAGNOSTIC),
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
    _attr_name = "Connexion OpenEMS"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "connection_status")

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return "Connecté" if data and data.connected else "Déconnecté"

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Mark cached power-limit values that were not refreshed this cycle."""
        if self._field in {
            "serial_number",
            "inverter_count",
            "meter_count",
            "total_energy_wh",
            "daily_energy_wh",
            "active_power_w",
            "reactive_power_var",
        }:
            health = self.coordinator.measurement_health(self._field)
            return {
                "fresh": health["available"],
                "last_success": health["last_success"],
                "last_error": health["last_error"],
                "consecutive_failures": health["consecutive_failures"],
            }
        if not self._field.startswith("port_") or "power_limit" not in self._field:
            return {}
        parts = self._field.split("_")
        port = int(parts[1])
        temporary = parts[2] == "temporary"
        registers = (
            PORT_TEMPORARY_POWER_LIMIT_REGISTERS
            if temporary
            else PORT_PERMANENT_POWER_LIMIT_REGISTERS
        )
        health = self.coordinator.power_limit_health(registers[port])
        return {
            "fresh": health["available"],
            "last_success": health["last_success"],
            "last_error": health["last_error"],
            "consecutive_failures": health["consecutive_failures"],
        }


class OpenEMSControllerSensor(_DtuSensorBase):
    """Expose local controller status; it does not trigger Modbus I/O."""

    def __init__(
        self,
        coordinator: DtuProSCoordinator,
        entry: ConfigEntry,
        field: str,
        name: str,
        category: EntityCategory | None = None,
        *,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, entry, field)
        self._field = field
        self._attr_name = name
        self._attr_entity_category = category
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def native_value(self) -> Any:
        controller = self.coordinator.controller
        status = controller.status
        fields: dict[str, Any] = {
            "controller_state": status.state,
            "scheduler_state": controller.scheduler.state.value,
            "current_limit": status.current_limit_percent,
            "calculated_limit": status.calculated_limit_percent,
            "simulated_limit": status.simulated_limit_percent,
            "watts_per_percent": controller.watts_per_percent,
            "grid_power": status.grid_power_w,
            "grid_error": status.grid_error_w,
            "next_command": controller.scheduler.remaining_seconds(),
            "last_decision": status.last_decision,
            "last_decision_time": status.last_decision_time,
            "last_command_result": status.last_command_result,
            "last_command_time": status.last_command_time,
            "decision_count": controller.history.count,
            "commands_sent": controller.commands_sent,
            "commands_succeeded": controller.commands_succeeded,
            "commands_failed": controller.commands_failed,
            "commands_simulated": controller.commands_simulated,
            "last_error": status.last_error,
        }
        value = fields[self._field]
        if self._field in {
            "controller_state",
            "scheduler_state",
            "last_decision",
            "last_command_result",
            "last_error",
        }:
            return display_label(value)
        return value
