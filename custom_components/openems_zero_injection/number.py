"""Manual, temporary DTU power-limit number entities for Build003."""

from __future__ import annotations

from time import monotonic

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN
from .const import (
    INSTALLED_NOMINAL_POWER_STEP_W,
    MAX_INSTALLED_NOMINAL_POWER_W,
    MIN_INSTALLED_NOMINAL_POWER_W,
)
from .coordinator import DtuProSCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the one common Manual-mode temporary power-limit control."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    started = monotonic()
    registry = er.async_get(hass)
    for port in (1, 2, 3):
        old_entity_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{entry.entry_id}_port_{port}_temporary_power_limit"
        )
        if old_entity_id is not None:
            # Keep historical registry entries but disable them permanently:
            # no old per-port command remains active or becomes orphaned.
            registry.async_update_entity(
                old_entity_id, disabled_by=RegistryEntryDisabler.INTEGRATION
            )
    old_switch_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_enable_manual_dtu_writes"
    )
    if old_switch_id is not None:
        registry.async_update_entity(
            old_switch_id, disabled_by=RegistryEntryDisabler.INTEGRATION
        )
    async_add_entities(
        [DtuCommonTemporaryPowerLimitNumber(coordinator, entry)]
        + [
            OpenEMSControllerNumber(
                coordinator, entry, "target_grid_power", "Puissance cible réseau", -200, 200, 5, UnitOfPower.WATT
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "deadband", "Zone de tolérance", 0, 200, 5, UnitOfPower.WATT
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "stabilization_delay", "Délai de stabilisation", 10, 60, 1, "s"
            ),
            OpenEMSControllerNumber(
                coordinator,
                entry,
                "installed_nominal_power",
                "Puissance nominale de l’installation photovoltaïque",
                MIN_INSTALLED_NOMINAL_POWER_W,
                MAX_INSTALLED_NOMINAL_POWER_W,
                INSTALLED_NOMINAL_POWER_STEP_W,
                UnitOfPower.WATT,
            ),
            OpenEMSControllerNumber(
                coordinator, entry, "maximum_step", "Pas maximal", 1, 20, 1, PERCENTAGE
            ),
        ]
    )
    coordinator.async_record_platform_setup("number", started, monotonic())


class DtuCommonTemporaryPowerLimitNumber(
    CoordinatorEntity[DtuProSCoordinator], NumberEntity
):
    """One slider that writes the same verified limit to all temporary ports."""

    _attr_native_min_value = 2
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DtuProSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_manual_temporary_power_limit"
        self._attr_name = "Limite temporaire manuelle DTU"
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
            and self.coordinator.manual_write_allowed
            and self.coordinator.data is not None
        )

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.effective_temporary_limit
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Request one verified common temporary-limit write."""
        if not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError("DTU power limit must be a whole percentage")
        await self.coordinator.async_set_manual_temporary_power_limit(int(value))


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
    def available(self) -> bool:
        """Local configuration must remain editable while Modbus is unavailable."""
        return True

    @property
    def native_value(self) -> float:
        controller = self.coordinator.controller
        fields = {
            "target_grid_power": "target_grid_power_w",
            "deadband": "deadband_w",
            "stabilization_delay": "stabilization_delay_seconds",
            "installed_nominal_power": "installed_nominal_power_w",
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
            "maximum_step": controller.set_maximum_step,
        }
        if self._key == "installed_nominal_power":
            await self.coordinator.async_set_installed_nominal_power(value)
            return
        setters[self._key](int(value))
        self.async_write_ha_state()
