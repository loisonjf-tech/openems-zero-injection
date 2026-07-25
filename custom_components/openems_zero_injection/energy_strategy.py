"""Pure, manufacturer-neutral energy-strategy contracts."""

from __future__ import annotations

from collections import deque
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
    DISABLED = "battery_priority_disabled"
    VERIFIED_MODE_RESERVED = "battery_priority_verified_mode_reserved"
    CHARGE_CONFIRMATION_PENDING = "battery_priority_charge_confirmation_pending"
    BATTERY_DISCHARGING = "battery_priority_battery_discharging"
    BATTERY_IDLE = "battery_priority_battery_idle"
    OBSERVED_CONSERVATIVE = "battery_priority_observed_conservative"


class BatteryPriorityMode(StrEnum):
    """Stable configuration modes; only the conservative mode is active now."""

    DISABLED = "disabled"
    OBSERVED_CONSERVATIVE = "observed_conservative"
    VERIFIED = "verified"


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
    mode: BatteryPriorityMode = BatteryPriorityMode.DISABLED
    applied_margin_w: float = 0.0
    consecutive_charge_samples: int = 0
    charge_threshold_w: float = 0.0
    observed_charge_power_w: float | None = None
    observed_discharge_power_w: float | None = None

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
            mode=BatteryPriorityMode.OBSERVED_CONSERVATIVE,
            applied_margin_w=reserve,
        )

    def observed_conservative(
        self,
        strategy_input: EnergyStrategyInput,
        context: BatteryPriorityContext | None,
        *,
        consecutive_charge_samples: int,
        confirmation_samples: int,
        charge_threshold_w: float,
        mode: BatteryPriorityMode,
    ) -> BatteryPriorityComparison:
        """Return a bounded Production candidate from current, confirmed charge.

        No maximum-charge estimate is inferred.  The charge direction must be
        observed afresh on each strategy evaluation; a discharge immediately
        returns the configured Zero Injection target.
        """
        target = strategy_input.target_grid_power_w
        if mode is BatteryPriorityMode.DISABLED:
            return self._fallback(target, BatteryPriorityReasonCode.DISABLED, mode=mode)
        if mode is BatteryPriorityMode.VERIFIED:
            return self._fallback(
                target, BatteryPriorityReasonCode.VERIFIED_MODE_RESERVED, mode=mode
            )
        basic = self._observed_data_reason(context, target)
        if basic is not None:
            return self._fallback(target, basic, mode=mode)
        assert context is not None
        charge_power = sum(
            resource.charge_power_w or 0.0 for resource in context.resources
        )
        discharge_power = sum(
            resource.discharge_power_w or 0.0 for resource in context.resources
        )
        if discharge_power > charge_threshold_w:
            return self._fallback(
                target,
                BatteryPriorityReasonCode.BATTERY_DISCHARGING,
                mode=mode,
                observed_charge_power_w=charge_power,
                observed_discharge_power_w=discharge_power,
            )
        if charge_power <= charge_threshold_w:
            return self._fallback(
                target,
                BatteryPriorityReasonCode.BATTERY_IDLE,
                mode=mode,
                observed_charge_power_w=charge_power,
                observed_discharge_power_w=discharge_power,
            )
        if consecutive_charge_samples < confirmation_samples:
            return self._fallback(
                target,
                BatteryPriorityReasonCode.CHARGE_CONFIRMATION_PENDING,
                mode=mode,
                consecutive_charge_samples=consecutive_charge_samples,
                observed_charge_power_w=charge_power,
                observed_discharge_power_w=discharge_power,
            )
        margin = min(self._max_reserve_w, self._max_extra_export_w)
        candidate = target - margin
        return BatteryPriorityComparison(
            effective_target_grid_power_w=target,
            candidate_target_grid_power_w=candidate,
            target_delta_w=-margin,
            candidate_expected_storage_gain_w=margin,
            reason_code=BatteryPriorityReasonCode.OBSERVED_CONSERVATIVE,
            fallback_used=False,
            eligible_resource_ids=tuple(
                resource.resource_id for resource in context.resources
            ),
            mode=mode,
            applied_margin_w=margin,
            consecutive_charge_samples=consecutive_charge_samples,
            charge_threshold_w=charge_threshold_w,
            observed_charge_power_w=charge_power,
            observed_discharge_power_w=discharge_power,
        )

    @staticmethod
    def _observed_data_reason(
        context: BatteryPriorityContext | None, target: float
    ) -> BatteryPriorityReasonCode | None:
        if context is None or not context.resources:
            return BatteryPriorityReasonCode.NO_BATTERY
        if target > 0:
            return BatteryPriorityReasonCode.TARGET_NOT_EXPORT_ORIENTED
        if any(
            resource.fault or resource.health is BatteryHealth.FAULT
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.BATTERY_FAULT
        if any(
            resource.health is BatteryHealth.STALE for resource in context.resources
        ):
            return BatteryPriorityReasonCode.BATTERY_DATA_STALE
        if any(
            resource.health is BatteryHealth.INCONSISTENT
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.BATTERY_DATA_INCONSISTENT
        if any(
            not resource.available or resource.health is BatteryHealth.UNAVAILABLE
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.BATTERY_UNAVAILABLE
        if any(
            resource.charge_power_w is None or resource.discharge_power_w is None
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.BATTERY_CAPACITY_UNKNOWN
        return None

    @staticmethod
    def _fallback(
        target: float,
        reason: BatteryPriorityReasonCode,
        *,
        mode: BatteryPriorityMode = BatteryPriorityMode.DISABLED,
        consecutive_charge_samples: int = 0,
        observed_charge_power_w: float | None = None,
        observed_discharge_power_w: float | None = None,
    ) -> BatteryPriorityComparison:
        return BatteryPriorityComparison(
            effective_target_grid_power_w=target,
            candidate_target_grid_power_w=target,
            target_delta_w=0.0,
            candidate_expected_storage_gain_w=0.0,
            reason_code=reason,
            fallback_used=True,
            eligible_resource_ids=(),
            mode=mode,
            consecutive_charge_samples=consecutive_charge_samples,
            observed_charge_power_w=observed_charge_power_w,
            observed_discharge_power_w=observed_discharge_power_w,
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
        self._battery_priority_mode = BatteryPriorityMode.DISABLED
        self._battery_priority_charge_threshold_w = 50.0
        self._battery_priority_confirmation_samples = 3
        self._consecutive_charge_samples = 0
        self._activation_count = 0
        self._fallback_count = 0
        self._transition_history: deque[dict[str, Any]] = deque(maxlen=20)
        self._last_runtime_state: str | None = None
        self._last_battery_signature: tuple[object, ...] | None = None

    def set_battery_context_provider(
        self, provider: Callable[[], BatteryPriorityContext] | None
    ) -> None:
        """Wire a generic read-only provider without coupling to any adapter."""
        self._battery_context_provider = provider

    def configure_battery_priority(
        self,
        *,
        mode: str,
        margin_w: float,
        charge_threshold_w: float,
        confirmation_samples: int,
    ) -> None:
        """Apply bounded, explicit settings without coupling to Home Assistant."""
        try:
            parsed_mode = BatteryPriorityMode(mode)
        except ValueError:
            parsed_mode = BatteryPriorityMode.DISABLED
        if margin_w < 0 or charge_threshold_w < 0 or confirmation_samples < 1:
            raise ValueError("Invalid Battery Priority configuration")
        self._battery_priority_mode = parsed_mode
        self._battery_priority_strategy = BatteryPriorityStrategy(
            max_reserve_w=margin_w, max_extra_export_w=margin_w
        )
        self._battery_priority_charge_threshold_w = charge_threshold_w
        self._battery_priority_confirmation_samples = confirmation_samples
        self._last_battery_signature = None
        self._reset_charge_confirmation("configuration_changed")

    @property
    def battery_priority_diagnostics(self) -> dict[str, Any]:
        """Return primitive diagnostics; this never reads adapters or Modbus."""
        comparison = self._last_comparison
        return {
            "mode": self._battery_priority_mode.value,
            "applied_margin_w": comparison.applied_margin_w if comparison else 0.0,
            "zero_injection_target_grid_power_w": (
                comparison.effective_target_grid_power_w if comparison else None
            ),
            "final_target_grid_power_w": (
                comparison.candidate_target_grid_power_w if comparison else None
            ),
            "consecutive_charge_samples": self._consecutive_charge_samples,
            "confirmation_samples": self._battery_priority_confirmation_samples,
            "charge_threshold_w": self._battery_priority_charge_threshold_w,
            "observed_charge_power_w": (
                comparison.observed_charge_power_w if comparison else None
            ),
            "observed_discharge_power_w": (
                comparison.observed_discharge_power_w if comparison else None
            ),
            "reason_code": comparison.reason_code.value if comparison else None,
            "activation_count": self._activation_count,
            "fallback_count": self._fallback_count,
            "transitions": tuple(self._transition_history),
        }

    def battery_priority_input_changed(self) -> bool:
        """Tell the controller when a fresh battery transition needs evaluation.

        This is intentionally passive: it only examines the coordinator's
        already-acquired snapshot and does not cause polling or adapter I/O.
        """
        if self._battery_priority_mode is not BatteryPriorityMode.OBSERVED_CONSERVATIVE:
            return False
        context = (
            self._battery_context_provider()
            if self._battery_context_provider is not None
            else None
        )
        return self._battery_signature(context) != self._last_battery_signature

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
        activate_battery_priority: bool = False,
    ) -> EnergyStrategyDecision:
        """Return Zero Injection; Battery Priority is comparison-only in Build007."""
        strategy_input = EnergyStrategyInput(
            target_grid_power_w=target_grid_power_w,
            input_snapshot_id=input_snapshot_id,
            decision_timestamp=decision_timestamp or datetime.now(UTC),
        )
        decision = self._strategy.decide(strategy_input)
        if activate_battery_priority:
            # The default must remain byte-for-byte equivalent in behaviour to
            # the historical Production path: no alternate target, trace, or
            # fallback state is generated while the feature is disabled.
            if self._battery_priority_mode is BatteryPriorityMode.DISABLED:
                self._last_comparison = None
                return decision
            comparison = self._observed_conservative_comparison(strategy_input)
            self._last_comparison = comparison
            if comparison.fallback_used:
                return replace(decision, comparison=comparison, fallback_used=True)
            return replace(
                decision,
                target_grid_power_w=comparison.candidate_target_grid_power_w,
                policy_id="battery_priority_observed_conservative",
                reason=comparison.reason_code.value,
                confidence=0.5,
                comparison=comparison,
            )
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

    def _observed_conservative_comparison(
        self, strategy_input: EnergyStrategyInput
    ) -> BatteryPriorityComparison:
        context = (
            self._battery_context_provider()
            if self._battery_context_provider is not None
            else None
        )
        signature = self._battery_signature(context)
        new_sample = signature != self._last_battery_signature
        self._last_battery_signature = signature
        self._update_charge_confirmation(context, new_sample=new_sample)
        comparison = self._battery_priority_strategy.observed_conservative(
            strategy_input,
            context,
            consecutive_charge_samples=self._consecutive_charge_samples,
            confirmation_samples=self._battery_priority_confirmation_samples,
            charge_threshold_w=self._battery_priority_charge_threshold_w,
            mode=self._battery_priority_mode,
        )
        runtime_state = "fallback" if comparison.fallback_used else "active"
        if runtime_state != self._last_runtime_state:
            if comparison.fallback_used:
                self._fallback_count += 1
            else:
                self._activation_count += 1
            self._record_transition(runtime_state, comparison.reason_code.value)
            self._last_runtime_state = runtime_state
        return comparison

    def _update_charge_confirmation(
        self,
        context: BatteryPriorityContext | None,
        *,
        new_sample: bool,
    ) -> None:
        """Count only fresh charging samples; reset immediately on any doubt."""
        reason = self._battery_priority_strategy._observed_data_reason(context, -1.0)
        if reason is not None or context is None:
            self._reset_charge_confirmation(reason.value if reason else "no_context")
            return
        charge = sum(resource.charge_power_w or 0.0 for resource in context.resources)
        discharge = sum(
            resource.discharge_power_w or 0.0 for resource in context.resources
        )
        if discharge > self._battery_priority_charge_threshold_w:
            self._reset_charge_confirmation(
                BatteryPriorityReasonCode.BATTERY_DISCHARGING.value
            )
        elif charge > self._battery_priority_charge_threshold_w:
            if new_sample:
                self._consecutive_charge_samples += 1
        else:
            self._reset_charge_confirmation(BatteryPriorityReasonCode.BATTERY_IDLE.value)

    def _reset_charge_confirmation(self, reason: str) -> None:
        if self._consecutive_charge_samples:
            self._record_transition("reset", reason)
        self._consecutive_charge_samples = 0

    def _record_transition(self, state: str, reason_code: str) -> None:
        self._transition_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "state": state,
                "reason_code": reason_code,
                "consecutive_charge_samples": self._consecutive_charge_samples,
            }
        )

    @staticmethod
    def _battery_signature(
        context: BatteryPriorityContext | None,
    ) -> tuple[object, ...] | None:
        if context is None:
            return None
        return tuple(
            (
                resource.resource_id,
                resource.last_updated,
                resource.health.value,
                resource.available,
                resource.charge_power_w,
                resource.discharge_power_w,
            )
            for resource in context.resources
        )
