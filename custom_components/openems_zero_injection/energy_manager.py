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
    def remaining_charge_power_w(self) -> float:
        """Return safe remaining charge capacity; unknown values contribute zero."""
        if not self.available or self.max_charge_power_w is None:
            return 0.0
        current = self.current_charge_power_w or 0.0
        return max(0.0, self.max_charge_power_w - current)


@dataclass(frozen=True, slots=True)
class EnergyManagerSnapshot:
    """Read-only aggregate values exposed as Home Assistant diagnostics."""

    battery_count: int
    total_max_charge_power_w: float
    total_current_charge_power_w: float
    total_remaining_charge_power_w: float
    state: str


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
        available = tuple(battery for battery in self._batteries if battery.available)
        return EnergyManagerSnapshot(
            battery_count=len(self._batteries),
            total_max_charge_power_w=sum(
                battery.max_charge_power_w or 0.0 for battery in available
            ),
            total_current_charge_power_w=sum(
                battery.current_charge_power_w or 0.0 for battery in available
            ),
            total_remaining_charge_power_w=sum(
                battery.remaining_charge_power_w for battery in available
            ),
            state="No batteries configured" if not self._batteries else "Passive",
        )
