"""Read-only DTU telemetry sensors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import re
from time import monotonic
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
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


# Unique IDs deliberately remain unchanged: Home Assistant uses them to retain
# history and customisations.  These object IDs only repair the automatically
# generated, generic IDs created by the first dashboard-entity increment.
_DASHBOARD_SENSOR_OBJECT_IDS: dict[str, str] = {
    "solarflow_soc_percent": "solarflow_soc_percent",
    "solarflow_directional_power_w": "solarflow_directional_power_w",
    "energy_strategy_effective": "energy_strategy_effective",
    "energy_strategy_directive": "energy_control_directive",
    "energy_strategy_reason": "energy_strategy_reason",
    "measurement_health": "measurement_health",
    "persistent_history_status": "persistent_history_status",
    "adaptive_nominal_gain": "adaptive_nominal_gain_w_per_percent",
    "adaptive_estimated_gain": "adaptive_estimated_gain_w_per_percent",
    "adaptive_confidence": "adaptive_confidence",
    "adaptive_limit_range": "adaptive_limit_range",
    "adaptive_accepted_observations": "adaptive_accepted_observations",
    "adaptive_rejected_observations": "adaptive_rejected_observations",
    "adaptive_comparable_predictions": "adaptive_comparable_predictions",
    "adaptive_nominal_median_error": "adaptive_nominal_median_error_w",
    "adaptive_adaptive_median_error": "adaptive_adaptive_median_error_w",
    "adaptive_nominal_signed_bias": "adaptive_nominal_signed_bias_w",
    "adaptive_adaptive_signed_bias": "adaptive_adaptive_signed_bias_w",
    "adaptive_better_percent": "adaptive_better_percent",
    "adaptive_candidate_limit": "adaptive_candidate_limit_percent",
    "adaptive_last_observation_reason": "adaptive_last_observation_reason",
}


def _dashboard_entity_id(suffix: str) -> str:
    """Return the stable, readable entity ID for one dashboard entity."""
    return f"sensor.openems_{_DASHBOARD_SENSOR_OBJECT_IDS[suffix]}"


def _migrate_generic_dashboard_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename only integration-generated generic IDs, never user custom IDs."""
    registry = er.async_get(hass)
    for suffix in _DASHBOARD_SENSOR_OBJECT_IDS:
        unique_id = f"{entry.entry_id}_{suffix}"
        current_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if current_entity_id is None:
            continue
        current_object_id = current_entity_id.split(".", maxsplit=1)[1]
        if not re.fullmatch(r".*hoymiles_dtu_pro_s_\d+", current_object_id):
            continue
        expected_entity_id = _dashboard_entity_id(suffix)
        if registry.async_get(expected_entity_id) is not None:
            continue
        registry.async_update_entity(
            current_entity_id, new_entity_id=expected_entity_id
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up all Build002 read-only DTU sensors."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    started = monotonic()
    _migrate_generic_dashboard_entity_ids(hass, entry)
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
            SolarFlowBatterySensor(coordinator, entry, "health", "État de santé batterie SolarFlow"),
            SolarFlowBatterySensor(
                coordinator, entry, "data_age_seconds", "Âge des données batterie SolarFlow",
                unit=UnitOfTime.SECONDS,
            ),
            SolarFlowBatterySensor(
                coordinator, entry, "soc_percent", "Niveau de charge batterie SolarFlow",
                unit="%",
            ),
            SolarFlowBatterySensor(
                coordinator, entry, "directional_power_w", "Puissance batterie SolarFlow",
                unit=UnitOfPower.WATT,
            ),
            EnergyStrategySensor(coordinator, entry, "effective"),
            EnergyStrategySensor(coordinator, entry, "directive"),
            EnergyStrategySensor(coordinator, entry, "reason"),
            MeasurementHealthSensor(coordinator, entry),
            PersistentHistoryStatusSensor(coordinator, entry),
            OpenEMSControllerSensor(coordinator, entry, "controller_state", "État du contrôleur"),
            OpenEMSControllerSensor(coordinator, entry, "scheduler_state", "État du planificateur"),
            OpenEMSControllerSensor(coordinator, entry, "current_limit", "Limite DTU réelle", unit="%"),
            OpenEMSControllerSensor(coordinator, entry, "current_limit_source", "Source de la limite courante", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "ports_synchronization", "État de synchronisation des ports", EntityCategory.DIAGNOSTIC),
            OpenEMSControllerSensor(coordinator, entry, "calculated_limit", "Limite prédictive théorique", unit="%"),
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
            AdaptiveLimitModelSensor(coordinator, entry, "nominal_gain", unit="W/%"),
            AdaptiveLimitModelSensor(coordinator, entry, "estimated_gain", unit="W/%"),
            AdaptiveLimitModelSensor(coordinator, entry, "confidence"),
            AdaptiveLimitModelSensor(coordinator, entry, "limit_range"),
            AdaptiveLimitModelSensor(coordinator, entry, "accepted_observations"),
            AdaptiveLimitModelSensor(coordinator, entry, "rejected_observations"),
            AdaptiveLimitModelSensor(coordinator, entry, "comparable_predictions"),
            AdaptiveLimitModelSensor(coordinator, entry, "nominal_median_error", unit=UnitOfPower.WATT),
            AdaptiveLimitModelSensor(coordinator, entry, "adaptive_median_error", unit=UnitOfPower.WATT),
            AdaptiveLimitModelSensor(coordinator, entry, "nominal_signed_bias", unit=UnitOfPower.WATT),
            AdaptiveLimitModelSensor(coordinator, entry, "adaptive_signed_bias", unit=UnitOfPower.WATT),
            AdaptiveLimitModelSensor(coordinator, entry, "better_percent", unit="%"),
            AdaptiveLimitModelSensor(coordinator, entry, "candidate_limit", unit="%"),
            AdaptiveLimitModelSensor(coordinator, entry, "last_observation_reason"),
        ]
    )
    coordinator.async_record_platform_setup("sensor", started, monotonic())


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


