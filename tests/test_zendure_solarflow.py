"""Tests for the Build005 read-only SolarFlow adapter."""

from datetime import UTC, datetime, timedelta

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT

from custom_components.openems_zero_injection.battery import (
    BatteryHealth,
    BatteryPowerSign,
    BatteryReasonCode,
)
from custom_components.openems_zero_injection.battery_adapters.zendure_solarflow import (
    ZendureSolarFlowAdapter,
)


def _adapter(hass, **changes):
    settings = {
        "soc_entity_id": "sensor.soc",
        "power_entity_id": "sensor.power",
        "charge_limit_entity_id": "sensor.limit",
        "power_sign": BatteryPowerSign.UNKNOWN,
        "charge_limit_verified": False,
        "max_age_seconds": 120,
    } | changes
    return ZendureSolarFlowAdapter(hass, **settings)


def test_unknown_power_sign_keeps_resource_healthy_but_capability_unknown(hass) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set("sensor.power", "300", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(hass)
    adapter._started_at = datetime.now(UTC) - timedelta(seconds=1)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.HEALTHY
    assert resource.charge_power_w is None
    assert BatteryReasonCode.POWER_SIGN_UNKNOWN in resource.anomalies


def test_invalid_soc_is_inconsistent_and_nan_is_not_accepted(hass) -> None:
    hass.states.async_set("sensor.soc", "nan", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set("sensor.power", "10", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(hass, power_sign=BatteryPowerSign.POSITIVE_CHARGING)
    adapter._started_at = datetime.now(UTC) - timedelta(seconds=1)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.INCONSISTENT
    assert BatteryReasonCode.POWER_NON_FINITE in resource.anomalies


def test_remaining_power_needs_verified_limit_and_known_charge(hass) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set("sensor.power", "300", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    hass.states.async_set("sensor.limit", "1000", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(
        hass, power_sign=BatteryPowerSign.POSITIVE_CHARGING,
        charge_limit_verified=True,
    )
    adapter._started_at = datetime.now(UTC) - timedelta(seconds=1)

    resource = adapter.read_resource()

    assert resource.max_charge_power_w == 1000
    assert resource.remaining_charge_power_w == 700


def test_restored_pre_start_states_are_stale_until_new_publication(hass) -> None:
    hass.states.async_set("sensor.soc", "50", {ATTR_UNIT_OF_MEASUREMENT: "%"})
    hass.states.async_set("sensor.power", "300", {ATTR_UNIT_OF_MEASUREMENT: "W"})
    adapter = _adapter(hass)

    resource = adapter.read_resource()

    assert resource.health is BatteryHealth.STALE
    assert BatteryReasonCode.SOURCE_NOT_REFRESHED in resource.anomalies


def test_adapter_has_no_write_or_modbus_api(hass) -> None:
    """Build005 cannot command either the battery or the DTU."""
    adapter = _adapter(hass)
    assert not hasattr(adapter, "async_write")
    assert not hasattr(adapter, "async_read_registers")
    assert not hasattr(adapter, "async_tick")
