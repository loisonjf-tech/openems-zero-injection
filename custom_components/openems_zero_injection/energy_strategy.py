"""Pure, manufacturer-neutral energy-strategy contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .battery import BatteryHealth, BatteryResource


class EnergyStrategyReasonCode(StrEnum):
    """Stable, serialisable explanations emitted by energy strategies."""

    CONFIGURED_ZERO_INJECTION_TARGET = "configured_zero_injection_target"


class BatteryPriorityReasonCode(StrEnum):
    """Stable reasons for a Build007 Battery Priority comparison."""

    BATTERY_PRIORITY_SIMULATION = "battery_priority_simulation"
    NO_BATTERY = "battery_priority_no_battery"
    BATTERY_UNAVAILABLE = "battery_priority_battery_unavailable"
    BATTERY_DATA_STALE = "battery_priority_battery_data_stale"
    BATTERY_DATA_INCONSISTENT = "battery_priority_battery_data_inconsistent"
    BATTERY_FAULT = "battery_priority_battery_fault"
    BATTERY_CAPACITY_PARTIAL = "battery_priority_capacity_partial"
    BATTERY_CAPACITY_UNKNOWN = "battery_priority_capacity_unknown"
    BATTERY_FULL = "battery_priority_battery_full"
    TARGET_NOT_EXPORT_ORIENTED = "battery_priority_target_not_export_oriented"


@dataclass(frozen=True, slots=True)
class EnergyStrategyInput:
    """Immutable, Home-Assistant-independent input available before a decision."""

    target_grid_power_w: float
    input_snapshot_id: str
    decision_timestamp: datetime


@dataclass(frozen=True, slots=True)
class BatteryPriorityContext:
    """Generic, read-only battery data available to an energy strategy."""

    resources: tuple[BatteryResource, ...]
    total_remaining_charge_power_w: float | None
    remaining_charge_coverage: str


@dataclass(frozen=True, slots=True)
class BatteryPriorityComparison:
    """Simulation-only comparison; it never becomes a DTU command in Build007."""

    effective_target_grid_power_w: float
    candidate_target_grid_power_w: float
    target_delta_w: float
    candidate_expected_storage_gain_w: float
    reason_code: BatteryPriorityReasonCode
    fallback_used: bool
    eligible_resource_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return primitive-only data suitable for diagnostics and traces."""
        data = asdict(self)
        data["reason_code"] = self.reason_code.value
        return data


@dataclass(frozen=True, slots=True)
class EnergyStrategyDecision:
    """The target contract consumed by the predictive controller.

    ``comparison`` is observability-only. The historical target continues to
    come exclusively from ZeroInjectionStrategy throughout Build007.
    """

    target_grid_power_w: float
    policy_id: str
    reason: str
    confidence: float
    fallback_used: bool
    decision_timestamp: datetime
    input_snapshot_id: str
    reason_code: EnergyStrategyReasonCode
    comparison: BatteryPriorityComparison | None = None


class ZeroInjectionStrategy:
    """Baseline strategy: return the configured target unchanged."""

    policy_id = "zero_injection"
    _LEGACY_REASON = "Configured zero-injection target"

    def decide(self, strategy_input: EnergyStrategyInput) -> EnergyStrategyDecision:
        """Produce the V1 target without battery, DTU or Home Assistant I/O."""
        return EnergyStrategyDecision(
            target_grid_power_w=strategy_input.target_grid_power_w,
            policy_id=self.policy_id,
            reason=self._LEGACY_REASON,
            confidence=1.0,
            fallback_used=False,
            decision_timestamp=strategy_input.decision_timestamp,
            input_snapshot_id=strategy_input.input_snapshot_id,
            reason_code=EnergyStrategyReasonCode.CONFIGURED_ZERO_INJECTION_TARGET,
        )


