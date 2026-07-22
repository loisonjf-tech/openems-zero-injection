"""Passive calibration contracts; Build004 RC2 never changes control from them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CalibrationConfidence(StrEnum):
    """Confidence is diagnostic-only until a future explicit opt-in."""

    NONE = "none"
    INSUFFICIENT = "insufficient"
    OBSERVING = "observing"


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    """One observation retained without influencing a controller decision."""

    timestamp: datetime
    response_time_seconds: float | None
    obtained_power_w: float | None
    residual_error_w: float | None
    quality: float


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    """Read-only profile published for diagnostics in this build."""

    confidence: CalibrationConfidence = CalibrationConfidence.NONE
    accepted_samples: int = 0
    rejected_samples: int = 0
    mean_response_time_seconds: float | None = None
    mean_residual_error_w: float | None = None


class CalibrationManager:
    """Passive observer. It does not persist, calibrate, or command in RC2."""

    def __init__(self) -> None:
        self._profile = CalibrationProfile()

    @property
    def profile(self) -> CalibrationProfile:
        """Return the diagnostic-only profile."""
        return self._profile

    def observe(self, _sample: CalibrationSample) -> None:
        """Accept the future API without changing any operational behavior."""
