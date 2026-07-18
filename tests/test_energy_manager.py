"""Tests for passive EMS resource aggregation."""

from custom_components.openems_zero_injection.energy_manager import (
    BatteryResource,
    EnergyManager,
)


def test_energy_manager_aggregates_available_battery_charge_capacity() -> None:
    """Aggregation is diagnostic-only and never needs a DTU or scheduler."""
    manager = EnergyManager(
        (
            BatteryResource("a", "Battery A", 60, 400, 0, 1000, 800, "charging", True, True),
            BatteryResource("b", "Battery B", 80, 100, 0, 500, 400, "charging", True, True),
            BatteryResource("c", "Battery C", None, None, None, 900, 900, None, False, True),
        )
    )

    snapshot = manager.snapshot()
    assert snapshot.battery_count == 3
    assert snapshot.total_max_charge_power_w == 1500
    assert snapshot.total_current_charge_power_w == 500
    assert snapshot.total_remaining_charge_power_w == 1000
    assert snapshot.state == "Passive"


def test_unknown_or_over_limit_charge_capacity_is_safe() -> None:
    """Missing values and excess charge cannot yield a negative capacity."""
    manager = EnergyManager(
        (
            BatteryResource("a", "Battery A", None, 1200, None, 1000, None, None, True, True),
            BatteryResource("b", "Battery B", None, None, None, None, None, None, True, True),
        )
    )

    assert manager.snapshot().total_remaining_charge_power_w == 0
