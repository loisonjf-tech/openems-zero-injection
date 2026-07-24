"""Passive, manufacturer-neutral Energy Manager foundation.

The V1 controller never reads this module. It aggregates energy resources for
diagnostics only, ready for a future EMS policy validated independently.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BatteryResource:
    """Describe one autonomous battery without performing any I/O."""

    resource_id: str
    name: str
    soc: float | None
    current_charge_power_w: float | None
    current_discharge_power_w: float | None
    max_charge_power_w: float | None
    max_discharge_power_w: float | None
    state: str | None
    available: bool
    autonomous: bool

    @property
    def remaining_charge_power_w(self) -> float | None:
        """Return remaining capacity without ever converting unknown into zero."""
        if (
            not self.available
            or self.max_charge_power_w is None
            or self.current_charge_power_w is None
        ):
            return None
        current = self.current_charge_power_w
        return max(0.0, self.max_charge_power_w - current)


@dataclass(frozen=True, slots=True)
class EnergyManagerSnapshot:
    """Read-only aggregate values exposed as Home Assistant diagnostics."""

    battery_count: int
    total_max_charge_power_w: float | None
    total_current_charge_power_w: float | None
    total_remaining_charge_power_w: float | None
    state: str
    unknown_reason: str | None


class EnergyManager:
    """Aggregate resources passively; it has no scheduler or DTU dependency."""

    def __init__(self, batteries: tuple[BatteryResource, ...] = ()) -> None:
        self._batteries = batteries

    @property
    def batteries(self) -> tuple[BatteryResource, ...]:
        """Return all independently modeled battery resources."""
        return self._batteries

    def set_batteries(self, batteries: tuple[BatteryResource, ...]) -> None:
        """Replace the passive resource list for a future adapter integration."""
        self._batteries = batteries

    def snapshot(self) -> EnergyManagerSnapshot:
        """Calculate diagnostic-only aggregate charge capacity."""
        if not self._batteries:
            return EnergyManagerSnapshot(
                battery_count=0,
                total_max_charge_power_w=None,
                total_current_charge_power_w=None,
                total_remaining_charge_power_w=None,
                state="No batteries configured",
                unknown_reason="No batteries configured",
            )
        available = tuple(battery for battery in self._batteries if battery.available)
        max_values = [battery.max_charge_power_w for battery in available]
        current_values = [battery.current_charge_power_w for battery in available]
        remaining_values = [battery.remaining_charge_power_w for battery in available]
        unknown_reason = None
        if not available:
            unknown_reason = "No available batteries"
        elif any(value is None for value in max_values + current_values + remaining_values):
            unknown_reason = "Battery charge data is incomplete"
        return EnergyManagerSnapshot(
            battery_count=len(self._batteries),
            total_max_charge_power_w=(
                sum(value for value in max_values if value is not None)
                if available and all(value is not None for value in max_values)
                else None
            ),
            total_current_charge_power_w=(
                sum(value for value in current_values if value is not None)
                if available and all(value is not None for value in current_values)
                else None
            ),
            total_remaining_charge_power_w=(
                sum(value for value in remaining_values if value is not None)
                if available and all(value is not None for value in remaining_values)
                else None
            ),
            state="No batteries configured" if not self._batteries else "Passive",
            unknown_reason=unknown_reason,
        )
