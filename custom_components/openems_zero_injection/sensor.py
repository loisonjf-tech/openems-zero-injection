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
            DtuValueSensor(coordinator, entry, "port_1_temporary_power_limit_percent", "Limite temporaire réelle DTU port 1", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_1_permanent_power_limit_percent", "Limite permanente DTU port 1", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_2_temporary_power_limit_percent", "Limite temporaire réelle DTU port 2", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_2_permanent_power_limit_percent", "Limite permanente DTU port 2", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_3_temporary_power_limit_percent", "Limite temporaire réelle DTU port 3", EntityCategory.DIAGNOSTIC, unit="%"),
            DtuValueSensor(coordinator, entry, "port_3_permanent_power_limit_percent", "Limite permanente DTU port 3", EntityCategory.DIAGNOSTIC, unit="%"),
            EnergyManagerSensor(
                coordinator, entry, "battery_count", "Nombre de batteries détectées"
            ),
            EnergyManagerSensor(
                coordinator,
                entry,
                "total_max_charge_power_w",
                "Puissance maximale totale de charge",
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
                unit=UnitOfPower.WATT,
            ),
            EnergyManagerSensor(
                coordinator,
                entry,
                "total_current_charge_power_w",
                "Puissance actuelle de charge",
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
                unit=UnitOfPower.WATT,
            ),
            EnergyManagerSensor(
                coordinator,
                entry,
                "total_remaining_charge_power_w",
                "Capacité restante de charge",
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
                unit=UnitOfPower.WATT,
            ),
            EnergyManagerSensor(coordinator, entry, "state", "État Energy Manager"),
            OpenEMSControllerSensor(coordinator, entry, "controller_state", "État du contrôleur"),
            OpenEMSControllerSensor(coordinator, entry, "scheduler_state", "État du planificateur"),
            OpenEMSControllerSensor(coordinator, entry, "current_limit", "Limite DTU réelle", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "current_limit_source", "Source de la limite courante", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "ports_synchronization", "État de synchronisation des ports", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_simulated_limit", "Dernière limite simulée", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "simulated_limit", "Limite actuellement recommandée", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "calculated_limit", "Limite théorique calculée", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "commanded_limit", "Prochaine limite commandée", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "waiting_state", "État d’attente", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "scheduler_inactive_reason", "Motif d’inactivité du planificateur", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "watts_per_percent", "Puissance correspondant à 1 %", EntityCategory.DIAGNOSTIC, unit="W/%"),
            OpenEMSControllerSensor(coordinator, entry, "grid_power", "Puissance réseau", unit=UnitOfPower.WATT),
            OpenEMSControllerSensor(coordinator, entry, "grid_error", "Erreur réseau", unit=UnitOfPower.WATT),
            OpenEMSControllerSensor(coordinator, entry, "next_command", "Prochaine commande autorisée dans", EntityCategory.DIAGNOSTIC, unit=UnitOfTime.SECONDS),
            OpenEMSControllerSensor(coordinator, entry, "last_decision", "Motif de la dernière décision", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_decision_time", "Date de la dernière décision", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            OpenEMSControllerSensor(coordinator, entry, "last_decision_sequence", "Numéro de la dernière décision", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_command_result", "Résultat de la dernière commande", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_command_time", "Date de la dernière commande", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            OpenEMSControllerSensor(coordinator, entry, "last_command_sequence", "Numéro de la dernière commande", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "decision_count", "Décisions évaluées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_sent", "Commandes envoyées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_succeeded", "Commandes exécutées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_failed", "Commandes échouées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "commands_simulated", "Commandes simulées", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "last_error", "Dernière erreur du contrôleur", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "grid_source_timestamp", "Horodatage source puissance réseau", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            OpenEMSControllerSensor(coordinator, entry, "pv_source_timestamp", "Horodatage source puissance PV", EntityCategory.DIAGNOSTIC, device_class=SensorDeviceClass.TIMESTAMP),
            OpenEMSControllerSensor(coordinator, entry, "grid_measurement_age", "Âge mesure réseau", EntityCategory.DIAGNOSTIC, unit=UnitOfTime.SECONDS),
            OpenEMSControllerSensor(coordinator, entry, "pv_measurement_age", "Âge mesure PV", EntityCategory.DIAGNOSTIC, unit=UnitOfTime.SECONDS),
            OpenEMSControllerSensor(coordinator, entry, "measurement_timestamp_difference", "Écart temporel réseau/PV", EntityCategory.DIAGNOSTIC, unit=UnitOfTime.SECONDS),
            OpenEMSControllerSensor(coordinator, entry, "measurement_sync_tolerance", "Tolérance synchronisation mesures", EntityCategory.DIAGNOSTIC, unit=UnitOfTime.SECONDS),
            OpenEMSControllerSensor(coordinator, entry, "measurement_sync_reason", "Motif de désynchronisation des mesures", EntityCategory.DIAGNOSTIC),
            TraceRecorderSensor(coordinator, entry, "mode", "Mode Trace Recorder"),
            TraceRecorderSensor(coordinator, entry, "session_active", "Session de régulation active"),
            TraceRecorderSensor(coordinator, entry, "session_started_at", "Début de la session de régulation", device_class=SensorDeviceClass.TIMESTAMP),
            TraceRecorderSensor(coordinator, entry, "data_coverage_percent", "Couverture des données Trace Recorder", unit="%"),
            TraceRecorderSensor(coordinator, entry, "commands_confirmed", "Commandes confirmées Trace Recorder"),
            TraceRecorderSensor(coordinator, entry, "commands_effective", "Commandes efficaces Trace Recorder"),
            TraceRecorderSensor(coordinator, entry, "commands_ineffective", "Commandes inefficaces Trace Recorder"),
            TraceRecorderSensor(coordinator, entry, "commands_indeterminate", "Commandes indéterminées Trace Recorder"),
            TraceRecorderSensor(coordinator, entry, "median_energy_response_ms", "Temps de réponse énergétique médian", unit=UnitOfTime.MILLISECONDS),
            TraceRecorderSensor(coordinator, entry, "weighted_time_in_tolerance_percent", "Temps pondéré dans la tolérance", unit="%"),
            TraceRecorderSensor(coordinator, entry, "average_absolute_error_w", "Erreur absolue moyenne Trace Recorder", unit=UnitOfPower.WATT),
            TraceRecorderSensor(coordinator, entry, "suspected_oscillations", "Oscillations suspectées Trace Recorder"),
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
        # The three temporary-limit readings are cached coordinator values.
        # Keep a known value visible during a transient global refresh failure;
        # its freshness and any error remain explicit in state attributes.
        if self._field in {
            "port_1_temporary_power_limit_percent",
            "port_2_temporary_power_limit_percent",
            "port_3_temporary_power_limit_percent",
        }:
            return (
                self.coordinator.data is not None
                and getattr(self.coordinator.data, self._field) is not None
            )
        return super().available and self.coordinator.data is not None and getattr(self.coordinator.data, self._field) is not None

    @property
    def native_value(self) -> Any:
        data: DtuMeasurements | None = self.coordinator.data
        return getattr(data, self._field) if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Mark cached power-limit values that were not refreshed this cycle."""
        if self._field == "response_time_ms":
            return {
                "measurement": "single Modbus TCP transaction",
                "coordinator_cycle_duration_ms": self.coordinator.cycle_timings_ms.get(
                    "total_cycle"
                ),
            }
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


class EnergyManagerSensor(_DtuSensorBase):
    """Expose passive Energy Manager aggregates without any DTU interaction."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DtuProSCoordinator,
        entry: ConfigEntry,
        field: str,
        name: str,
        *,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry, f"energy_manager_{field}")
        self._field = field
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit

    @property
    def available(self) -> bool:
        """Local passive diagnostics do not depend on the DTU connection."""
        return True

    @property
    def native_value(self) -> Any:
        snapshot = self.coordinator.energy_manager.snapshot()
        value = getattr(snapshot, self._field)
        return display_label(value) if self._field == "state" else value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._field in {
            "total_max_charge_power_w",
            "total_current_charge_power_w",
            "total_remaining_charge_power_w",
        }:
            snapshot = self.coordinator.energy_manager.snapshot()
            return (
                {"unknown_reason": snapshot.unknown_reason}
                if snapshot.unknown_reason
                else {}
            )
        return {}


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
    def available(self) -> bool:
        """Controller state is local and remains visible during DTU outages."""
        return True

    @property
    def native_value(self) -> Any:
        controller = self.coordinator.controller
        status = controller.status
        fields: dict[str, Any] = {
            "controller_state": status.state,
            "scheduler_state": controller.scheduler_display_state,
            "current_limit": status.real_dtu_limit_percent,
            "current_limit_source": {
                "modbus_readback": "Relecture Modbus",
                "takeover_confirmed": "Prise de contrôle confirmée",
                "automatic_correction": "Dernière correction automatique confirmée",
                "manual_command": "Commande manuelle confirmée",
                "unknown": "Inconnue",
            }.get(self.coordinator.temporary_limit_source, "Inconnue"),
            "ports_synchronization": (
                "Synchronisés"
                if self.coordinator.temporary_limits_synchronized
                else "Incertains"
            ),
            "calculated_limit": status.calculated_limit_percent,
            # In Simulation this is intentionally only a displayed proposal:
            # it is never submitted to the DTU.
            "commanded_limit": (
                controller.simulated_current_limit
                if controller.mode.value == "Simulation"
                else status.commanded_limit_percent
            ),
            "simulated_limit": status.simulated_limit_percent,
            "last_simulated_limit": controller.last_simulated_limit,
            "waiting_state": controller.waiting_state,
            "scheduler_inactive_reason": status.scheduler_inactive_reason,
            "watts_per_percent": controller.watts_per_percent,
            "grid_power": status.grid_power_w,
            "grid_error": status.grid_error_w,
            "next_command": controller.scheduler.remaining_seconds(),
            "last_decision": status.last_decision,
            "last_decision_time": status.last_decision_time,
            "last_decision_sequence": controller.last_decision_sequence,
            "last_command_result": status.last_command_result,
            "last_command_time": status.last_command_time,
            "last_command_sequence": controller.last_command_sequence,
            "decision_count": controller.decisions_evaluated,
            "commands_sent": controller.commands_sent,
            "commands_succeeded": controller.commands_succeeded,
            "commands_failed": controller.commands_failed,
            "commands_simulated": controller.commands_simulated,
            "last_error": status.last_error,
            "grid_source_timestamp": controller.measurement_sync_diagnostics.grid_source_timestamp,
            "pv_source_timestamp": controller.measurement_sync_diagnostics.pv_source_timestamp,
            "grid_measurement_age": controller.measurement_sync_diagnostics.grid_age_seconds,
            "pv_measurement_age": controller.measurement_sync_diagnostics.pv_age_seconds,
            "measurement_timestamp_difference": controller.measurement_sync_diagnostics.difference_seconds,
            "measurement_sync_tolerance": controller.measurement_sync_diagnostics.tolerance_seconds,
            "measurement_sync_reason": controller.measurement_sync_diagnostics.reason,
        }
        value = fields[self._field]
        if self._field in {
            "controller_state",
            "scheduler_state",
            "last_decision",
            "last_command_result",
            "last_error",
            "scheduler_inactive_reason",
            "measurement_sync_reason",
        }:
            return display_label(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Make the simulated nature of a displayed proposal explicit."""
        if self._field != "commanded_limit":
            return {}
        is_simulation = self.coordinator.controller.mode.value == "Simulation"
        return {
            "execution_mode": "Simulation" if is_simulation else "Production",
            "is_simulation": is_simulation,
        }


class TraceRecorderSensor(_DtuSensorBase):
    """Expose passive RC3 recorder diagnostics without any I/O."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DtuProSCoordinator,
        entry: ConfigEntry,
        field: str,
        name: str,
        *,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, entry, f"trace_{field}")
        self._field = field
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> Any:
        trace = self.coordinator.controller.trace_recorder.diagnostics()
        if self._field == "session_started_at":
            return self.coordinator.controller.trace_recorder.session_started_at
        if self._field == "session_active":
            return "Active" if trace[self._field] else "Inactive"
        if self._field == "mode":
            return trace[self._field]
        metrics = trace["metrics"]
        return metrics.get(self._field) if metrics else None
