"""Single-command safety scheduler for automatic temporary DTU writes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from .const import ControllerMode, SchedulerState


class SafetyScheduler:
    """Serialize automatic writes and enforce a stabilization delay."""

    def __init__(self, stabilization_delay_seconds: int) -> None:
        self._delay_seconds = stabilization_delay_seconds
        self._state = SchedulerState.IDLE
        self._next_allowed_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def state(self) -> SchedulerState:
        return self._state

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def configure(self, stabilization_delay_seconds: int) -> None:
        self._delay_seconds = stabilization_delay_seconds

    def remaining_seconds(self, now: datetime | None = None) -> int:
        if self._next_allowed_at is None:
            return 0
        remaining = (self._next_allowed_at - (now or datetime.now(UTC))).total_seconds()
        return max(0, int(remaining + 0.999))

    def pause(self) -> None:
        """Prevent automatic commands without sending a DTU frame."""
        if not self._lock.locked():
            self._state = SchedulerState.PAUSED

    def reset(self) -> None:
        """Manually re-arm the scheduler after an error or pause."""
        if not self._lock.locked():
            self._state = SchedulerState.IDLE
            self._last_error = None

    def command_block_reason(self) -> str | None:
        """Return a non-error reason when a new command must not start yet."""
        if self._state in {SchedulerState.PAUSED, SchedulerState.ERROR}:
            return "Scheduler is paused"
        if self._lock.locked():
            self._state = SchedulerState.WAITING
            return "Command already in progress"
        if self.remaining_seconds() > 0:
            self._state = SchedulerState.WAITING
            return "Waiting for stabilization"
        return None

    async def async_execute(
        self,
        mode: ControllerMode,
        command: Callable[[], Awaitable[None]],
    ) -> tuple[bool, str]:
        """Execute exactly one verified command only when safe and permitted."""
        if mode is ControllerMode.DISABLED:
            self._state = SchedulerState.PAUSED
            return False, "Disabled"
        if mode is ControllerMode.SIMULATION:
            return False, "Simulation mode"
        if reason := self.command_block_reason():
            return False, reason

        async with self._lock:
            self._state = SchedulerState.WRITING
            try:
                await command()
            except Exception as err:  # converted to an explicit controller error
                self._state = SchedulerState.ERROR
                self._last_error = str(err)
                return False, f"Command failed: {err}"
            self._state = SchedulerState.VERIFYING
            self._next_allowed_at = datetime.now(UTC) + timedelta(
                seconds=self._delay_seconds
            )
            self._state = SchedulerState.WAITING
            self._last_error = None
            return True, "Command confirmed"
