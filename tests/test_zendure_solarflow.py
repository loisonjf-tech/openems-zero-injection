"""Tests for the Build005 SolarFlow read-only adapter corrections."""

from datetime import UTC, datetime, timedelta

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN

from custom_components.openems_zero_injection.battery import (
    BatteryHealth,
    BatteryPowerSign,
    BatteryReasonCode,
)
from custom_components.openems_zero_injection.battery_adapters.zendure_solarflow import (
    BAT_IN_OUT_ENTITY_ID,
    ZendureSolarFlowAdapter,
)


def _adapter(hass, **changes):
    settings = {
        "soc_entity_id": "sensor.soc",
        "power_entity_id": BAT_IN_OUT_ENTITY_ID,
        "grid_input_power_entity_id": "sensor.grid_input",
        "charge_limit_entity_id": "sensor.limit",
        "power_sign": BatteryPowerSign.UNKNOWN,
        "charge_limit_verified": False,
        "max_age_seconds": 120,
    } | changes
    return ZendureSolarFlowAdapter(hass, **settings)


def _set_fresh_required_states(hass, power: str) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set(BAT_IN_OUT_ENTITY_ID, power, {ATTR_UNIT_OF_MEASUREMENT: "W"})


def _make_fresh(adapter: ZendureSolarFlowAdapter) -> None:
    adapter._started_at = datetime.now(UTC) - timedelta(seconds=1)


def test_bat_in_out_negative_value_is_charge_without_unknown_sign(hass) -> None:
    _set_fresh_required_states(hass, "-291")
    hass.states.async_set("sensor.grid_input", "292", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.charge_power_w == 291
    assert resource.discharge_power_w == 0
    assert resource.grid_input_power_w == 292
    assert BatteryReasonCode.POWER_SIGN_UNKNOWN not in resource.anomalies


def test_bat_in_out_positive_value_is_discharge(hass) -> None:
    _set_fresh_required_states(hass, "58")
    hass.states.async_set("sensor.grid_input", "0", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.charge_power_w == 0
    assert resource.discharge_power_w == 58
    assert resource.grid_input_power_w == 0


def test_bat_in_out_zero_is_inactive(hass) -> None:
    _set_fresh_required_states(hass, "0")
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.charge_power_w == 0
    assert resource.discharge_power_w == 0


def test_unknown_directional_power_is_unavailable(hass) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set(BAT_IN_OUT_ENTITY_ID, STATE_UNKNOWN)
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.UNAVAILABLE
    assert BatteryReasonCode.SOURCE_UNAVAILABLE in resource.anomalies


def test_unavailable_directional_power_is_unavailable(hass) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set(BAT_IN_OUT_ENTITY_ID, STATE_UNAVAILABLE)
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.UNAVAILABLE


def test_pre_start_required_states_are_stale_until_republished(hass) -> None:
    _set_fresh_required_states(hass, "-10")
    adapter = _adapter(hass)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.STALE
    assert BatteryReasonCode.SOURCE_NOT_REFRESHED in resource.anomalies


def test_nan_directional_power_is_inconsistent(hass) -> None:
    _set_fresh_required_states(hass, "nan")
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.INCONSISTENT
    assert BatteryReasonCode.POWER_NON_FINITE in resource.anomalies


def test_charge_max_limit_is_ignored_and_remaining_capacity_stays_unknown(hass) -> None:
    _set_fresh_required_states(hass, "-300")
    hass.states.async_set("sensor.limit", "1000", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(hass, charge_limit_verified=True)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.max_charge_power_w is None
    assert resource.remaining_charge_power_w is None
    assert BatteryReasonCode.REMAINING_POWER_UNAVAILABLE in resource.anomalies


def test_optional_grid_input_diagnostic_never_changes_required_source_health(hass) -> None:
    _set_fresh_required_states(hass, "-10")
    adapter = _adapter(hass)
    _make_fresh(adapter)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.grid_input_power_w is None
    assert BatteryReasonCode.GRID_INPUT_POWER_UNAVAILABLE in resource.anomalies


def test_adapter_has_no_write_or_modbus_api(hass) -> None:
    """Build005 remains unable to command either the battery or the DTU."""
    adapter = _adapter(hass)
    assert not hasattr(adapter, "async_write")
    assert not hasattr(adapter, "async_read_registers")
    assert not hasattr(adapter, "async_tick")
