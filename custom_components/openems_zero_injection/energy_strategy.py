"""Pure, manufacturer-neutral energy-strategy contracts.

Build006 deliberately keeps this boundary side-effect free. It selects an
energy target only; the predictive controller and safety scheduler retain
exclusive responsibility for translating that target into a DTU command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class EnergyStrategyReasonCode(StrEnum):
    """Stable, serialisable explanations emitted by energy strategies."""

    CONFIGURED_ZERO_INJECTION_TARGET = "configured_zero_injection_target"


@dataclass(frozen=True, slots=True)
class EnergyStrategyInput:
    """Immutable, Home-Assistant-independent input available before a decision."""

    target_grid_power_w: float
    input_snapshot_id: str
    decision_timestamp: datetime


@dataclass(frozen=True, slots=True)
class EnergyStrategyDecision:
    """The target contract consumed by the predictive controller.

    ``reason`` remains the legacy human-readable value during Build006 so
    existing controller status and trace output stay compatible. New consumers
    must use the stable ``reason_code`` instead.
    """

    target_grid_power_w: float
    policy_id: str
    reason: str
    confidence: float
    fallback_used: bool
    decision_timestamp: datetime
    input_snapshot_id: str
    reason_code: EnergyStrategyReasonCode


class ZeroInjectionStrategy:
    """Build006 baseline strategy: return the configured target unchanged."""

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


class EnergyStrategyEngine:
    """Select a pure target using the active Build006 strategy.

    BatteryPriorityStrategy is intentionally absent from this build. Optional
    metadata lets later callers use a replayable snapshot without changing the
    controller's established ``decide(float)`` call.
    """

    def __init__(self, strategy: ZeroInjectionStrategy | None = None) -> None:
        self._strategy = strategy or ZeroInjectionStrategy()

    def decide(
        self,
        target_grid_power_w: float,
        *,
        input_snapshot_id: str = "configured_target",
        decision_timestamp: datetime | None = None,
    ) -> EnergyStrategyDecision:
        """Return the exact configured target under ZeroInjectionStrategy."""
        return self._strategy.decide(
            EnergyStrategyInput(
                target_grid_power_w=target_grid_power_w,
                input_snapshot_id=input_snapshot_id,
                decision_timestamp=decision_timestamp or datetime.now(UTC),
            )
        )