class BatteryPriorityStrategy:
    """Calculate a bounded candidate target without controlling any device."""

    policy_id = "battery_priority"

    def __init__(
        self,
        *,
        max_reserve_w: float = 25.0,
        max_extra_export_w: float = 25.0,
    ) -> None:
        if max_reserve_w < 0 or max_extra_export_w < 0:
            raise ValueError("Battery Priority bounds must be non-negative")
        self._max_reserve_w = max_reserve_w
        self._max_extra_export_w = max_extra_export_w

    def compare(
        self,
        strategy_input: EnergyStrategyInput,
        context: BatteryPriorityContext | None,
    ) -> BatteryPriorityComparison:
        """Return a conservative candidate or an exact Zero Injection fallback."""
        target = strategy_input.target_grid_power_w
        fallback = lambda reason: self._fallback(target, reason)
        if context is None or not context.resources:
            return fallback(BatteryPriorityReasonCode.NO_BATTERY)
        if target > 0:
            return fallback(BatteryPriorityReasonCode.TARGET_NOT_EXPORT_ORIENTED)
        if any(
            resource.fault or resource.health is BatteryHealth.FAULT
            for resource in context.resources
        ):
            return fallback(BatteryPriorityReasonCode.BATTERY_FAULT)
        if any(
            resource.health is BatteryHealth.STALE for resource in context.resources
        ):
            return fallback(BatteryPriorityReasonCode.BATTERY_DATA_STALE)
        if any(
            resource.health is BatteryHealth.INCONSISTENT
            for resource in context.resources
        ):
            return fallback(BatteryPriorityReasonCode.BATTERY_DATA_INCONSISTENT)
        if any(
            not resource.available or resource.health is BatteryHealth.UNAVAILABLE
            for resource in context.resources
        ):
            return fallback(BatteryPriorityReasonCode.BATTERY_UNAVAILABLE)
        if context.remaining_charge_coverage != "complete":
            return fallback(BatteryPriorityReasonCode.BATTERY_CAPACITY_PARTIAL)
        if context.total_remaining_charge_power_w is None:
            return fallback(BatteryPriorityReasonCode.BATTERY_CAPACITY_UNKNOWN)
        if context.total_remaining_charge_power_w <= 0 or all(
            resource.full is True for resource in context.resources
        ):
            return fallback(BatteryPriorityReasonCode.BATTERY_FULL)
        if any(resource.charge_power_w is None for resource in context.resources):
            return fallback(BatteryPriorityReasonCode.BATTERY_CAPACITY_UNKNOWN)

        reserve = min(
            context.total_remaining_charge_power_w,
            self._max_reserve_w,
            self._max_extra_export_w,
        )
        candidate = target - reserve
        # Explicitly retain the configured maximum intentional extra export.
        candidate = max(candidate, target - self._max_extra_export_w)
        return BatteryPriorityComparison(
            effective_target_grid_power_w=target,
            candidate_target_grid_power_w=candidate,
            target_delta_w=candidate - target,
            candidate_expected_storage_gain_w=reserve,
            reason_code=BatteryPriorityReasonCode.BATTERY_PRIORITY_SIMULATION,
            fallback_used=False,
            eligible_resource_ids=tuple(
                resource.resource_id for resource in context.resources
            ),
        )

    @staticmethod
    def _fallback(
        target: float, reason: BatteryPriorityReasonCode
    ) -> BatteryPriorityComparison:
        return BatteryPriorityComparison(
            effective_target_grid_power_w=target,
            candidate_target_grid_power_w=target,
            target_delta_w=0.0,
            candidate_expected_storage_gain_w=0.0,
            reason_code=reason,
            fallback_used=True,
            eligible_resource_ids=(),
        )


class EnergyStrategyEngine:
    """Select Zero Injection and optionally compare Battery Priority safely."""

    def __init__(
        self,
        strategy: ZeroInjectionStrategy | None = None,
        *,
        battery_context_provider: Callable[[], BatteryPriorityContext] | None = None,
        battery_priority_strategy: BatteryPriorityStrategy | None = None,
    ) -> None:
        self._strategy = strategy or ZeroInjectionStrategy()
        self._battery_context_provider = battery_context_provider
        self._battery_priority_strategy = (
            battery_priority_strategy or BatteryPriorityStrategy()
        )
        self._last_comparison: BatteryPriorityComparison | None = None

    def set_battery_context_provider(
        self, provider: Callable[[], BatteryPriorityContext] | None
    ) -> None:
        """Wire a generic read-only provider without coupling to any adapter."""
        self._battery_context_provider = provider

    @property
    def last_comparison(self) -> BatteryPriorityComparison | None:
        """Return the last simulation-only candidate without recalculating it."""
        return self._last_comparison

    def decide(
        self,
        target_grid_power_w: float,
        *,
        input_snapshot_id: str = "configured_target",
        decision_timestamp: datetime | None = None,
        compare_battery_priority: bool = False,
    ) -> EnergyStrategyDecision:
        """Return Zero Injection; Battery Priority is comparison-only in Build007."""
        strategy_input = EnergyStrategyInput(
            target_grid_power_w=target_grid_power_w,
            input_snapshot_id=input_snapshot_id,
            decision_timestamp=decision_timestamp or datetime.now(UTC),
        )
        decision = self._strategy.decide(strategy_input)
        if not compare_battery_priority:
            self._last_comparison = None
            return decision
        context = (
            self._battery_context_provider()
            if self._battery_context_provider is not None
            else None
        )
        comparison = self._battery_priority_strategy.compare(strategy_input, context)
        self._last_comparison = comparison
        return replace(decision, comparison=comparison)
