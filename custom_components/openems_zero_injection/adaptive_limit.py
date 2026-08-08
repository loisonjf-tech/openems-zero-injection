"""Passive, explainable observations of the DTU limit-to-power response.

This module deliberately has no dependency on Home Assistant, Modbus, the
scheduler or the controller command path.  Its output is diagnostic-only in
this increment: callers must continue to use the nominal gain for control.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median
from typing import Any


class AdaptiveLimitConfidence(StrEnum):
    """Stable confidence codes for diagnostics, history and future replay."""

    NONE = "none"
    INSUFFICIENT = "insufficient"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AdaptiveObservationRejection(StrEnum):
    """Stable reasons why an observation cannot safely teach the model."""

    COMMAND_TOO_SMALL = "command_too_small"
    INSUFFICIENT_PRE_COMMAND_CONTEXT = "insufficient_pre_command_context"
    PRE_COMMAND_MEASUREMENTS_UNSTABLE = "pre_command_measurements_unstable"
    POST_STABILIZATION_TIMEOUT = "post_stabilization_timeout"
    BATTERY_CONTEXT_CHANGED = "battery_context_changed"
    POST_POWER_UNSTABLE = "post_power_unstable"
    POWER_CHANGE_TOO_SMALL = "power_change_too_small"
    POWER_CHANGE_WRONG_DIRECTION = "power_change_wrong_direction"
    GAIN_OUTSIDE_CONSERVATIVE_BOUNDS = "gain_outside_conservative_bounds"


class AdaptivePredictionNonComparableReason(StrEnum):
    """Why a resolved command cannot fairly compare the two predictors."""

    ADAPTIVE_CONFIDENCE_INSUFFICIENT = "adaptive_confidence_insufficient"
    OBSERVATION_INDETERMINATE = "observation_indeterminate"


@dataclass(frozen=True, slots=True)
class AdaptiveObservation:
    """One resolved command-effect observation, accepted or indeterminate."""

    timestamp: datetime
    limit_before_percent: int
    limit_after_percent: int
    power_before_w: float
    power_after_w: float | None
    gain_observed_w_per_percent: float | None
    accepted: bool
    rejection_reason: AdaptiveObservationRejection | None = None
    limit_range: str | None = None
    nominal_gain_w_per_percent: float | None = None
    adaptive_gain_before_observation_w_per_percent: float | None = None
    confidence_before_observation: AdaptiveLimitConfidence = (
        AdaptiveLimitConfidence.NONE
    )
    predicted_nominal_power_change_w: float | None = None
    predicted_adaptive_power_change_w: float | None = None
    observed_power_change_w: float | None = None
    nominal_error_w: float | None = None
    adaptive_error_w: float | None = None
    nominal_signed_error_w: float | None = None
    adaptive_signed_error_w: float | None = None
    prediction_comparable: bool = False
    prediction_non_comparable_reason: (
        AdaptivePredictionNonComparableReason | None
    ) = None
    adaptive_model_better: bool | None = None


@dataclass(frozen=True, slots=True)
class AdaptivePredictionComparison:
    """One fair, out-of-sample comparison retained for aggregate metrics."""

    timestamp: datetime
    limit_range: str
    nominal_error_w: float
    adaptive_error_w: float
    nominal_signed_error_w: float
    adaptive_signed_error_w: float
    adaptive_model_better: bool


@dataclass(slots=True)
class _PendingObservation:
    """A confirmed command awaiting stable post-command measurements."""

    timestamp: datetime
    limit_before_percent: int
    limit_after_percent: int
    power_before_w: float
    battery_signature: tuple[object, ...]
    limit_range: str
    nominal_gain_w_per_percent: float
    adaptive_gain_before_observation_w_per_percent: float | None
    confidence_before_observation: AdaptiveLimitConfidence
    predicted_nominal_power_change_w: float
    predicted_adaptive_power_change_w: float | None
    post_samples: list[tuple[datetime, float]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AdaptiveLimitProfile:
    """A robust local gain estimate for one configured percentage range."""

    limit_range: str
    lower_percent: int
    upper_percent: int
    estimated_gain_w_per_percent: float | None
    dispersion_w_per_percent: float | None
    accepted_observations: int
    rejected_observations: int
    last_observation_at: datetime | None
    age_seconds: float | None
    confidence: AdaptiveLimitConfidence


@dataclass(frozen=True, slots=True)
class AdaptiveLimitCandidate:
    """Diagnostic-only candidate; it is never a controller command here."""

    limit_candidate_percent: int | None
    gain_estimated_w_per_percent: float | None
    limit_range: str
    confidence: AdaptiveLimitConfidence


class AdaptiveLimitModel:
    """Build passive profiles from only high-quality confirmed commands."""

    _RANGES: tuple[tuple[str, int, int], ...] = (
        ("2-10", 2, 10),
        ("11-25", 11, 25),
        ("26-50", 26, 50),
        ("51-75", 51, 75),
        ("76-100", 76, 100),
    )
    _MIN_LIMIT_CHANGE_PERCENT = 2
    _POST_SAMPLE_COUNT = 2
    _POST_SAMPLE_MIN_INTERVAL_SECONDS = 5
    _OBSERVATION_TIMEOUT_SECONDS = 90
    _BASELINE_MAX_AGE_SECONDS = 45
    _MIN_POWER_CHANGE_W = 20.0

    def __init__(self, *, nominal_gain_w_per_percent: float) -> None:
        if nominal_gain_w_per_percent <= 0:
            raise ValueError("nominal_gain_w_per_percent must be positive")
        self._nominal_gain = nominal_gain_w_per_percent
        self._pending: _PendingObservation | None = None
        self._recent_baselines: deque[
            tuple[datetime, float, float, tuple[object, ...]]
        ] = deque(maxlen=3)
        self._samples: dict[str, deque[tuple[datetime, float]]] = {
            label: deque(maxlen=100) for label, _, _ in self._RANGES
        }
        self._comparisons: dict[str, deque[AdaptivePredictionComparison]] = {
            label: deque(maxlen=100) for label, _, _ in self._RANGES
        }
        self._rejected: dict[str, int] = {label: 0 for label, _, _ in self._RANGES}
        self._accepted_total = 0
        self._rejected_total = 0
        self._last_observation: AdaptiveObservation | None = None

    @property
    def last_observation(self) -> AdaptiveObservation | None:
        """Return the most recently accepted or rejected resolved observation."""
        return self._last_observation

    def register_confirmed_command(
        self,
        *,
        timestamp: datetime,
        limit_before_percent: int,
        limit_after_percent: int,
        power_before_w: float | None,
        battery_signature: tuple[object, ...],
    ) -> None:
        """Begin observing one ordinary automatic command after confirmation."""
        if power_before_w is None:
            return
        limit_range = self.limit_range_for(limit_after_percent)
        profile = self.profile_for(limit_after_percent, now=timestamp)
        delta_limit = limit_after_percent - limit_before_percent
        adaptive_gain = (
            profile.estimated_gain_w_per_percent
            if profile.confidence
            in {
                AdaptiveLimitConfidence.LOW,
                AdaptiveLimitConfidence.MEDIUM,
                AdaptiveLimitConfidence.HIGH,
            }
            else None
        )
        pending = _PendingObservation(
            timestamp=timestamp,
            limit_before_percent=limit_before_percent,
            limit_after_percent=limit_after_percent,
            power_before_w=power_before_w,
            battery_signature=battery_signature,
            limit_range=limit_range,
            nominal_gain_w_per_percent=self._nominal_gain,
            adaptive_gain_before_observation_w_per_percent=adaptive_gain,
            confidence_before_observation=profile.confidence,
            predicted_nominal_power_change_w=delta_limit * self._nominal_gain,
            predicted_adaptive_power_change_w=(
                delta_limit * adaptive_gain if adaptive_gain is not None else None
            ),
        )
        if (
            abs(limit_after_percent - limit_before_percent)
            < self._MIN_LIMIT_CHANGE_PERCENT
        ):
            self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.COMMAND_TOO_SMALL,
            )
            return
        baselines = [
            entry
            for entry in self._recent_baselines
            if (timestamp - entry[0]).total_seconds() <= self._BASELINE_MAX_AGE_SECONDS
        ]
        if len(baselines) < 2:
            self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.INSUFFICIENT_PRE_COMMAND_CONTEXT,
            )
            return
        baseline_powers = [entry[1] for entry in baselines]
        baseline_grid_powers = [entry[2] for entry in baselines]
        baseline_signatures = [entry[3] for entry in baselines]
        median_pv = float(median(baseline_powers))
        median_grid = float(median(baseline_grid_powers))
        if (
            any(signature != battery_signature for signature in baseline_signatures)
            or max(baseline_powers) - min(baseline_powers)
            > max(75.0, abs(median_pv) * 0.10)
            or max(baseline_grid_powers) - min(baseline_grid_powers)
            > max(30.0, abs(median_grid) * 0.10)
        ):
            self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.PRE_COMMAND_MEASUREMENTS_UNSTABLE,
            )
            return
        self._pending = pending

    def record_baseline(
        self,
        *,
        timestamp: datetime,
        power_w: float | None,
        grid_power_w: float,
        battery_signature: tuple[object, ...],
    ) -> None:
        """Retain existing stable-context evidence before a future command."""
        if self._pending is not None or power_w is None:
            return
        self._recent_baselines.append(
            (timestamp, power_w, grid_power_w, battery_signature)
        )

    def observe(
        self,
        *,
        timestamp: datetime,
        power_w: float | None,
        scheduler_stabilizing: bool,
        battery_signature: tuple[object, ...],
    ) -> AdaptiveObservation | None:
        """Resolve a pending observation only after stable post-command data."""
        pending = self._pending
        if pending is None:
            return None
        if (
            timestamp - pending.timestamp
        ).total_seconds() > self._OBSERVATION_TIMEOUT_SECONDS:
            self._pending = None
            self._recent_baselines.clear()
            return self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.POST_STABILIZATION_TIMEOUT,
                timestamp=timestamp,
            )
        if scheduler_stabilizing or power_w is None:
            return None
        if battery_signature != pending.battery_signature:
            self._pending = None
            self._recent_baselines.clear()
            return self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.BATTERY_CONTEXT_CHANGED,
                timestamp=timestamp,
            )
        if pending.post_samples and (
            timestamp - pending.post_samples[-1][0]
        ).total_seconds() < self._POST_SAMPLE_MIN_INTERVAL_SECONDS:
            return None
        pending.post_samples.append((timestamp, power_w))
        if len(pending.post_samples) < self._POST_SAMPLE_COUNT:
            return None
        self._pending = None
        self._recent_baselines.clear()
        post_powers = [sample[1] for sample in pending.post_samples]
        post_power = float(median(post_powers))
        allowed_spread = max(75.0, abs(post_power) * 0.10)
        if max(post_powers) - min(post_powers) > allowed_spread:
            return self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.POST_POWER_UNSTABLE,
                timestamp=timestamp,
                power_after_w=post_power,
            )
        delta_limit = pending.limit_after_percent - pending.limit_before_percent
        delta_power = post_power - pending.power_before_w
        if abs(delta_power) < self._MIN_POWER_CHANGE_W:
            return self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.POWER_CHANGE_TOO_SMALL,
                timestamp=timestamp,
                power_after_w=post_power,
            )
        if delta_power * delta_limit <= 0:
            return self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.POWER_CHANGE_WRONG_DIRECTION,
                timestamp=timestamp,
                power_after_w=post_power,
            )
        gain = abs(delta_power / delta_limit)
        # Bounds are proportional to the configured nominal reference, rather
        # than assuming undocumented DTU register semantics are linear.
        if not self._nominal_gain / 6 <= gain <= self._nominal_gain * 4:
            return self._resolve_pending_rejection(
                pending,
                reason=AdaptiveObservationRejection.GAIN_OUTSIDE_CONSERVATIVE_BOUNDS,
                timestamp=timestamp,
                power_after_w=post_power,
            )
        observed_power_change = delta_power
        nominal_signed_error = (
            pending.predicted_nominal_power_change_w - observed_power_change
        )
        adaptive_signed_error = (
            pending.predicted_adaptive_power_change_w - observed_power_change
            if pending.predicted_adaptive_power_change_w is not None
            else None
        )
        prediction_comparable = adaptive_signed_error is not None
        non_comparable_reason = (
            None
            if prediction_comparable
            else (
                AdaptivePredictionNonComparableReason
                .ADAPTIVE_CONFIDENCE_INSUFFICIENT
            )
        )
        if prediction_comparable:
            nominal_error = abs(nominal_signed_error)
            adaptive_error = abs(adaptive_signed_error)
            self._comparisons[pending.limit_range].append(
                AdaptivePredictionComparison(
                    timestamp=timestamp,
                    limit_range=pending.limit_range,
                    nominal_error_w=nominal_error,
                    adaptive_error_w=adaptive_error,
                    nominal_signed_error_w=nominal_signed_error,
                    adaptive_signed_error_w=adaptive_signed_error,
                    adaptive_model_better=adaptive_error < nominal_error,
                )
            )
        self._samples[pending.limit_range].append((timestamp, gain))
        self._accepted_total += 1
        observation = AdaptiveObservation(
            timestamp=timestamp,
            limit_before_percent=pending.limit_before_percent,
            limit_after_percent=pending.limit_after_percent,
            power_before_w=pending.power_before_w,
            power_after_w=post_power,
            gain_observed_w_per_percent=gain,
            accepted=True,
            limit_range=pending.limit_range,
            nominal_gain_w_per_percent=pending.nominal_gain_w_per_percent,
            adaptive_gain_before_observation_w_per_percent=(
                pending.adaptive_gain_before_observation_w_per_percent
            ),
            confidence_before_observation=pending.confidence_before_observation,
            predicted_nominal_power_change_w=(
                pending.predicted_nominal_power_change_w
            ),
            predicted_adaptive_power_change_w=(
                pending.predicted_adaptive_power_change_w
            ),
            observed_power_change_w=observed_power_change,
            nominal_error_w=abs(nominal_signed_error),
            adaptive_error_w=(
                abs(adaptive_signed_error)
                if adaptive_signed_error is not None
                else None
            ),
            nominal_signed_error_w=nominal_signed_error,
            adaptive_signed_error_w=adaptive_signed_error,
            prediction_comparable=prediction_comparable,
            prediction_non_comparable_reason=non_comparable_reason,
            adaptive_model_better=(
                abs(adaptive_signed_error) < abs(nominal_signed_error)
                if adaptive_signed_error is not None
                else None
            ),
        )
        self._last_observation = observation
        return observation

    def candidate_for(
        self, *, current_limit_percent: int, grid_error_w: float
    ) -> AdaptiveLimitCandidate:
        """Calculate a comparison candidate, never an operational command."""
        profile = self.profile_for(current_limit_percent)
        if profile.confidence not in {
            AdaptiveLimitConfidence.LOW,
            AdaptiveLimitConfidence.MEDIUM,
            AdaptiveLimitConfidence.HIGH,
        } or profile.estimated_gain_w_per_percent is None:
            return AdaptiveLimitCandidate(
                limit_candidate_percent=None,
                gain_estimated_w_per_percent=None,
                limit_range=profile.limit_range,
                confidence=profile.confidence,
            )
        gain = profile.estimated_gain_w_per_percent
        adjustment = _round_away_from_zero(grid_error_w / gain)
        return AdaptiveLimitCandidate(
            limit_candidate_percent=max(
                2, min(100, current_limit_percent + adjustment)
            ),
            gain_estimated_w_per_percent=gain,
            limit_range=profile.limit_range,
            confidence=profile.confidence,
        )

    def profile_for(
        self, limit_percent: int, *, now: datetime | None = None
    ) -> AdaptiveLimitProfile:
        """Return one serialisable profile, falling back to nominal when empty."""
        label = self.limit_range_for(limit_percent)
        lower, upper = next(
            (low, high) for name, low, high in self._RANGES if name == label
        )
        values = [gain for _, gain in self._samples[label]]
        last = self._samples[label][-1][0] if self._samples[label] else None
        current = now or datetime.now(UTC)
        age = max(0.0, (current - last).total_seconds()) if last else None
        estimate = float(median(values)) if values else None
        dispersion = (
            float(median([abs(value - estimate) for value in values]))
            if estimate is not None and values
            else None
        )
        return AdaptiveLimitProfile(
            limit_range=label,
            lower_percent=lower,
            upper_percent=upper,
            estimated_gain_w_per_percent=estimate,
            dispersion_w_per_percent=dispersion,
            accepted_observations=len(values),
            rejected_observations=self._rejected[label],
            last_observation_at=last,
            age_seconds=age,
            confidence=_confidence(len(values), estimate, dispersion),
        )

    def diagnostics(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return primitive, passive state suitable for Home Assistant diagnostics."""
        current = now or datetime.now(UTC)
        return {
            "mode": "passive",
            "gain_nominal_w_per_percent": self._nominal_gain,
            "gain_used_w_per_percent": self._nominal_gain,
            "accepted_observations": self._accepted_total,
            "rejected_observations": self._rejected_total,
            "pending_observation": self._pending is not None,
            "last_observation": _observation_dict(self._last_observation),
            "prediction_metrics": self.prediction_metrics(),
            "profiles": [
                {
                    **_profile_dict(self.profile_for(lower, now=current)),
                    "prediction_metrics": self.prediction_metrics(label),
                }
                for label, lower, _ in self._RANGES
            ],
        }

    def prediction_metrics(self, limit_range: str | None = None) -> dict[str, Any]:
        """Return aggregate out-of-sample comparison metrics, never control data."""
        comparisons = (
            list(self._comparisons[limit_range])
            if limit_range is not None
            else [
                comparison
                for values in self._comparisons.values()
                for comparison in values
            ]
        )
        if not comparisons:
            return {
                "comparable_predictions": 0,
                "nominal_mean_absolute_error_w": None,
                "nominal_median_absolute_error_w": None,
                "adaptive_mean_absolute_error_w": None,
                "adaptive_median_absolute_error_w": None,
                "nominal_mean_signed_error_w": None,
                "adaptive_mean_signed_error_w": None,
                "adaptive_better_percent": None,
            }
        nominal_errors = [comparison.nominal_error_w for comparison in comparisons]
        adaptive_errors = [comparison.adaptive_error_w for comparison in comparisons]
        nominal_signed = [
            comparison.nominal_signed_error_w for comparison in comparisons
        ]
        adaptive_signed = [
            comparison.adaptive_signed_error_w for comparison in comparisons
        ]
        return {
            "comparable_predictions": len(comparisons),
            "nominal_mean_absolute_error_w": sum(nominal_errors) / len(comparisons),
            "nominal_median_absolute_error_w": float(median(nominal_errors)),
            "adaptive_mean_absolute_error_w": sum(adaptive_errors)
            / len(comparisons),
            "adaptive_median_absolute_error_w": float(median(adaptive_errors)),
            "nominal_mean_signed_error_w": sum(nominal_signed) / len(comparisons),
            "adaptive_mean_signed_error_w": sum(adaptive_signed)
            / len(comparisons),
            "adaptive_better_percent": 100
            * sum(
                comparison.adaptive_model_better for comparison in comparisons
            )
            / len(comparisons),
        }

    def reset(self, *, nominal_gain_w_per_percent: float) -> None:
        """Discard incomparable observations after nominal-power reconfiguration."""
        if nominal_gain_w_per_percent <= 0:
            raise ValueError("nominal_gain_w_per_percent must be positive")
        self._nominal_gain = nominal_gain_w_per_percent
        self._pending = None
        self._recent_baselines.clear()
        for samples in self._samples.values():
            samples.clear()
        for comparisons in self._comparisons.values():
            comparisons.clear()
        self._rejected = {label: 0 for label, _, _ in self._RANGES}
        self._accepted_total = 0
        self._rejected_total = 0
        self._last_observation = None

    @classmethod
    def limit_range_for(cls, limit_percent: int) -> str:
        """Return the stable configured range containing a valid DTU limit."""
        for label, lower, upper in cls._RANGES:
            if lower <= limit_percent <= upper:
                return label
        raise ValueError("limit percent must be within 2..100")

    def _resolve_pending_rejection(
        self,
        pending: _PendingObservation,
        *,
        reason: AdaptiveObservationRejection,
        timestamp: datetime | None = None,
        power_after_w: float | None = None,
    ) -> AdaptiveObservation:
        """Record an indeterminate result without inventing a zero response."""
        return self._resolve_rejection(
            timestamp=timestamp or pending.timestamp,
            limit_before_percent=pending.limit_before_percent,
            limit_after_percent=pending.limit_after_percent,
            power_before_w=pending.power_before_w,
            reason=reason,
            power_after_w=power_after_w,
            nominal_gain_w_per_percent=pending.nominal_gain_w_per_percent,
            adaptive_gain_before_observation_w_per_percent=(
                pending.adaptive_gain_before_observation_w_per_percent
            ),
            confidence_before_observation=pending.confidence_before_observation,
            predicted_nominal_power_change_w=(
                pending.predicted_nominal_power_change_w
            ),
            predicted_adaptive_power_change_w=(
                pending.predicted_adaptive_power_change_w
            ),
            limit_range=pending.limit_range,
        )

    def _resolve_rejection(
        self,
        *,
        timestamp: datetime,
        limit_before_percent: int,
        limit_after_percent: int,
        power_before_w: float,
        reason: AdaptiveObservationRejection,
        power_after_w: float | None = None,
        nominal_gain_w_per_percent: float | None = None,
        adaptive_gain_before_observation_w_per_percent: float | None = None,
        confidence_before_observation: AdaptiveLimitConfidence = (
            AdaptiveLimitConfidence.NONE
        ),
        predicted_nominal_power_change_w: float | None = None,
        predicted_adaptive_power_change_w: float | None = None,
        limit_range: str | None = None,
    ) -> AdaptiveObservation:
        limit_range = limit_range or self.limit_range_for(
            max(2, min(100, limit_after_percent))
        )
        self._rejected[limit_range] += 1
        self._rejected_total += 1
        observation = AdaptiveObservation(
            timestamp=timestamp,
            limit_before_percent=limit_before_percent,
            limit_after_percent=limit_after_percent,
            power_before_w=power_before_w,
            power_after_w=power_after_w,
            gain_observed_w_per_percent=None,
            accepted=False,
            rejection_reason=reason,
            limit_range=limit_range,
            nominal_gain_w_per_percent=nominal_gain_w_per_percent,
            adaptive_gain_before_observation_w_per_percent=(
                adaptive_gain_before_observation_w_per_percent
            ),
            confidence_before_observation=confidence_before_observation,
            predicted_nominal_power_change_w=predicted_nominal_power_change_w,
            predicted_adaptive_power_change_w=(
                predicted_adaptive_power_change_w
            ),
            prediction_non_comparable_reason=(
                AdaptivePredictionNonComparableReason.OBSERVATION_INDETERMINATE
            ),
        )
        self._last_observation = observation
        return observation


