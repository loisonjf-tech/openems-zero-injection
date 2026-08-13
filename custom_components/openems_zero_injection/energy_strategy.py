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


class DtuControlDirective(StrEnum):
    """Actuator-neutral intent produced by the energy strategy."""

    NORMAL_REGULATION = "normal_regulation"
    RELEASE_DTU_TO_MAXIMUM = "release_dtu_to_maximum"


class CapacityReleaseState(StrEnum):
    """Explicit runtime states of the Capacity Release safety policy."""

    RELEASE = "capacity_release"
    PROBE = "capacity_probe"
    ZERO_INJECTION = "zero_injection"


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
    CAPACITY_RELEASE_ACTIVE = "battery_capacity_release_active"
    CAPACITY_RELEASE_DISCHARGING = "battery_capacity_release_discharging"
    CAPACITY_RELEASE_FULL = "battery_capacity_release_full"
    CAPACITY_RELEASE_SATURATED = "battery_capacity_release_saturated"
    CAPACITY_RELEASE_WAITING_TO_RELEASE = "battery_capacity_release_waiting_to_release"
    CAPACITY_RELEASE_HOLD_NORMAL = "battery_capacity_release_hold_normal"
    CAPACITY_RELEASE_HOLD_RELEASE = "battery_capacity_release_hold_release"
    CAPACITY_RELEASE_CAPACITY_UNKNOWN = "battery_capacity_release_capacity_unknown"
    CAPACITY_RELEASE_CAPACITY_STALE = "battery_capacity_release_capacity_stale"
    CAPACITY_RELEASE_SOC_STALE = "battery_capacity_release_soc_stale"
    CAPACITY_PROBE_ACTIVE = "battery_capacity_probe_active"
    CAPACITY_PROBE_CHARGE_CONFIRMATION_PENDING = (
        "battery_capacity_probe_charge_confirmation_pending"
    )


class BatteryPriorityMode(StrEnum):
    """Stable configuration modes for safe Battery Priority increments."""

    DISABLED = "disabled"
    OBSERVED_CONSERVATIVE = "observed_conservative"
    CAPACITY_RELEASE = "capacity_release"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class EnergyStrategyInput:
    """Immutable, Home-Assistant-independent input available before a decision."""

    target_grid_power_w: float
    input_snapshot_id: str
    decision_timestamp: datetime
    grid_power_w: float | None = None
    grid_source_timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class BatteryPriorityContext:
    """Generic, read-only battery data available to an energy strategy."""

    resources: tuple[BatteryResource, ...]
    total_remaining_charge_power_w: float | None
    remaining_charge_coverage: str


