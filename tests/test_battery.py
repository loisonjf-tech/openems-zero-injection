"""Tests for the V1.1-ready battery abstraction without battery behavior."""

from custom_components.openems_zero_injection.battery import NullBatteryManager


async def test_null_battery_manager_performs_no_io_and_reports_unknown_state() -> None:
    """V1 has an interface only: it cannot influence a controller decision."""
    state = await NullBatteryManager().async_get_state()

    assert state.is_charging is None
    assert state.can_charge is None
    assert state.soc is None
    assert state.charge_power_w is None
    assert state.max_charge_power_w is None
