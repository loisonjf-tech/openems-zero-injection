"""OpenEMS Zero Injection custom integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_CONTROLLER_MODE, ControllerMode, DOMAIN, PLATFORMS
from .coordinator import DtuProSCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the DTU Pro-S connectivity integration from a config entry."""
    await _async_migrate_legacy_simulation(hass, entry)
    coordinator = DtuProSCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.controller.async_start()
    return True


async def _async_migrate_legacy_simulation(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Move the removed user Simulation mode to safe Manual operation."""
    if entry.options.get(CONF_CONTROLLER_MODE) == ControllerMode.SIMULATION.value:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_CONTROLLER_MODE: ControllerMode.DISABLED.value},
        )
    registry = er.async_get(hass)
    legacy_suffixes = (
        "last_simulated_limit",
        "simulated_limit",
        "commands_simulated",
    )
    for suffix in legacy_suffixes:
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
        )
        if entity_id is not None:
            registry.async_update_entity(
                entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
            )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the DTU Pro-S connectivity integration entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: DtuProSCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload safely after changing the selected local grid-power sensor."""
    coordinator: DtuProSCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and coordinator._skip_next_options_reload:
        coordinator._skip_next_options_reload = False
        return
    await hass.config_entries.async_reload(entry.entry_id)
