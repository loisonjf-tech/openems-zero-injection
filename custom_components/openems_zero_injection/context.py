"""Passive Context Analyzer contracts for a future Build005 implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContextKind(StrEnum):
    """Context categories deliberately kept descriptive, not certain."""

    UNKNOWN = "unknown"
    STABLE = "stable"
    MEASUREMENTS_UNSTABLE = "measurements_unstable"
    CONSUMPTION_STEP_LIKELY = "consumption_step_likely"
    IRRADIANCE_CHANGE_LIKELY = "irradiance_change_likely"
    BATTERY_RAMP_LIKELY = "battery_ramp_likely"


@dataclass(frozen=True, slots=True)
class ContextClassification:
    """Passive context result; it has no command authority."""

    kind: ContextKind = ContextKind.UNKNOWN
    confidence: float = 0.0
    reason: str = "Context analysis is not implemented"


class ContextAnalyzer:
    """Build004 RC2 placeholder exposing only stable diagnostics contracts."""

    def classify(self) -> ContextClassification:
        """Return the explicit passive placeholder result."""
        return ContextClassification()