@dataclass(frozen=True, slots=True)
class BatteryPriorityComparison:
    """Read-only explanation of Battery Priority's current policy result."""

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
    max_charge_power_w: float | None = None
    remaining_charge_power_w: float | None = None
    dtu_control_directive: DtuControlDirective = DtuControlDirective.NORMAL_REGULATION
    capacity_release_state: CapacityReleaseState = CapacityReleaseState.ZERO_INJECTION

    def as_dict(self) -> dict[str, Any]:
        """Return primitive-only data suitable for diagnostics and traces."""
        data = asdict(self)
        data["reason_code"] = self.reason_code.value
        data["dtu_control_directive"] = self.dtu_control_directive.value
        data["capacity_release_state"] = self.capacity_release_state.value
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
    dtu_control_directive: DtuControlDirective = DtuControlDirective.NORMAL_REGULATION
    requested_dtu_limit_percent: int | None = None


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
    _MAINTAIN_CHARGE_THRESHOLD_W = 5.0
    _CAPACITY_RELEASE_DISCHARGE_THRESHOLD_W = 5.0

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
        consecutive_low_charge_samples: int,
        confirmation_samples: int,
        charge_threshold_w: float,
        priority_active: bool,
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
        if not priority_active and charge_power <= charge_threshold_w:
            return self._fallback(
                target,
                BatteryPriorityReasonCode.BATTERY_IDLE,
                mode=mode,
                observed_charge_power_w=charge_power,
                observed_discharge_power_w=discharge_power,
            )
        if priority_active and (
            consecutive_low_charge_samples >= confirmation_samples
        ):
            return self._fallback(
                target,
                BatteryPriorityReasonCode.BATTERY_IDLE,
                mode=mode,
                observed_charge_power_w=charge_power,
                observed_discharge_power_w=discharge_power,
            )
        if not priority_active and consecutive_charge_samples < confirmation_samples:
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

    def capacity_release(
        self,
        strategy_input: EnergyStrategyInput,
        context: BatteryPriorityContext | None,
        *,
        release_state: CapacityReleaseState,
        consecutive_saturation_samples: int,
        consecutive_probe_charge_samples: int,
        confirmation_samples: int,
        saturation_tolerance_w: float,
        mode: BatteryPriorityMode,
    ) -> BatteryPriorityComparison:
        """Decide whether a verified battery capacity warrants DTU release."""
        target = strategy_input.target_grid_power_w
        reason = self._capacity_release_reason(context, target)
        if reason is not None:
            return self._fallback(target, reason, mode=mode)
        assert context is not None
        max_charge = sum(
            resource.max_charge_power_w or 0.0 for resource in context.resources
        )
        charge = sum(resource.charge_power_w or 0.0 for resource in context.resources)
        discharge = sum(
            resource.discharge_power_w or 0.0 for resource in context.resources
        )
        remaining = max(max_charge - charge, 0.0)
        full = any(
            resource.full is True
            or (resource.soc_percent is not None and resource.soc_percent >= 100)
            for resource in context.resources
        )
        # A full or confirmed-saturated battery has no usable headroom. Those
        # two safety facts are absolute: an old discharge observation must not
        # leave the DTU released while excess PV is injected to the grid.
        if full:
            return self._capacity_fallback(
                target, BatteryPriorityReasonCode.CAPACITY_RELEASE_FULL, mode, charge,
                discharge, max_charge, remaining,
            )
        if (
            release_state is CapacityReleaseState.ZERO_INJECTION
            and consecutive_saturation_samples >= confirmation_samples
        ):
            return self._capacity_fallback(
                target, BatteryPriorityReasonCode.CAPACITY_RELEASE_SATURATED, mode,
                charge, discharge, max_charge, remaining,
            )
        if release_state is CapacityReleaseState.PROBE:
            return BatteryPriorityComparison(
                effective_target_grid_power_w=target,
                candidate_target_grid_power_w=-100.0,
                target_delta_w=-100.0 - target,
                candidate_expected_storage_gain_w=remaining,
                reason_code=(
                    BatteryPriorityReasonCode.CAPACITY_PROBE_CHARGE_CONFIRMATION_PENDING
                    if consecutive_probe_charge_samples
                    else BatteryPriorityReasonCode.CAPACITY_PROBE_ACTIVE
                ),
                fallback_used=False,
                eligible_resource_ids=tuple(
                    resource.resource_id for resource in context.resources
                ),
                mode=mode,
                observed_charge_power_w=charge,
                observed_discharge_power_w=discharge,
                max_charge_power_w=max_charge,
                remaining_charge_power_w=remaining,
                capacity_release_state=CapacityReleaseState.PROBE,
            )
        if release_state is CapacityReleaseState.ZERO_INJECTION:
            return self._capacity_fallback(
                target,
                BatteryPriorityReasonCode.CAPACITY_RELEASE_HOLD_NORMAL,
                mode,
                charge,
                discharge,
                max_charge,
                remaining,
            )
        # Below the saturation boundary, a confirmed discharge is evidence
        # that the site needs available PV. It immediately releases the DTU,
        # but can never override the two conditions above.
        if discharge > self._CAPACITY_RELEASE_DISCHARGE_THRESHOLD_W:
            return BatteryPriorityComparison(
                effective_target_grid_power_w=target,
                candidate_target_grid_power_w=target,
                target_delta_w=0.0,
                candidate_expected_storage_gain_w=remaining,
                reason_code=BatteryPriorityReasonCode.CAPACITY_RELEASE_DISCHARGING,
                fallback_used=False,
                eligible_resource_ids=tuple(
                    resource.resource_id for resource in context.resources
                ),
                mode=mode,
                observed_charge_power_w=charge,
                observed_discharge_power_w=discharge,
                max_charge_power_w=max_charge,
                remaining_charge_power_w=remaining,
                dtu_control_directive=DtuControlDirective.RELEASE_DTU_TO_MAXIMUM,
                capacity_release_state=CapacityReleaseState.RELEASE,
            )
        # Releasing an under-used battery capacity must not depend on the
        # SolarFlow publishing a changing zero-W state.  The lower hysteresis
        # boundary therefore releases immediately from one coherent snapshot;
        # only saturation requires three distinct fresh publications.
        return BatteryPriorityComparison(
            effective_target_grid_power_w=target,
            candidate_target_grid_power_w=target,
            target_delta_w=0.0,
            candidate_expected_storage_gain_w=remaining,
            reason_code=BatteryPriorityReasonCode.CAPACITY_RELEASE_ACTIVE,
            fallback_used=False,
            eligible_resource_ids=tuple(
                resource.resource_id for resource in context.resources
            ),
            mode=mode,
            observed_charge_power_w=charge,
            observed_discharge_power_w=discharge,
            max_charge_power_w=max_charge,
            remaining_charge_power_w=remaining,
            dtu_control_directive=DtuControlDirective.RELEASE_DTU_TO_MAXIMUM,
            capacity_release_state=CapacityReleaseState.RELEASE,
        )

    @staticmethod
    def _capacity_fallback(
        target: float,
        reason: BatteryPriorityReasonCode,
        mode: BatteryPriorityMode,
        charge: float,
        discharge: float,
        max_charge: float,
        remaining: float,
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
            observed_charge_power_w=charge,
            observed_discharge_power_w=discharge,
            max_charge_power_w=max_charge,
            remaining_charge_power_w=remaining,
        )

    @staticmethod
    def _capacity_release_reason(
        context: BatteryPriorityContext | None, target: float
    ) -> BatteryPriorityReasonCode | None:
        basic = BatteryPriorityStrategy._observed_data_reason(context, target)
        if basic is not None:
            return basic
        assert context is not None
        if any(
            resource.source_freshness.get("soc_percent") != "fresh"
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.CAPACITY_RELEASE_SOC_STALE
        if any(
            resource.source_freshness.get("max_charge_power_w") not in {"fresh", "cached"}
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.CAPACITY_RELEASE_CAPACITY_STALE
        if any(
            resource.max_charge_power_w is None or resource.max_charge_power_w <= 0
            for resource in context.resources
        ):
            return BatteryPriorityReasonCode.CAPACITY_RELEASE_CAPACITY_UNKNOWN
        return None

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

    _CAPACITY_RELEASE_CONFIRMATION_SAMPLES = 3
    _CAPACITY_PROBE_CONFIRMATION_SAMPLES = 3
    _CAPACITY_PROBE_CHARGE_THRESHOLD_W = 50.0
    _CAPACITY_PROBE_INJECTION_THRESHOLD_W = -100.0
    _CAPACITY_PROBE_TARGET_GRID_POWER_W = -100.0

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
        self._consecutive_low_charge_samples = 0
        self._battery_priority_active = False
        self._capacity_release_active = False
        self._capacity_release_state = CapacityReleaseState.ZERO_INJECTION
        self._consecutive_saturation_samples = 0
        self._consecutive_probe_samples = 0
        self._consecutive_probe_charge_samples = 0
        self._battery_priority_saturation_tolerance_w = 50.0
        self._activation_count = 0
        self._fallback_count = 0
        self._transition_history: deque[dict[str, Any]] = deque(maxlen=20)
        self._last_runtime_state: str | None = None
        self._last_battery_signature: tuple[object, ...] | None = None
        self._last_capacity_input_signature: tuple[object, ...] | None = None
        self._last_capacity_directional_signature: tuple[object, ...] | None = None
        self._last_capacity_grid_input_signature: tuple[object, ...] | None = None

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
        self._last_capacity_input_signature = None
        self._last_capacity_directional_signature = None
        self._last_capacity_grid_input_signature = None
        self._battery_priority_active = False
        self._capacity_release_active = False
        self._capacity_release_state = CapacityReleaseState.ZERO_INJECTION
        self._consecutive_saturation_samples = 0
        self._consecutive_probe_samples = 0
        self._consecutive_probe_charge_samples = 0
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
            "consecutive_low_charge_samples": self._consecutive_low_charge_samples,
            "confirmation_samples": self._battery_priority_confirmation_samples,
            "charge_threshold_w": self._battery_priority_charge_threshold_w,
            "maintain_charge_threshold_w": (
                BatteryPriorityStrategy._MAINTAIN_CHARGE_THRESHOLD_W
            ),
            "saturation_tolerance_w": self._battery_priority_saturation_tolerance_w,
            "capacity_release_confirmation_samples": (
                self._CAPACITY_RELEASE_CONFIRMATION_SAMPLES
            ),
            "consecutive_saturation_samples": self._consecutive_saturation_samples,
            # Retained for compatibility with existing diagnostics. Capacity
            # Release now exposes the meaningful probe counters below.
            "consecutive_release_samples": 0,
            "capacity_release_state": self._capacity_release_state.value,
            "consecutive_probe_samples": self._consecutive_probe_samples,
            "consecutive_probe_charge_samples": (
                self._consecutive_probe_charge_samples
            ),
            "probe_confirmation_samples": self._CAPACITY_PROBE_CONFIRMATION_SAMPLES,
            "probe_charge_threshold_w": self._CAPACITY_PROBE_CHARGE_THRESHOLD_W,
            "probe_injection_threshold_w": self._CAPACITY_PROBE_INJECTION_THRESHOLD_W,
            "probe_target_grid_power_w": self._CAPACITY_PROBE_TARGET_GRID_POWER_W,
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

    def battery_priority_input_changed(
        self,
        *,
        grid_power_w: float | None = None,
        grid_source_timestamp: datetime | None = None,
    ) -> bool:
        """Tell the controller when a battery transition needs evaluation.

        This is intentionally passive: it only examines the coordinator's
        already-acquired snapshot and does not cause polling or adapter I/O.
        """
        if self._battery_priority_mode not in {
            BatteryPriorityMode.OBSERVED_CONSERVATIVE,
            BatteryPriorityMode.CAPACITY_RELEASE,
        }:
            return False
        context = (
            self._battery_context_provider()
            if self._battery_context_provider is not None
            else None
        )
        if self._battery_priority_mode is BatteryPriorityMode.CAPACITY_RELEASE:
            return (
                self._capacity_input_signature(context)
                != self._last_capacity_input_signature
                or self._capacity_probe_grid_input_changed(
                    grid_power_w, grid_source_timestamp
                )
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
        grid_power_w: float | None = None,
        grid_source_timestamp: datetime | None = None,
    ) -> EnergyStrategyDecision:
        """Return Zero Injection; Battery Priority is comparison-only in Build007."""
        strategy_input = EnergyStrategyInput(
            target_grid_power_w=target_grid_power_w,
            input_snapshot_id=input_snapshot_id,
            decision_timestamp=decision_timestamp or datetime.now(UTC),
            grid_power_w=grid_power_w,
            grid_source_timestamp=grid_source_timestamp,
        )
        decision = self._strategy.decide(strategy_input)
        if activate_battery_priority:
            # The default must remain byte-for-byte equivalent in behaviour to
            # the historical Production path: no alternate target, trace, or
            # fallback state is generated while the feature is disabled.
            if self._battery_priority_mode is BatteryPriorityMode.DISABLED:
                self._last_comparison = None
                return decision
            if self._battery_priority_mode is BatteryPriorityMode.CAPACITY_RELEASE:
                comparison = self._capacity_release_comparison(strategy_input)
                self._last_comparison = comparison
                if comparison.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM:
                    return replace(
                        decision,
                        policy_id="battery_capacity_release",
                        reason=comparison.reason_code.value,
                        confidence=0.8,
                        comparison=comparison,
                        dtu_control_directive=comparison.dtu_control_directive,
                        requested_dtu_limit_percent=100,
                    )
                if comparison.capacity_release_state is CapacityReleaseState.PROBE:
                    return replace(
                        decision,
                        target_grid_power_w=comparison.candidate_target_grid_power_w,
                        policy_id="battery_capacity_release",
                        reason=comparison.reason_code.value,
                        confidence=0.8,
                        comparison=comparison,
                    )
                return replace(decision, comparison=comparison, fallback_used=True)
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

    def _capacity_release_comparison(
        self, strategy_input: EnergyStrategyInput
    ) -> BatteryPriorityComparison:
        context = (
            self._battery_context_provider()
            if self._battery_context_provider is not None
            else None
        )
        # Capacity-release hysteresis deliberately counts *directional-power*
        # publications only.  A SOC refresh, a diagnostic update or a repeated
        # strategy evaluation must not turn one power observation into three
        # confirmations.
        directional_signature = self._directional_battery_signature(context)
        new_sample = (
            directional_signature != self._last_capacity_directional_signature
        )
        self._last_capacity_directional_signature = directional_signature
        grid_input_signature = (
            strategy_input.grid_source_timestamp or strategy_input.input_snapshot_id,
            strategy_input.grid_power_w,
        )
        new_grid_sample = (
            grid_input_signature != self._last_capacity_grid_input_signature
        )
        self._last_capacity_grid_input_signature = grid_input_signature
        self._last_capacity_input_signature = self._capacity_input_signature(context)
        self._update_capacity_release_hysteresis(
            context,
            new_directional_sample=new_sample,
            new_grid_sample=new_grid_sample,
            grid_power_w=strategy_input.grid_power_w,
        )
        comparison = self._battery_priority_strategy.capacity_release(
            strategy_input,
            context,
            release_state=self._capacity_release_state,
            consecutive_saturation_samples=self._consecutive_saturation_samples,
            consecutive_probe_charge_samples=self._consecutive_probe_charge_samples,
            confirmation_samples=self._CAPACITY_RELEASE_CONFIRMATION_SAMPLES,
            saturation_tolerance_w=self._battery_priority_saturation_tolerance_w,
            mode=self._battery_priority_mode,
        )
        self._capacity_release_active = (
            self._capacity_release_state is CapacityReleaseState.RELEASE
        )
        if comparison.fallback_used and comparison.reason_code in {
            BatteryPriorityReasonCode.CAPACITY_RELEASE_FULL,
            BatteryPriorityReasonCode.CAPACITY_RELEASE_SATURATED,
        }:
            self._consecutive_saturation_samples = 0
            self._consecutive_probe_samples = 0
            self._consecutive_probe_charge_samples = 0
        runtime_state = self._capacity_release_state.value
        if runtime_state != self._last_runtime_state:
            if runtime_state == CapacityReleaseState.RELEASE.value:
                self._activation_count += 1
            else:
                self._fallback_count += 1
            self._record_transition(runtime_state, comparison.reason_code.value)
            self._last_runtime_state = runtime_state
        return comparison

    def _capacity_probe_grid_input_changed(
        self,
        grid_power_w: float | None,
        grid_source_timestamp: datetime | None,
    ) -> bool:
        """Request a decision for each fresh persistent-export measurement.

        This only applies while the DTU is fully released and the battery is
        not drawing enough power. It does not read an entity or schedule I/O.
        """
        return (
            self._capacity_release_state is CapacityReleaseState.RELEASE
            and grid_power_w is not None
            and grid_power_w < self._CAPACITY_PROBE_INJECTION_THRESHOLD_W
            and (
                grid_source_timestamp or grid_power_w,
                grid_power_w,
            )
            != self._last_capacity_grid_input_signature
        )

    def _update_capacity_release_hysteresis(
        self,
        context: BatteryPriorityContext | None,
        *,
        new_directional_sample: bool,
        new_grid_sample: bool,
        grid_power_w: float | None,
    ) -> None:
        """Maintain release, probe and saturation states without any I/O."""
        reason = self._battery_priority_strategy._capacity_release_reason(context, -1.0)
        if reason is not None or context is None:
            self._capacity_release_state = CapacityReleaseState.ZERO_INJECTION
            self._consecutive_saturation_samples = 0
            self._consecutive_probe_samples = 0
            self._consecutive_probe_charge_samples = 0
            return
        max_charge = sum(
            resource.max_charge_power_w or 0.0 for resource in context.resources
        )
        charge = sum(resource.charge_power_w or 0.0 for resource in context.resources)
        full = any(
            resource.full is True
            or (resource.soc_percent is not None and resource.soc_percent >= 100)
            for resource in context.resources
        )
        if full:
            self._capacity_release_state = CapacityReleaseState.ZERO_INJECTION
            self._consecutive_saturation_samples = 0
            self._consecutive_probe_samples = 0
            self._consecutive_probe_charge_samples = 0
            return

        saturated = charge >= max_charge - self._battery_priority_saturation_tolerance_w
        directional_power_fresh = all(
            resource.source_freshness.get("directional_power_w") == "fresh"
            for resource in context.resources
        )
        if saturated:
            if new_directional_sample and directional_power_fresh:
                self._consecutive_saturation_samples += 1
            if (
                self._consecutive_saturation_samples
                >= self._CAPACITY_RELEASE_CONFIRMATION_SAMPLES
            ):
                self._capacity_release_state = CapacityReleaseState.ZERO_INJECTION
                self._consecutive_probe_samples = 0
                self._consecutive_probe_charge_samples = 0
            return
        self._consecutive_saturation_samples = 0

        # The 900–950 W hysteresis band keeps a previously selected normal
        # regulation state. Below 900 W one coherent capacity snapshot is
        # sufficient to restore capacity release.
        if (
            self._capacity_release_state is CapacityReleaseState.ZERO_INJECTION
            and charge
            >= max_charge - (2 * self._battery_priority_saturation_tolerance_w)
        ):
            return

        if self._capacity_release_state is CapacityReleaseState.PROBE:
            if charge > self._CAPACITY_PROBE_CHARGE_THRESHOLD_W:
                if new_directional_sample and directional_power_fresh:
                    self._consecutive_probe_charge_samples += 1
                if (
                    self._consecutive_probe_charge_samples
                    >= self._CAPACITY_PROBE_CONFIRMATION_SAMPLES
                ):
                    self._capacity_release_state = CapacityReleaseState.RELEASE
                    self._consecutive_probe_samples = 0
                    self._consecutive_probe_charge_samples = 0
            else:
                self._consecutive_probe_charge_samples = 0
            return

        self._capacity_release_state = CapacityReleaseState.RELEASE
        self._consecutive_probe_charge_samples = 0
        if (
            charge <= self._CAPACITY_PROBE_CHARGE_THRESHOLD_W
            and grid_power_w is not None
            and grid_power_w < self._CAPACITY_PROBE_INJECTION_THRESHOLD_W
        ):
            if new_grid_sample:
                self._consecutive_probe_samples += 1
            if (
                self._consecutive_probe_samples
                >= self._CAPACITY_PROBE_CONFIRMATION_SAMPLES
            ):
                self._capacity_release_state = CapacityReleaseState.PROBE
                self._consecutive_probe_charge_samples = 0
        else:
            self._consecutive_probe_samples = 0

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
            consecutive_low_charge_samples=self._consecutive_low_charge_samples,
            confirmation_samples=self._battery_priority_confirmation_samples,
            charge_threshold_w=self._battery_priority_charge_threshold_w,
            priority_active=self._battery_priority_active,
            mode=self._battery_priority_mode,
        )
        if comparison.fallback_used:
            # A pending activation is an expected intermediate state: retain
            # its fresh-sample count.  Once active, any fallback ends the
            # priority immediately and clears both hysteresis counters.
            if self._battery_priority_active:
                self._battery_priority_active = False
                self._reset_charge_confirmation(comparison.reason_code.value)
        else:
            self._battery_priority_active = True
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
        """Track fresh activation and maintenance samples without I/O."""
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
        elif self._battery_priority_active:
            if charge < BatteryPriorityStrategy._MAINTAIN_CHARGE_THRESHOLD_W:
                if new_sample:
                    self._consecutive_low_charge_samples += 1
            else:
                self._consecutive_low_charge_samples = 0
        elif charge > self._battery_priority_charge_threshold_w:
            if new_sample:
                self._consecutive_charge_samples += 1
        else:
            self._reset_charge_confirmation(
                BatteryPriorityReasonCode.BATTERY_IDLE.value
            )

    def _reset_charge_confirmation(self, reason: str) -> None:
        if self._consecutive_charge_samples or self._consecutive_low_charge_samples:
            self._record_transition("reset", reason)
        self._consecutive_charge_samples = 0
        self._consecutive_low_charge_samples = 0

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
                resource.soc_percent,
                resource.charge_power_w,
                resource.discharge_power_w,
                resource.max_charge_power_w,
                resource.source_freshness.get("soc_percent"),
                resource.source_freshness.get("max_charge_power_w"),
            )
            for resource in context.resources
        )

    @staticmethod
    def _directional_battery_signature(
        context: BatteryPriorityContext | None,
    ) -> tuple[object, ...] | None:
        """Identify one fresh directional-power publication per resource."""
        if context is None:
            return None
        return tuple(
            (
                resource.resource_id,
                resource.source_timestamps.get(
                    "directional_power_w", resource.last_updated
                ),
                resource.source_freshness.get("directional_power_w"),
                resource.charge_power_w,
                resource.discharge_power_w,
            )
            for resource in context.resources
        )

    @staticmethod
    def _capacity_input_signature(
        context: BatteryPriorityContext | None,
    ) -> tuple[object, ...] | None:
        """Identify changes requiring a capacity-policy re-evaluation.

        SOC and capacity freshness can safely force a fallback, but do not
        count as one of the three directional-power confirmations.
        """
        if context is None:
            return None
        return tuple(
            (
                resource.resource_id,
                resource.source_timestamps.get(
                    "directional_power_w", resource.last_updated
                ),
                resource.source_freshness.get("directional_power_w"),
                resource.charge_power_w,
                resource.discharge_power_w,
                resource.soc_percent,
                resource.source_freshness.get("soc_percent"),
                resource.max_charge_power_w,
                resource.source_freshness.get("max_charge_power_w"),
                resource.available,
                resource.health.value,
            )
            for resource in context.resources
        )
