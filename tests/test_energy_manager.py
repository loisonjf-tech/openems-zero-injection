"""Tests for passive multi-battery aggregation."""

from custom_components.openems_zero_injection.battery import BatteryHealth, BatteryResource
from custom_components.openems_zero_injection.energy_manager import EnergyManager


def _battery(resource_id: str, *, max_power: float | None, charge: float | None,
             remaining: float | None) -> BatteryResource:
    return BatteryResource(
        resource_id, resource_id, "test", "1", True, BatteryHealth.HEALTHY,
        None, None, max_charge_power_w=max_power, charge_power_w=charge,
        remaining_charge_power_w=remaining,
    )


def test_energy_manager_aggregates_only_complete_capacity() -> None:
    manager = EnergyManager((
        _battery("a", max_power=1000, charge=400, remaining=600),
        _battery("b", max_power=500, charge=100, remaining=400),
    ))

    snapshot = manager.snapshot()
    assert snapshot.total_max_charge_power_w == 1500
    assert snapshot.total_current_charge_power_w == 500
    assert snapshot.total_remaining_charge_power_w == 1000
    assert snapshot.remaining_charge_coverage.status == "complete"


def test_partial_values_are_never_exposed_as_complete_totals() -> None:
    manager = EnergyManager((
        _battery("a", max_power=1000, charge=400, remaining=600),
        _battery("b", max_power=None, charge=None, remaining=None),
    ))

    snapshot = manager.snapshot()
    assert snapshot.total_max_charge_power_w is None
    assert snapshot.total_remaining_charge_power_w is None
    assert snapshot.remaining_charge_coverage.status == "partial"
    assert snapshot.remaining_charge_coverage.missing_resource_ids == ("b",)


def test_no_configured_battery_has_unknown_power_totals() -> None:
    snapshot = EnergyManager().snapshot()
    assert snapshot.state == "No batteries configured"
    assert snapshot.total_max_charge_power_w is None
    assert snapshot.unknown_reason == "no_batteries_configured"