class SolarFlowBatterySensor(_DtuSensorBase):
    """Expose one passive normalized SolarFlow diagnostic without I/O."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DtuProSCoordinator, entry: ConfigEntry, field: str,
        name: str, *, unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry, f"solarflow_{field}")
        self._field = field
        self._attr_translation_key = f"solarflow_{field}"
        self._attr_native_unit_of_measurement = unit
        suffix = f"solarflow_{field}"
        if suffix in _DASHBOARD_SENSOR_OBJECT_IDS:
            # ``entity_id`` (not ``_attr_entity_id``) is the value consumed by
            # EntityPlatform before its first entity-registry entry is made.
            # This gives new installations a readable ID immediately.
            self.entity_id = _dashboard_entity_id(suffix)

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> Any:
        resources = self.coordinator.energy_manager.batteries
        if not resources:
            return None
        resource = resources[0]
        value = getattr(resource, self._field)
        return value.value if hasattr(value, "value") else value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        resources = self.coordinator.energy_manager.batteries
        if not resources:
            return {}
        resource = resources[0]
        attributes = {
            "adapter_id": resource.adapter_id,
            "adapter_version": resource.adapter_version,
            "last_updated": resource.last_updated.isoformat() if resource.last_updated else None,
            "anomalies": [anomaly.value for anomaly in resource.anomalies],
            "source_entities": resource.source_entities,
            "source_timestamps": {
                source: timestamp.isoformat() if timestamp else None
                for source, timestamp in resource.source_timestamps.items()
            },
            "source_ages_seconds": resource.source_ages_seconds,
            "source_max_age_seconds": resource.source_max_age_seconds,
            "source_freshness": resource.source_freshness,
        }
        return attributes


class EnergyStrategySensor(_DtuSensorBase):
    """Expose the latest already-evaluated energy-policy result.

    Reading this entity never calls ``EnergyStrategyEngine.decide``.  The
    controller stores the result at the normal decision boundary.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DtuProSCoordinator, entry: ConfigEntry, field: str
    ) -> None:
        super().__init__(coordinator, entry, f"energy_strategy_{field}")
        self._field = field
        self._attr_translation_key = f"energy_strategy_{field}"
        self.entity_id = _dashboard_entity_id(f"energy_strategy_{field}")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        decision = self.coordinator.controller.last_energy_strategy_decision
        if decision is None:
            return "unknown"
        if self._field == "effective":
            return decision.policy_id
        if self._field == "directive":
            return decision.dtu_control_directive.value
        if decision.comparison is not None:
            return decision.comparison.reason_code.value
        return decision.reason_code.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        decision = self.coordinator.controller.last_energy_strategy_decision
        if decision is None:
            return {}
        return {
            "decision_timestamp": decision.decision_timestamp.isoformat(),
            "input_snapshot_id": decision.input_snapshot_id,
            "fallback_used": decision.fallback_used,
        }


class MeasurementHealthSensor(_DtuSensorBase):
    """Summarise existing control-measurement health without performing I/O."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "measurement_health"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "measurement_health")
        self.entity_id = _dashboard_entity_id("measurement_health")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        sync = self.coordinator.controller.measurement_sync_diagnostics
        if (
            data is None
            or not data.connected
            or data.active_power_w is None
            or not self.coordinator.temporary_limits_ready
            or sync.reason is not None
        ):
            return "blocked"
        if data.last_error:
            return "degraded"
        return "healthy"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sync = self.coordinator.controller.measurement_sync_diagnostics
        return {
            "grid_age_seconds": sync.grid_age_seconds,
            "pv_age_seconds": sync.pv_age_seconds,
            "synchronized": sync.reason is None,
            "temporary_limits_ready": self.coordinator.temporary_limits_ready,
        }


class PersistentHistoryStatusSensor(_DtuSensorBase):
    """Expose cached persistent-history writer health without filesystem I/O."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "persistent_history_status"

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "persistent_history_status")
        self.entity_id = _dashboard_entity_id("persistent_history_status")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        recorder = self.coordinator.persistent_history_recorder
        diagnostics = recorder.diagnostics()
        if not diagnostics["enabled"]:
            return "disabled"
        if diagnostics["last_error"] or diagnostics["write_errors"] or diagnostics["events_dropped"]:
            return "degraded"
        return "active" if recorder.is_running else "unavailable"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        diagnostics = self.coordinator.persistent_history_recorder.diagnostics()
        return {
            "retention_days": diagnostics["retention_days"],
            "queue_size": diagnostics["queue_size"],
            "queue_capacity": diagnostics["queue_capacity"],
            "events_dropped": diagnostics["events_dropped"],
            "write_errors": diagnostics["write_errors"],
        }


