"""Passive multi-battery aggregation with no controller or DTU authority."""

from __future__ import annotations

from dataclasses import dataclass

from .battery import BatteryHealth, BatteryReasonCode, BatteryResource


@dataclass(frozen=True, slots=True)
class AggregateCoverage:
    """Whether an aggregate is exhaustive across configured batteries."""

    status: str
    included_resource_ids: tuple[str, ...]
    missing_resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnergyManagerSnapshot:
    """Read-only aggregate values exposed as Home Assistant diagnostics."""

    battery_count: int
    total_max_charge_power_w: float | None
    total_current_charge_power_w: float | None
    total_remaining_charge_power_w: float | None
    state: str
    unknown_reason: str | None
    resources: tuple[BatteryResource, ...]
    max_charge_coverage: AggregateCoverage
    current_charge_coverage: AggregateCoverage
    remaining_charge_coverage: AggregateCoverage


class EnergyManager:
    """Aggregate passive resources; no scheduler or adapter I/O belongs here."""

    def __init__(self, batteries: tuple[BatteryResource, ...] = ()) -> None:
        self._batteries = batteries

    @property
    def batteries(self) -> tuple[BatteryResource, ...]:
        return self._batteries

    def set_batteries(self, batteries: tuple[BatteryResource, ...]) -> None:
        self._batteries = batteries

    def snapshot(self) -> EnergyManagerSnapshot:
        """Return diagnostics without turning partial values into complete sums."""
        if not self._batteries:
            none = _coverage((), ())
            return EnergyManagerSnapshot(
                0, None, None, None, "No batteries configured",
                BatteryReasonCode.NO_BATTERIES_CONFIGURED.value, (), none, none, none,
            )
        max_total, max_coverage = _aggregate(self._batteries, "max_charge_power_w")
        current_total, current_coverage = _aggregate(self._batteries, "charge_power_w")
        remaining_total, remaining_coverage = _aggregate(
            self._batteries, "remaining_charge_power_w"
        )
        healths = {battery.health for battery in self._batteries}
        if all(health is BatteryHealth.HEALTHY for health in healths):
            state = "Passive"
            reason = None
        elif all(health is BatteryHealth.UNAVAILABLE for health in healths):
            state = "No available batteries"
            reason = BatteryReasonCode.SOURCE_UNAVAILABLE.value
        else:
            state = "Passive with partial battery data"
            reason = "partial_battery_data"
        return EnergyManagerSnapshot(
            len(self._batteries), max_total, current_total, remaining_total,
            state, reason, self._batteries, max_coverage, current_coverage,
            remaining_coverage,
        )


def _aggregate(
    batteries: tuple[BatteryResource, ...], field: str
) -> tuple[float | None, AggregateCoverage]:
    """Only publish a total when every configured resource supplies the field."""
    included = tuple(
        battery.resource_id for battery in batteries if getattr(battery, field) is not None
    )
    missing = tuple(
        battery.resource_id for battery in batteries if getattr(battery, field) is None
    )
    coverage = _coverage(included, missing)
    if missing:
        return None, coverage
    return sum(float(getattr(battery, field)) for battery in batteries), coverage


def _coverage(included: tuple[str, ...], missing: tuple[str, ...]) -> AggregateCoverage:
    if not included:
        status = "none"
    elif not missing:
        status = "complete"
    else:
        status = "partial"
    return AggregateCoverage(status, included, missing)