def _confidence(
    count: int, estimate: float | None, dispersion: float | None
) -> AdaptiveLimitConfidence:
    """Derive a conservative confidence from sample count and robust dispersion."""
    if count == 0:
        return AdaptiveLimitConfidence.NONE
    if count < 3 or estimate is None or dispersion is None:
        return AdaptiveLimitConfidence.INSUFFICIENT
    if dispersion > max(10.0, estimate * 0.30):
        return AdaptiveLimitConfidence.INSUFFICIENT
    if count >= 15:
        return AdaptiveLimitConfidence.HIGH
    if count >= 8:
        return AdaptiveLimitConfidence.MEDIUM
    return AdaptiveLimitConfidence.LOW


def _round_away_from_zero(value: float) -> int:
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def _observation_dict(observation: AdaptiveObservation | None) -> dict[str, Any] | None:
    if observation is None:
        return None
    return {
        "timestamp": observation.timestamp.isoformat(),
        "limit_before_percent": observation.limit_before_percent,
        "limit_after_percent": observation.limit_after_percent,
        "power_before_w": observation.power_before_w,
        "power_after_w": observation.power_after_w,
        "gain_observed_w_per_percent": observation.gain_observed_w_per_percent,
        "nominal_gain_w_per_percent": observation.nominal_gain_w_per_percent,
        "adaptive_gain_before_observation_w_per_percent": (
            observation.adaptive_gain_before_observation_w_per_percent
        ),
        "confidence_before_observation": (
            observation.confidence_before_observation.value
        ),
        "predicted_nominal_power_change_w": (
            observation.predicted_nominal_power_change_w
        ),
        "predicted_adaptive_power_change_w": (
            observation.predicted_adaptive_power_change_w
        ),
        "observed_power_change_w": observation.observed_power_change_w,
        "nominal_error_w": observation.nominal_error_w,
        "adaptive_error_w": observation.adaptive_error_w,
        "nominal_signed_error_w": observation.nominal_signed_error_w,
        "adaptive_signed_error_w": observation.adaptive_signed_error_w,
        "prediction_comparable": observation.prediction_comparable,
        "prediction_non_comparable_reason": (
            observation.prediction_non_comparable_reason.value
            if observation.prediction_non_comparable_reason
            else None
        ),
        "adaptive_model_better": observation.adaptive_model_better,
        "accepted": observation.accepted,
        "rejection_reason": (
            observation.rejection_reason.value if observation.rejection_reason else None
        ),
        "limit_range": observation.limit_range,
    }


def _profile_dict(profile: AdaptiveLimitProfile) -> dict[str, Any]:
    return {
        "limit_range": profile.limit_range,
        "lower_percent": profile.lower_percent,
        "upper_percent": profile.upper_percent,
        "estimated_gain_w_per_percent": profile.estimated_gain_w_per_percent,
        "dispersion_w_per_percent": profile.dispersion_w_per_percent,
        "accepted_observations": profile.accepted_observations,
        "rejected_observations": profile.rejected_observations,
        "last_observation_at": (
            profile.last_observation_at.isoformat()
            if profile.last_observation_at
            else None
        ),
        "age_seconds": profile.age_seconds,
        "confidence": profile.confidence.value,
    }
