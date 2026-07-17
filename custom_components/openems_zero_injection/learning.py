"""Passive learning data collector; it never changes controller parameters."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class LearningSample:
    timestamp: datetime
    old_limit: int
    new_limit: int
    grid_before: float | None
    grid_after: float | None
    dtu_power_before: float | None
    dtu_power_after: float | None
    configured_wait_time: int
    observed_change: float | None
    estimated_watts_per_percent: float


class PassiveLearningEngine:
    """Record confirmed commands only; no adaptive behavior in Build004."""

    def __init__(self, maxlen: int = 200) -> None:
        self._samples: deque[LearningSample] = deque(maxlen=maxlen)

    def record(self, sample: LearningSample) -> None:
        self._samples.append(sample)

    def diagnostics(self, count: int = 20) -> list[dict[str, Any]]:
        return [asdict(sample) for sample in list(self._samples)[-count:]]
