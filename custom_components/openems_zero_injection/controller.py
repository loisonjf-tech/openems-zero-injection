"""Build004 controller orchestration with no battery-specific behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .acquisition import AcquisitionEngine
from .const import (
    CONTROLLER_INTERVAL,
    DEFAULT_DEADBAND_W,
    DEFAULT_MAXIMUM_STEP_PERCENT,
    DEFAULT_STABILIZATION_DELAY_SECONDS,
    DEFAULT_TARGET_GRID_POWER_W,
    DEFAULT_WATTS_PER_PERCENT,
    ControllerMode,
    SchedulerState,
    VALID_GRID_MEASUREMENTS_REQUIRED,
)
from .decision import ControlDecision, calculate_power_limit
from .history import DecisionHistory, DecisionRecord
from .learning import LearningSample, PassiveLearningEngine
from .scheduler import SafetyScheduler

if TYPE_CHECKING:
    from .coordinator import DtuProSCoordinator


@dataclass(frozen=True, slots=True)
class ControllerStatus:
    """Current controller state exposed through Home Assistant entities."""

    mode: ControllerMode = ControllerMode.DISABLED
    state: str = "Disabled"
    grid_power_w: float | None = None
    grid_error_w: float | None = None
    current_limit_percent: int | None = None
    calculated_limit_percent: int | None = None
    last_decision: str | None = None
    last_decision_time: datetime | None = None
    last_command_result: str | None = None
    last_command_time: datetime | None = None
    last_error: str | None = None


class ZeroInjectionController:
    """Coordinate acquisition, pure decision, scheduler, and verified writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DtuProSCoordinator,
        acquisition: AcquisitionEngine,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._acquisition = acquisition
        self._mode = ControllerMode.DISABLED
        self._target_grid_power_w = DEFAULT_TARGET_GRID_POWER_W
        self._deadband_w = DEFAULT_DEADBAND_W
        self._stabilization_delay_seconds = DEFAULT_STABILIZATION_DELAY_SECONDS
        self._watts_per_percent = DEFAULT_WATTS_PER_PERCENT
        self._maximum_step_percent = DEFAULT_MAXIMUM_STEP_PERCENT
        self._scheduler = SafetyScheduler(self._stabilization_delay_seconds)
        self._history = DecisionHistory()
        self._learning = PassiveLearningEngine()
        self._status = ControllerStatus()
        self._valid_grid_measurements = 0
        self._cancel_tick: Callable[[], None] | None = None
        self._tick_lock = asyncio.Lock()
        self.commands_sent = 0
        self.commands_succeeded = 0
        self.commands_failed = 0
        self.commands_simulated = 0

    @property
    def mode(self) -> ControllerMode:
        return self._mode

    @property
    def status(self) -> ControllerStatus:
        return self._status

    @property
    def scheduler(self) -> SafetyScheduler:
        return self._scheduler

    @property
    def history(self) -> DecisionHistory:
        return self._history

    @property
    def learning(self) -> PassiveLearningEngine:
        return self._learning

    @property
    def target_grid_power_w(self) -> int:
        return self._target_grid_power_w

    @property
    def deadband_w(self) -> int:
        return self._deadband_w

    @property
    def stabilization_delay_seconds(self) -> int:
        return self._stabilization_delay_seconds

    @property
    def watts_per_percent(self) -> float:
        return self._watts_per_percent

    @property
    def maximum_step_percent(self) -> int:
        return self._maximum_step_percent

    async def async_start(self) -> None:
        """Start periodic local acquisition; mode remains disabled after restart."""
        self._cancel_tick = async_track_time_interval(
            self._hass, self._async_scheduled_tick, CONTROLLER_INTERVAL
        )

    async def async_stop(self) -> None:
        """Stop periodic evaluation without changing DTU values."""
        if self._cancel_tick is not None:
            self._cancel_tick()
            self._cancel_tick = None

    async def _async_scheduled_tick(self, _now: datetime) -> None:
        await self.async_tick()

    async def async_set_mode(self, mode: str) -> None:
        """Select an explicit mode; Production is never restored on startup."""
        self._mode = ControllerMode(mode)
        if self._mode is ControllerMode.DISABLED:
            self._scheduler.pause()
        elif self._scheduler.state is SchedulerState.PAUSED:
            self._scheduler.reset()
        self._set_status(state=self._mode.value, last_error=None)

    def set_target_grid_power(self, value: int) -> None:
        self._target_grid_power_w = value

    def set_deadband(self, value: int) -> None:
        self._deadband_w = value

    def set_stabilization_delay(self, value: int) -> None:
        self._stabilization_delay_seconds = value
        self._scheduler.configure(value)

    def set_watts_per_percent(self, value: float) -> None:
        self._watts_per_percent = value

    def set_maximum_step(self, value: int) -> None:
        self._maximum_step_percent = value

    def async_rearm(self) -> None:
        """Allow a user to clear a paused/error scheduler without a DTU write."""
        self._scheduler.reset()
        self._set_status(state="Idle", last_error=None)

    async def async_tick(self) -> None:
        """Evaluate one local measurement and possibly schedule one safe command."""
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            if self._mode is ControllerMode.DISABLED:
                self._set_status(state="Disabled")
                return

            measurement = self._acquisition.read_grid_power()
            if measurement.power_w is None:
                self._valid_grid_measurements = 0
                self._scheduler.pause()
                self._record(None, None, None, "Grid sensor unavailable", False, False, measurement.error)
                self._set_status(
                    state="Paused",
                    last_decision="Grid sensor unavailable",
                    last_error=measurement.error,
                )
                return

            self._valid_grid_measurements += 1
            if self._valid_grid_measurements < VALID_GRID_MEASUREMENTS_REQUIRED:
                self._scheduler.pause()
                self._record(measurement.power_w, None, None, "Waiting for valid grid data", False, False, None)
                self._set_status(
                    state="Paused",
                    grid_power_w=measurement.power_w,
                    last_decision="Waiting for valid grid data",
                    last_error=None,
                )
                return
            if self._valid_grid_measurements == VALID_GRID_MEASUREMENTS_REQUIRED:
                self._scheduler.reset()

            current_limit = self._current_consistent_limit()
            if current_limit is None:
                self._scheduler.pause()
                self._record(measurement.power_w, None, None, "DTU unavailable", False, False, "Temporary limits are unavailable or inconsistent")
                self._set_status(
                    state="Paused",
                    grid_power_w=measurement.power_w,
                    last_decision="DTU unavailable",
                    last_error="Temporary limits are unavailable or inconsistent",
                )
                return

            decision = calculate_power_limit(
                grid_power_w=measurement.power_w,
                target_grid_power_w=self._target_grid_power_w,
                deadband_w=self._deadband_w,
                current_limit_percent=current_limit,
                watts_per_percent=self._watts_per_percent,
                minimum_limit_percent=2,
                maximum_limit_percent=100,
                maximum_step_percent=self._maximum_step_percent,
            )
            self._set_status(
                state=self._scheduler.state.value,
                grid_power_w=measurement.power_w,
                grid_error_w=decision.grid_error_w,
                current_limit_percent=current_limit,
                calculated_limit_percent=decision.applied_limit_percent,
                last_decision=decision.reason.value,
                last_error=None,
            )
            if not decision.command_needed:
                self._record(measurement.power_w, current_limit, decision, decision.reason.value, False, False, None)
                return

            if self._mode is ControllerMode.SIMULATION:
                self.commands_simulated += 1
                self._record(measurement.power_w, current_limit, decision, "Simulation mode", False, False, None)
                self._set_status(last_decision="Simulation mode", last_command_result="Simulated")
                return

            if not self._coordinator.manual_writes_enabled:
                self._scheduler.pause()
                self._record(measurement.power_w, current_limit, decision, "Manual writes disabled", False, False, None)
                self._set_status(state="Paused", last_error="Enable Manual DTU Writes is off")
                return

            self.commands_sent += 1
            success, result = await self._scheduler.async_execute(
                self._mode,
                lambda: self._coordinator.async_set_all_temporary_power_limits(
                    decision.applied_limit_percent
                ),
            )
            if success:
                self.commands_succeeded += 1
                now = datetime.now(UTC)
                self._learning.record(
                    LearningSample(
                        timestamp=now,
                        old_limit=current_limit,
                        new_limit=decision.applied_limit_percent,
                        grid_before=measurement.power_w,
                        grid_after=None,
                        dtu_power_before=self._coordinator.data.active_power_w if self._coordinator.data else None,
                        dtu_power_after=None,
                        configured_wait_time=self._stabilization_delay_seconds,
                        observed_change=None,
                        estimated_watts_per_percent=self._watts_per_percent,
                    )
                )
            else:
                self.commands_failed += 1
            self._record(measurement.power_w, current_limit, decision, result, success, success, None if success else result)
            self._set_status(
                state=self._scheduler.state.value,
                last_decision=result,
                last_command_result=result,
                last_command_time=datetime.now(UTC),
                last_error=None if success else result,
            )

    def _current_consistent_limit(self) -> int | None:
        data = self._coordinator.data
        if data is None or not data.connected:
            return None
        limits = [
            data.port_1_temporary_power_limit_percent,
            data.port_2_temporary_power_limit_percent,
            data.port_3_temporary_power_limit_percent,
        ]
        if any(value is None for value in limits) or len(set(limits)) != 1:
            return None
        return limits[0]

    def _record(
        self,
        grid_power_w: float | None,
        current_limit: int | None,
        decision: ControlDecision | None,
        reason: str,
        sent: bool,
        confirmed: bool,
        error: str | None,
    ) -> None:
        self._history.append(
            DecisionRecord(
                timestamp=datetime.now(UTC),
                controller_mode=self._mode.value,
                grid_power_w=grid_power_w,
                target_grid_power_w=self._target_grid_power_w,
                deadband_w=self._deadband_w,
                current_limit_percent=current_limit,
                calculated_limit_percent=decision.calculated_limit_percent if decision else None,
                applied_limit_percent=decision.applied_limit_percent if decision else None,
                watts_per_percent=self._watts_per_percent,
                scheduler_state=self._scheduler.state.value,
                decision_reason=reason,
                command_sent=sent,
                command_confirmed=confirmed,
                error_message=error,
            )
        )

    def _set_status(self, **changes: object) -> None:
        self._status = replace(
            self._status,
            **{
                **changes,
                "mode": self._mode,
                "last_decision_time": datetime.now(UTC),
            },
        )
        self._coordinator.async_update_listeners()
