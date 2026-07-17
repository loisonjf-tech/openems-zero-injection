"""Bounded in-memory controller decision history."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One structured, non-sensitive controller decision."""

    timestamp: datetime
    controller_mode: str
    grid_power_w: float | None
    target_grid_power_w: float
    deadband_w: float
    current_limit_percent: int | None
    calculated_limit_percent: int | None
    applied_limit_percent: int | None
    watts_per_percent: float
    scheduler_state: str
    decision_reason: str
    command_sent: bool
    command_confirmed: bool
    error_message: str | None

    def as_dict(self) -> dict[str, Any]:
        """Return diagnostics-safe structured data."""
        return asdict(self)


class DecisionHistory:
    """Keep only the latest decisions to avoid unbounded memory growth."""

    def __init__(self, maxlen: int = 200) -> None:
        self._records: deque[DecisionRecord] = deque(maxlen=maxlen)

    def append(self, record: DecisionRecord) -> None:
        self._records.append(record)

    @property
    def count(self) -> int:
        return len(self._records)

    @property
    def latest(self) -> DecisionRecord | None:
        return self._records[-1] if self._records else None

    def latest_records(self, count: int = 20) -> list[dict[str, Any]]:
        return [record.as_dict() for record in list(self._records)[-count:]]
