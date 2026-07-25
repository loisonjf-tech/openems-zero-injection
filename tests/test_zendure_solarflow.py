"""Tests for the Build005 SolarFlow read-only adapter corrections."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State

from custom_components.openems_zero_injection.battery import (
    BatteryHealth,
    BatteryPowerSign,
    BatteryReasonCode,
)
from custom_components.openems_zero_injection.battery_adapters.zendure_solarflow import (
    BAT_IN_OUT_ENTITY_ID,
    ZendureSolarFlowAdapter,
)
from custom_components.openems_zero_injection.energy_manager import EnergyManager


def _adapter(hass, **changes):
    settings = {
        "soc_entity_id": "sensor.soc",
        "power_entity_id": BAT_IN_OUT_ENTITY_ID,
        "grid_input_power_entity_id": "sensor.grid_input",
        "charge_limit_entity_id": "sensor.limit",
        "power_sign": BatteryPowerSign.UNKNOWN,
        "charge_limit_verified": False,
        "max_age_seconds": 30,
    } | changes
    return ZendureSolarFlowAdapter(hass, **settings)


def _set_fresh_required_states(hass, power: str) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set(BAT_IN_OUT_ENTITY_ID, power, {ATTR_UNIT_OF_MEASUREMENT: "W"})


def _make_fresh(adapter: ZendureSolarFlowAdapter) -> None:
    adapter._started_at = datetime.now(UTC) - timedelta(seconds=1)


def _state(entity_id: str, value: str, unit: str, timestamp: datetime) -> State:
    """Build a deterministic Home Assistant source publication."""
    return State(
        entity_id,
        value,
        {ATTR_UNIT_OF_MEASUREMENT: unit},
        last_changed=timestamp,
        last_updated=timestamp,
    )


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


def test_required_source_freshness_identifies_the_stale_input(hass) -> None:
    """Diagnostics identify SOC or directional power instead of a vague stale state."""
    _set_fresh_required_states(hass, "-10")
    adapter = _adapter(hass)
    _make_fresh(adapter)
    resource = adapter.read_resource()

    assert resource.source_freshness == {
        "soc_percent": "fresh",
        "directional_power_w": "fresh",
        "grid_input_power_w": "unavailable",
    }
    assert resource.source_timestamps["soc_percent"] is not None
    assert resource.source_ages_seconds["directional_power_w"] is not None
    assert resource.source_max_age_seconds == {
        "soc_percent": 600,
        "directional_power_w": 30,
        "grid_input_power_w": 30,
    }


def test_soc_is_fresh_for_its_longer_source_threshold(hass) -> None:
    """A three-minute-old SOC remains valid while directional power is fresh."""
    now = datetime.now(UTC)
    adapter = _adapter(hass, max_age_seconds=30)
    adapter._started_at = now - timedelta(minutes=4)
    states = {
        "sensor.soc": _state("sensor.soc", "50", "%", now - timedelta(minutes=3)),
        BAT_IN_OUT_ENTITY_ID: _state(BAT_IN_OUT_ENTITY_ID, "-291", "W", now),
        "sensor.grid_input": _state("sensor.grid_input", "292", "W", now),
    }

    with patch.object(hass.states, "get", side_effect=states.get):
        resource = adapter.read_resource(now)

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.charge_power_w == 291
    assert resource.source_freshness["soc_percent"] == "fresh"
    assert resource.source_max_age_seconds["soc_percent"] == 600


def test_stale_soc_alone_does_not_block_fresh_charge_observation(hass) -> None:
    """A slow SOC source must not turn fresh directional power into stale data."""
    now = datetime.now(UTC)
    adapter = _adapter(hass, max_age_seconds=30)
    adapter._started_at = now - timedelta(minutes=12)
    states = {
        "sensor.soc": _state("sensor.soc", "50", "%", now - timedelta(seconds=601)),
        BAT_IN_OUT_ENTITY_ID: _state(BAT_IN_OUT_ENTITY_ID, "-291", "W", now),
        "sensor.grid_input": _state("sensor.grid_input", "292", "W", now),
    }

    with patch.object(hass.states, "get", side_effect=states.get):
        resource = adapter.read_resource(now)

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.charge_power_w == 291
    assert resource.source_freshness["soc_percent"] == "stale"
    assert resource.source_freshness["directional_power_w"] == "fresh"
    assert BatteryReasonCode.DATA_STALE in resource.anomalies
    assert EnergyManager((resource,)).snapshot().state == "Passive"


def test_stale_directional_power_keeps_the_existing_safety_fallback(hass) -> None:
    """The short directional-power threshold remains the strategy safety gate."""
    now = datetime.now(UTC)
    adapter = _adapter(hass, max_age_seconds=30)
    adapter._started_at = now - timedelta(minutes=2)
    states = {
        "sensor.soc": _state("sensor.soc", "50", "%", now),
        BAT_IN_OUT_ENTITY_ID: _state(
            BAT_IN_OUT_ENTITY_ID, "-291", "W", now - timedelta(seconds=31)
        ),
        "sensor.grid_input": _state("sensor.grid_input", "292", "W", now),
    }

    with patch.object(hass.states, "get", side_effect=states.get):
        resource = adapter.read_resource(now)

    assert resource.health is BatteryHealth.STALE
    assert resource.source_freshness["directional_power_w"] == "stale"


def test_stale_optional_grid_input_uses_the_short_threshold_only(hass) -> None:
    """An old diagnostic gridInputPower never invalidates fresh battery power."""
    now = datetime.now(UTC)
    adapter = _adapter(hass, max_age_seconds=30)
    adapter._started_at = now - timedelta(minutes=2)
    states = {
        "sensor.soc": _state("sensor.soc", "50", "%", now),
        BAT_IN_OUT_ENTITY_ID: _state(BAT_IN_OUT_ENTITY_ID, "-291", "W", now),
        "sensor.grid_input": _state(
            "sensor.grid_input", "292", "W", now - timedelta(seconds=31)
        ),
    }

    with patch.object(hass.states, "get", side_effect=states.get):
        resource = adapter.read_resource(now)

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.source_freshness["grid_input_power_w"] == "stale"


def test_adapter_has_no_write_or_modbus_api(hass) -> None:
    """Build005 remains unable to command either the battery or the DTU."""
    adapter = _adapter(hass)
    assert not hasattr(adapter, "async_write")
    assert not hasattr(adapter, "async_read_registers")
    assert not hasattr(adapter, "async_tick")