class AdaptiveLimitModelSensor(_DtuSensorBase):
    """Expose passive adaptive-model facts without granting control authority."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DtuProSCoordinator,
        entry: ConfigEntry,
        field: str,
        *,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry, f"adaptive_{field}")
        self._field = field
        self._attr_translation_key = f"adaptive_{field}"
        self._attr_native_unit_of_measurement = unit
        self.entity_id = _dashboard_entity_id(f"adaptive_{field}")

    @property
    def available(self) -> bool:
        return True

    def _snapshot(self) -> dict[str, Any]:
        """Build a passive view from cached model/controller state only."""
        controller = self.coordinator.controller
        model = controller.adaptive_limit_model
        diagnostics = model.diagnostics()
        current_limit = controller.status.real_dtu_limit_percent
        grid_error = controller.status.grid_error_w
        candidate = None
        profile = None
        if current_limit is not None:
            profile = model.profile_for(current_limit)
            if grid_error is not None:
                candidate = model.candidate_for(
                    current_limit_percent=current_limit, grid_error_w=grid_error
                )
        metrics = diagnostics["prediction_metrics"]
        observation = diagnostics["last_observation"]
        last_reason = None
        if observation is not None:
            last_reason = (
                observation.get("rejection_reason")
                or observation.get("prediction_non_comparable_reason")
            )
        return {
            "diagnostics": diagnostics,
            "metrics": metrics,
            "profile": profile,
            "candidate": candidate,
            "last_reason": last_reason or "none",
        }

    @property
    def native_value(self) -> Any:
        view = self._snapshot()
        diagnostics = view["diagnostics"]
        metrics = view["metrics"]
        profile = view["profile"]
        candidate = view["candidate"]
        fields: dict[str, Any] = {
            "nominal_gain": diagnostics["gain_nominal_w_per_percent"],
            "estimated_gain": (
                candidate.gain_estimated_w_per_percent if candidate else None
            ),
            "confidence": candidate.confidence.value if candidate else "none",
            "limit_range": candidate.limit_range if candidate else (profile.limit_range if profile else "unknown"),
            "accepted_observations": diagnostics["accepted_observations"],
            "rejected_observations": diagnostics["rejected_observations"],
            "comparable_predictions": metrics["comparable_predictions"],
            "nominal_median_error": metrics["nominal_median_absolute_error_w"],
            "adaptive_median_error": metrics["adaptive_median_absolute_error_w"],
            "nominal_signed_bias": metrics["nominal_mean_signed_error_w"],
            "adaptive_signed_bias": metrics["adaptive_mean_signed_error_w"],
            "better_percent": metrics["adaptive_better_percent"],
            "candidate_limit": candidate.limit_candidate_percent if candidate else None,
            "last_observation_reason": view["last_reason"],
        }
        return fields[self._field]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._field != "candidate_limit":
            return {}
        return {"applied": False, "mode": "passive"}


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
            "commanded_limit": status.commanded_limit_percent,
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
        """Describe the automatic command path without scheduling any work."""
        if self._field != "commanded_limit":
            return {}
        return {
            "execution_mode": "Production",
            "is_simulation": False,
        }


class TraceRecorderSensor(_DtuSensorBase):
    """Expose passive RC4 recorder diagnostics without any I/O."""

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
        self._attr_translation_key = f"trace_{field}"
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
            return "active" if trace[self._field] else "inactive"
        if self._field == "mode":
            return trace[self._field]
        metrics = trace["metrics"]
        return metrics.get(self._field) if metrics else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose scope metadata without creating additional polling or entities."""
        trace = self.coordinator.controller.trace_recorder.diagnostics()
        metrics = trace.get("metrics") or {}
        return {
            "schema_version": trace.get("schema_version"),
            "metrics_scope": "complete_session",
            "retained_detailed_traces": trace.get("retained_traces"),
            "detailed_trace_capacity": trace.get("detailed_trace_capacity"),
            "detailed_traces_truncated": metrics.get("detailed_traces_truncated"),
        }
