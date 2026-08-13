"""Backward-compatible names for the Build006 energy-strategy boundary.

New code should import :mod:`energy_strategy`. These aliases keep Build004
controller imports and experimental external imports stable.
"""

from .energy_strategy import (
    BatteryPriorityComparison,
    BatteryPriorityContext,
    BatteryPriorityMode,
    BatteryPriorityReasonCode,
    BatteryPriorityStrategy,
    CapacityReleaseState,
    DtuControlDirective,
    EnergyStrategyDecision,
    EnergyStrategyEngine,
    EnergyStrategyInput,
    EnergyStrategyReasonCode,
    ZeroInjectionStrategy,
)

EnergyPolicyDecision = EnergyStrategyDecision
EnergyPolicyEngine = EnergyStrategyEngine
ZeroInjectionPolicy = ZeroInjectionStrategy

__all__ = [
    "BatteryPriorityComparison",
    "BatteryPriorityContext",
    "BatteryPriorityMode",
    "BatteryPriorityReasonCode",
    "BatteryPriorityStrategy",
    "CapacityReleaseState",
    "DtuControlDirective",
    "EnergyPolicyDecision",
    "EnergyPolicyEngine",
    "EnergyStrategyDecision",
    "EnergyStrategyEngine",
    "EnergyStrategyInput",
    "EnergyStrategyReasonCode",
    "ZeroInjectionPolicy",
    "ZeroInjectionStrategy",
]
