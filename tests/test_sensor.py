"""Tests for the OpenEMS connection diagnostic sensor."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import replace

from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.helpers import entity_registry as er

from custom_components.openems_zero_injection.const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    DOMAIN,
    ControllerMode,
)
from custom_components.openems_zero_injection.battery import BatteryHealth, BatteryResource
from custom_components.openems_zero_injection.energy_strategy import (
    DtuControlDirective,
    EnergyStrategyDecision,
    EnergyStrategyReasonCode,
)


async def test_connection_sensor_reports_connected(hass) -> None:
    """The diagnostic sensor reports a successful DTU connection."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client_class.return_value.async_check_connectivity = AsyncMock(return_value=True)
        client_class.return_value.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client_class.return_value.async_read_power_limit_register = AsyncMock(
            return_value=50
        )
        client_class.return_value.async_write_temporary_power_limit = AsyncMock()
        client_class.return_value.async_disconnect = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    registry_entry = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_connection_status"
    )
    assert registry_entry is not None
    state = hass.states.get(registry_entry)
    assert state is not None
    assert state.state == "Connecté"

    power_limit_entity = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_manual_temporary_power_limit"
    )
    assert power_limit_entity is not None
    # Home Assistant serializes NumberEntity states as floating-point values.
    assert hass.states.get(power_limit_entity).state == "50.0"

    # The slider belongs exclusively to Manual mode and requires a connected DTU.
    await coordinator.controller.async_set_mode(ControllerMode.SIMULATION.value)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(power_limit_entity).state == "unavailable"

    await coordinator.controller.async_set_mode(ControllerMode.PRODUCTION.value)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(power_limit_entity).state == "unavailable"

    await coordinator.controller.async_set_mode(ControllerMode.DISABLED.value)
    coordinator.async_set_updated_data(replace(coordinator.data, connected=False))
    await hass.async_block_till_done()
    assert hass.states.get(power_limit_entity).state == "unavailable"

    coordinator.async_set_updated_data(replace(coordinator.data, connected=True))
    await hass.async_block_till_done()
    assert hass.states.get(power_limit_entity).state == "50.0"

    temporary_limit_sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_port_1_temporary_power_limit_percent"
    )
    assert temporary_limit_sensor is not None
    assert hass.states.get(temporary_limit_sensor).state == "50"

    expected_energy_manager_states = {
        "energy_manager_battery_count": "0",
        "energy_manager_total_max_charge_power_w": "unknown",
        "energy_manager_total_current_charge_power_w": "unknown",
        "energy_manager_total_remaining_charge_power_w": "unknown",
        "energy_manager_state": "Aucune batterie configurée",
    }
    for suffix, expected_state in expected_energy_manager_states.items():
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
        )
        assert entity_id is not None
        assert hass.states.get(entity_id).state == expected_state

    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    # A verified cached temporary limit remains visible; its attributes expose
    # that a later Modbus refresh might be stale.
    assert hass.states.get(temporary_limit_sensor).state == "50"

    for platform, unique_id in (
        ("select", f"{entry.entry_id}_controller_mode"),
        ("number", f"{entry.entry_id}_installed_nominal_power"),
        ("sensor", f"{entry.entry_id}_controller_state"),
    ):
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        assert entity_id is not None
        assert hass.states.get(entity_id).state != "unavailable"

    trace_mode_entity = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_trace_mode"
    )
    assert trace_mode_entity is not None
    assert hass.states.get(trace_mode_entity).state == "normal"


async def test_dashboard_entities_read_cached_state_without_control_io(hass) -> None:
    """Dashboard entities only expose already-cached controller and battery data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client = client_class.return_value
        client.async_check_connectivity = AsyncMock(return_value=True)
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.async_write_temporary_power_limit = AsyncMock()
        client.async_disconnect = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    controller = coordinator.controller
    client.async_read_input_registers.reset_mock()
    client.async_read_power_limit_register.reset_mock()
    coordinator.energy_manager.set_batteries(
        (
            BatteryResource(
                resource_id="solarflow-1",
                name="SolarFlow",
                adapter_id="zendure_solarflow",
                adapter_version="test",
                available=True,
                health=BatteryHealth.HEALTHY,
                last_updated=datetime.now(UTC),
                data_age_seconds=1,
                soc_percent=62,
                directional_power_w=-348,
                charge_power_w=348,
                discharge_power_w=0,
                max_charge_power_w=1000,
                remaining_charge_power_w=652,
            ),
        )
    )
    controller._last_energy_strategy_decision = EnergyStrategyDecision(
        target_grid_power_w=-40,
        policy_id="zero_injection",
        reason="Configured zero-injection target",
        confidence=1.0,
        fallback_used=False,
        decision_timestamp=datetime.now(UTC),
        input_snapshot_id="test-snapshot",
        reason_code=EnergyStrategyReasonCode.CONFIGURED_ZERO_INJECTION_TARGET,
        dtu_control_directive=DtuControlDirective.NORMAL_REGULATION,
    )
    controller._energy_policy_engine.decide = MagicMock()
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    registry = er.async_get(hass)

    def state_for(suffix: str):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{suffix}")
        assert entity_id is not None
        state = hass.states.get(entity_id)
        assert state is not None
        return state

    assert state_for("energy_strategy_effective").state == "zero_injection"
    assert state_for("energy_strategy_directive").state == "normal_regulation"
    assert state_for("energy_strategy_reason").state == "configured_zero_injection_target"
    assert state_for("solarflow_soc_percent").state == "62"
    directional = state_for("solarflow_directional_power_w")
    assert directional.state == "-348"
    assert state_for("persistent_history_status").state == "disabled"
    assert state_for("adaptive_nominal_gain").state == "30.0"
    candidate = state_for("adaptive_candidate_limit")
    assert candidate.state == "unknown"
    assert candidate.attributes["applied"] is False

    controller.energy_policy_engine.decide.assert_not_called()
    client.async_read_input_registers.assert_not_awaited()
    client.async_read_power_limit_register.assert_not_awaited()
