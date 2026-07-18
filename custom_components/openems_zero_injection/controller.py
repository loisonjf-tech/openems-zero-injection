"""Build004 controller orchestration with no battery-specific behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .acquisition import AcquisitionEngine
from .const import (
    CONTROLLER_INTERVAL,
    DEFAULT_DEADBAND_W,
    DEFAULT_INSTALLED_NOMINAL_POWER_W,
    DEFAULT_MAXIMUM_STEP_PERCENT,
    DEFAULT_STABILIZATION_DELAY_SECONDS,
    DEFAULT_TARGET_GRID_POWER_W,
    DTU_MEASUREMENT_MAX_AGE_SECONDS,
    GRID_MEASUREMENT_MAX_AGE_SECONDS,
    MAX_INSTALLED_NOMINAL_POWER_W,
    MIN_INSTALLED_NOMINAL_POWER_W,
    MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS,
    SIGNIFICANT_POWER_CHANGE_W,
    SIMULATION_DIAGNOSTIC_REFRESH_SECONDS,
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


DISPLAY_LABELS_FR = {
    "Within deadband": "Dans la zone de tolérance",
    "Grid import": "Consommation sur le réseau",
    "Excess export": "Injection excessive sur le réseau",
    "Waiting for stabilization": "Attente de stabilisation",
    "Simulation awaiting significant measurements": "Simulation en attente de nouvelles mesures significatives",
    "Simulation mode": "Mode simulation",
    "Production mode": "Mode production",
    "Disabled": "Désactivé",
    "Simulation": "Simulation",
    "Production": "Production",
    "Paused": "En pause",
    "Error": "Erreur",
    "Idle": "Inactif",
    "Waiting": "En attente",
    "Writing": "Écriture en cours",
    "Verifying": "Vérification en cours",
    "Command confirmed": "Commande confirmée",
    "Command failed": "Échec de la commande",
    "Command simulated": "Commande simulée",
    "DTU unavailable": "DTU indisponible",
    "Grid sensor unavailable": "Compteur réseau indisponible",
    "Limit unchanged": "Limite inchangée",
    "Maximum step applied": "Pas maximal appliqué",
    "Data unavailable": "Données indisponibles",
    "Temporary limit unavailable": "Limite temporaire indisponible",
    "Limits inconsistent": "Limites DTU incohérentes",
    "Controller disabled": "Contrôleur désactivé",
}


def display_label(value: str | None) -> str | None:
    """Return the French user-facing label while preserving internal codes."""
    return DISPLAY_LABELS_FR.get(value, value)


@dataclass(frozen=True, slots=True)
class ControllerStatus:
    """Current controller state exposed through Home Assistant entities."""

    mode: ControllerMode = ControllerMode.DISABLED
    state: str = "Disabled"
    grid_power_w: float | None = None
    grid_error_w: float | None = None
    current_limit_percent: int | None = None
    real_dtu_limit_percent: int | None = None
    calculated_limit_percent: int | None = None
    simulated_limit_percent: int | None = None
    last_decision: str | None = None
    last_decision_time: datetime | None = None
    last_command_result: str | None = None
    last_command_time: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    """One coherent set of measurements used for exactly one decision."""

    grid_power_w: float
    grid_power_timestamp: datetime
    dtu_power_w: float | None
    dtu_power_timestamp: datetime
    temporary_limits: tuple[int, int, int]
    temporary_limits_timestamp: datetime
    target_power_w: int
    created_at: datetime


class ZeroInjectionController:
    """Coordinate acquisition, pure decision, scheduler, and verified writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DtuProSCoordinator,
        acquisition: AcquisitionEngine,
        *,
        installed_nominal_power_w: int = DEFAULT_INSTALLED_NOMINAL_POWER_W,
        installed_power_source: str = "initial_configuration",
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._acquisition = acquisition
        self._mode = ControllerMode.DISABLED
        self._target_grid_power_w = DEFAULT_TARGET_GRID_POWER_W
        self._deadband_w = DEFAULT_DEADBAND_W
        self._stabilization_delay_seconds = DEFAULT_STABILIZATION_DELAY_SECONDS
        self._installed_nominal_power_w = 0
        self._installed_power_source = installed_power_source
        self._installed_power_updated_at: datetime | None = None
        self._previous_installed_nominal_power_w: int | None = None
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
        self.decisions_evaluated = 0
        self.decisions_blocked_stabilization = 0
        self.decisions_limit_unchanged = 0
        self.decisions_within_deadband = 0
        self._simulated_current_limit: int | None = None
        self._last_simulated_limit: int | None = None
        self._last_simulated_command_time: datetime | None = None
        self._last_decision_sequence = 0
        self._last_command_sequence: int | None = None
        self._last_evaluated_snapshot: DecisionSnapshot | None = None
        self._last_evaluated_configuration_generation = -1
        self._configuration_generation = 0
        self.set_installed_nominal_power(
            installed_nominal_power_w, source=installed_power_source, log_change=False
        )

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
        return self._installed_nominal_power_w / 100

    @property
    def installed_nominal_power_w(self) -> int:
        return self._installed_nominal_power_w

    @property
    def installed_power_source(self) -> str:
        return self._installed_power_source

    @property
    def installed_power_updated_at(self) -> datetime | None:
        return self._installed_power_updated_at

    @property
    def previous_installed_nominal_power_w(self) -> int | None:
        return self._previous_installed_nominal_power_w

    @property
    def maximum_step_percent(self) -> int:
        return self._maximum_step_percent

    @property
    def simulated_current_limit(self) -> int | None:
        return self._simulated_current_limit

    @property
    def last_simulated_limit(self) -> int | None:
        return self._last_simulated_limit

    @property
    def last_simulated_command_time(self) -> datetime | None:
        return self._last_simulated_command_time

    @property
    def last_decision_sequence(self) -> int:
        return self._last_decision_sequence

    @property
    def last_command_sequence(self) -> int | None:
        return self._last_command_sequence

    @property
    def waiting_state(self) -> str:
        """Describe why Simulation is currently holding its recommendation."""
        return (
            "Nouvelles mesures significatives attendues"
            if self._mode is ControllerMode.SIMULATION
            and self._last_evaluated_snapshot is not None
            else "Aucune attente"
        )

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
        previous_mode = self._mode
        self._mode = ControllerMode(mode)
        self._configuration_generation += 1
        if self._mode is ControllerMode.DISABLED:
            self._scheduler.pause()
            self._simulated_current_limit = None
            self._last_simulated_limit = None
            self._last_simulated_command_time = None
        elif self._scheduler.state is SchedulerState.PAUSED:
            self._scheduler.reset()
        if self._mode is ControllerMode.SIMULATION and previous_mode is not ControllerMode.SIMULATION:
            self._simulated_current_limit = self._current_consistent_limit(require_fresh=True)
            self._last_simulated_limit = None
            self._last_simulated_command_time = None
        self._set_status(
            state=self._mode.value,
            simulated_limit_percent=self._simulated_current_limit,
            last_error=None,
        )

    def set_target_grid_power(self, value: int) -> None:
        self._target_grid_power_w = value
        self._configuration_generation += 1

    def set_deadband(self, value: int) -> None:
        self._deadband_w = value
        self._configuration_generation += 1

    def set_stabilization_delay(self, value: int) -> None:
        self._stabilization_delay_seconds = value
        self._scheduler.configure(value)
        self._configuration_generation += 1

    def set_installed_nominal_power(
        self, value: float, *, source: str, log_change: bool = True
    ) -> None:
        """Set the persistent manual PV nominal power used for all decisions."""
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("Installed nominal power must be numeric")
        if int(value) != value or not (
            MIN_INSTALLED_NOMINAL_POWER_W <= value <= MAX_INSTALLED_NOMINAL_POWER_W
        ):
            raise ValueError("Installed nominal power is outside the permitted range")
        new_value = int(value)
        if self._installed_nominal_power_w == new_value:
            return
        old_value = self._installed_nominal_power_w or None
        self._installed_nominal_power_w = new_value
        self._previous_installed_nominal_power_w = old_value
        self._installed_power_source = source
        self._installed_power_updated_at = datetime.now(UTC)
        self._configuration_generation += 1
        if log_change:
            logging.getLogger(__name__).info(
                "Installed nominal PV power updated from %s W to %s W", old_value, new_value
            )
        self._coordinator.async_update_listeners()

    def set_maximum_step(self, value: int) -> None:
        self._maximum_step_percent = value
        self._configuration_generation += 1

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

            real_limit = self._current_consistent_limit(require_fresh=True)
            current_limit = real_limit
            if current_limit is None:
                limit_error = (
                    "Temporary limits are stale or inconsistent"
                    if self._mode is ControllerMode.PRODUCTION
                    else "Temporary limits are unavailable or inconsistent"
                )
                self._scheduler.pause()
                self._record(
                    measurement.power_w,
                    None,
                    None,
                    "DTU unavailable",
                    False,
                    False,
                    limit_error,
                )
                self._set_status(
                    state="Paused",
                    grid_power_w=measurement.power_w,
                    last_decision="DTU unavailable",
                    last_error=limit_error,
                )
                return

            if self._scheduler.state is SchedulerState.PAUSED:
                self._scheduler.reset()
                self._set_status(state="Idle", last_error=None)

            snapshot = self._build_snapshot(measurement.power_w, measurement.timestamp)
            if snapshot is None:
                self._set_status(
                    state="Paused",
                    grid_power_w=measurement.power_w,
                    last_decision="Measurements not synchronized",
                    last_error="Measurements not synchronized",
                )
                return
            if not self._requires_new_decision(snapshot):
                return
            self._last_evaluated_snapshot = snapshot
            self._last_evaluated_configuration_generation = self._configuration_generation

            decision = calculate_power_limit(
                grid_power_w=snapshot.grid_power_w,
                target_grid_power_w=snapshot.target_power_w,
                deadband_w=self._deadband_w,
                current_limit_percent=current_limit,
                watts_per_percent=self.watts_per_percent,
                minimum_limit_percent=2,
                maximum_limit_percent=100,
                maximum_step_percent=self._maximum_step_percent,
            )
            if self._mode is ControllerMode.SIMULATION:
                # Simulation has no stabilization loop and never models a DTU
                # response. Every meaningful snapshot is an independent,
                # display-only recommendation based on the real DTU limit.
                recommendation_changed = (
                    decision.command_needed
                    and decision.applied_limit_percent != self._simulated_current_limit
                )
                if recommendation_changed:
                    self._simulated_current_limit = decision.applied_limit_percent
                    self._last_simulated_limit = decision.applied_limit_percent
                    self._last_simulated_command_time = datetime.now(UTC)
                    self.commands_simulated += 1
                    self._last_command_sequence = self._last_decision_sequence + 1
                self._record(
                    snapshot.grid_power_w,
                    current_limit,
                    decision,
                    decision.reason.value,
                    False,
                    recommendation_changed,
                    None,
                )
                self._set_status(
                    state=ControllerMode.SIMULATION.value,
                    grid_power_w=snapshot.grid_power_w,
                    grid_error_w=decision.grid_error_w,
                    current_limit_percent=current_limit,
                    real_dtu_limit_percent=real_limit,
                    calculated_limit_percent=decision.calculated_limit_percent,
                    simulated_limit_percent=self._simulated_current_limit,
                    last_decision="Simulation awaiting significant measurements",
                    last_command_result=(
                        "Command simulated" if recommendation_changed else self._status.last_command_result
                    ),
                    last_command_time=(
                        self._last_simulated_command_time
                        if recommendation_changed
                        else self._status.last_command_time
                    ),
                    last_error=None,
                )
                return

            self._set_status(
                state=self._scheduler.state.value,
                grid_power_w=snapshot.grid_power_w,
                grid_error_w=decision.grid_error_w,
                current_limit_percent=current_limit,
                real_dtu_limit_percent=real_limit,
                calculated_limit_percent=decision.calculated_limit_percent,
                simulated_limit_percent=self._simulated_current_limit,
                last_decision=decision.reason.value,
                last_error=None,
            )
            if not decision.command_needed:
                if decision.reason.value == "Within deadband":
                    self.decisions_within_deadband += 1
                else:
                    self.decisions_limit_unchanged += 1
                self._record(snapshot.grid_power_w, current_limit, decision, decision.reason.value, False, False, None)
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
                        estimated_watts_per_percent=self.watts_per_percent,
                    )
                )
            else:
                self.commands_failed += 1
            self._last_command_sequence = self._last_decision_sequence + 1
            self._record(measurement.power_w, current_limit, decision, result, success, success, None if success else result)
            self._set_status(
                state=self._scheduler.state.value,
                last_decision=result,
                last_command_result=result,
                last_command_time=datetime.now(UTC),
                last_error=None if success else result,
            )

    def _current_consistent_limit(self, *, require_fresh: bool) -> int | None:
        data = self._coordinator.data
        if data is None or not data.connected:
            return None
        if require_fresh and not self._coordinator.temporary_limits_ready:
            return None
        limits = [
            data.port_1_temporary_power_limit_percent,
            data.port_2_temporary_power_limit_percent,
            data.port_3_temporary_power_limit_percent,
        ]
        if any(value is None for value in limits) or len(set(limits)) != 1:
            return None
        return limits[0]

    def _build_snapshot(
        self, grid_power_w: float, grid_timestamp: datetime | None
    ) -> DecisionSnapshot | None:
        """Return only a fresh, time-compatible control snapshot."""
        data = self._coordinator.data
        if data is None or grid_timestamp is None:
            return None
        now = datetime.now(UTC)
        dtu_timestamp = getattr(data, "last_success", None) or now
        limits_timestamp = getattr(self._coordinator, "temporary_limits_timestamp", None)
        if callable(limits_timestamp):
            limits_timestamp = limits_timestamp()
        if limits_timestamp is None:
            limits_timestamp = dtu_timestamp
        if dtu_timestamp is None or limits_timestamp is None:
            return None
        if (
            (now - grid_timestamp).total_seconds() > GRID_MEASUREMENT_MAX_AGE_SECONDS
            or (now - dtu_timestamp).total_seconds() > DTU_MEASUREMENT_MAX_AGE_SECONDS
            or abs((grid_timestamp - dtu_timestamp).total_seconds())
            > MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS
        ):
            return None
        limits = (
            data.port_1_temporary_power_limit_percent,
            data.port_2_temporary_power_limit_percent,
            data.port_3_temporary_power_limit_percent,
        )
        if any(value is None for value in limits):
            return None
        return DecisionSnapshot(
            grid_power_w=grid_power_w,
            grid_power_timestamp=grid_timestamp,
            dtu_power_w=data.active_power_w,
            dtu_power_timestamp=dtu_timestamp,
            temporary_limits=(limits[0], limits[1], limits[2]),
            temporary_limits_timestamp=limits_timestamp,
            target_power_w=self._target_grid_power_w,
            created_at=now,
        )

    def _requires_new_decision(self, snapshot: DecisionSnapshot) -> bool:
        """Return whether input changed enough to justify a new decision.

        Timestamp-only refreshes and small sensor noise are deliberately ignored.
        A configuration or mode change is represented by the configuration
        generation and always gets one fresh evaluation.
        """
        previous = self._last_evaluated_snapshot
        if (
            previous is None
            or self._last_evaluated_configuration_generation
            != self._configuration_generation
        ):
            return True
        if any(
            abs(current - prior) >= 1
            for current, prior in zip(snapshot.temporary_limits, previous.temporary_limits)
        ):
            return True
        if abs(snapshot.grid_power_w - previous.grid_power_w) > SIGNIFICANT_POWER_CHANGE_W:
            return True
        if snapshot.dtu_power_w is None or previous.dtu_power_w is None:
            return snapshot.dtu_power_w != previous.dtu_power_w
        if abs(snapshot.dtu_power_w - previous.dtu_power_w) > SIGNIFICANT_POWER_CHANGE_W:
            return True
        return (
            self._mode is ControllerMode.SIMULATION
            and (snapshot.created_at - previous.created_at).total_seconds()
            >= SIMULATION_DIAGNOSTIC_REFRESH_SECONDS
        )

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
        if decision is not None:
            self.decisions_evaluated += 1
            self._last_decision_sequence = self.decisions_evaluated
            self._status = replace(self._status, last_decision_time=datetime.now(UTC))
            self._coordinator.async_update_listeners()
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
                watts_per_percent=self.watts_per_percent,
                scheduler_state=self._scheduler.state.value,
                decision_reason=reason,
                command_sent=sent,
                command_confirmed=confirmed,
                error_message=error,
            )
        )

    def _set_status(self, **changes: object) -> None:
        updated = replace(self._status, **{**changes, "mode": self._mode})
        if updated == self._status:
            return
        self._status = updated
        self._coordinator.async_update_listeners()
