"""Manufacturer-neutral, side-effect-free energy policy contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnergyPolicyDecision:
    """The only target contract consumed by the predictive controller."""

    target_grid_power_w: float
    policy_id: str
    reason: str
    confidence: float
    fallback_used: bool


class ZeroInjectionPolicy:
    """V1-compatible policy: pass through the configured grid target exactly."""

    policy_id = "zero_injection"

    def decide(self, target_grid_power_w: float) -> EnergyPolicyDecision:
        """Return a deterministic target without I/O or battery knowledge."""
        return EnergyPolicyDecision(
            target_grid_power_w=target_grid_power_w,
            policy_id=self.policy_id,
            reason="Configured zero-injection target",
            confidence=1.0,
            fallback_used=False,
        )


class EnergyPolicyEngine:
    """Build004 RC2 policy boundary with only the V1-compatible policy active."""

    def __init__(self, policy: ZeroInjectionPolicy | None = None) -> None:
        self._policy = policy or ZeroInjectionPolicy()

    def decide(self, target_grid_power_w: float) -> EnergyPolicyDecision:
        """Produce the target that the controller receives, without side effects."""
        return self._policy.decide(target_grid_power_w)
