"""Build004 controller orchestration with no battery-specific behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .acquisition import AcquisitionEngine
from .battery import BatteryManager, NullBatteryManager
from .const import (
    CONTROLLER_INTERVAL,
    DEFAULT_DEADBAND_W,
    DEFAULT_INSTALLED_NOMINAL_POWER_W,
    DEFAULT_MAXIMUM_STEP_PERCENT,
    DEFAULT_FINE_CORRECTION_STEP_PERCENT,
    DEFAULT_PREDICTIVE_ERROR_THRESHOLD_W,
    DEFAULT_STABILIZATION_DELAY_SECONDS,
    DEFAULT_TARGET_GRID_POWER_W,
    DTU_MEASUREMENT_MAX_AGE_SECONDS,
    GRID_MEASUREMENT_MAX_AGE_SECONDS,
    MAX_INSTALLED_NOMINAL_POWER_W,
    MIN_INSTALLED_NOMINAL_POWER_W,
    MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS,
    SIGNIFICANT_POWER_CHANGE_W,
    INTERNAL_SIMULATION_DIAGNOSTIC_REFRESH_SECONDS,
    ControllerMode,
    ProductionStartupStrategy,
    SchedulerState,
    VALID_GRID_MEASUREMENTS_REQUIRED,
)
from .calibration import CalibrationManager
from .context import ContextAnalyzer
from .decision import (
    ControlDecision,
    DecisionReason,
    PredictiveControlDecision,
    calculate_power_limit,
    calculate_predictive_power_limit,
)
from .energy_policy import EnergyPolicyEngine
from .energy_strategy import DtuControlDirective
from .history import DecisionHistory, DecisionRecord
from .learning import LearningSample, PassiveLearningEngine
from .scheduler import SafetyScheduler
from .trace import TraceRecorder
from .persistent_history import HistoryEventType, PersistentHistoryRecorder

if TYPE_CHECKING:
    from .coordinator import DtuProSCoordinator


_LOGGER = logging.getLogger(__name__)


DISPLAY_LABELS_FR = {
    "No batteries configured": "Aucune batterie configurée",
    "Passive": "Passif",
    "Within deadband": "Dans la zone de tolérance",
    "Grid import": "Consommation sur le réseau",
    "Excess export": "Injection excessive sur le réseau",
    "Waiting for stabilization": "Attente de stabilisation",
    "Simulation awaiting significant measurements": "Simulation en attente de nouvelles mesures significatives",
    "Simulation active": "Simulation active",
    "Simulation awaiting measurements": "Simulation en attente de nouvelles mesures",
    "Simulation mode": "Mode simulation",
    "Production mode": "Mode production",
    "Disabled": "Manuel",
    "Simulation": "Simulation",
    "Production": "Régulation automatique",
    "Paused": "En pause",
    "Error": "Erreur",
    "Idle": "Inactif",
    "Monitoring": "Régulation active",
    "Waiting": "En attente",
    "Writing": "Écriture en cours",
    "Verifying": "Vérification en cours",
    "Command confirmed": "Commande confirmée",
    "Command failed": "Échec de la commande",
    "Command simulated": "Commande simulée",
    "DTU unavailable": "DTU indisponible",
    "Temporary limit reference unavailable": "Référence de limite temporaire indisponible",
    "Takeover waiting for DTU connection": "Prise de contrôle en attente de connexion DTU",
    "Takeover confirmed": "Prise de contrôle confirmée",
    "Takeover failed": "Échec de la prise de contrôle",
    "Grid sensor unavailable": "Compteur réseau indisponible",
    "Limit unchanged": "Limite inchangée",
    "Maximum step applied": "Pas maximal appliqué",
    "Data unavailable": "Données indisponibles",
    "Temporary limit unavailable": "Limite temporaire indisponible",
    "Limits inconsistent": "Limites DTU incohérentes",
    "Controller disabled": "Mode manuel",
    "Predictive limit applied": "Limite prédictive appliquée",
    "Fine correction applied": "Correction fine appliquée",
    "Battery capacity release applied": "Libération DTU selon capacité batterie",
    "Grid measurement is older than the allowed age": "Mesure réseau trop ancienne",
    "PV measurement is older than the allowed age": "Mesure PV trop ancienne",
    "Grid/PV timestamp difference exceeds the allowed tolerance": "Écart temporel réseau/PV trop élevé",
    "Grid timestamp unavailable": "Horodatage réseau indisponible",
    "PV timestamp unavailable": "Horodatage PV indisponible",
    "DTU telemetry unavailable": "Télémétrie DTU indisponible",
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
    commanded_limit_percent: int | None = None
    simulated_limit_percent: int | None = None
    last_decision: str | None = None
    last_decision_time: datetime | None = None
    last_command_result: str | None = None
    last_command_time: datetime | None = None
    last_error: str | None = None
    scheduler_inactive_reason: str | None = None
    estimated_load_w: float | None = None
    predictive_strategy: str | None = None
    policy_id: str | None = None
    policy_reason: str | None = None


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


@dataclass(frozen=True, slots=True)
class MeasurementSyncDiagnostics:
    """Explain the exact timestamp validation of the latest control snapshot."""

    grid_source_timestamp: datetime | None = None
    pv_source_timestamp: datetime | None = None
    grid_age_seconds: float | None = None
    pv_age_seconds: float | None = None
    difference_seconds: float | None = None
    tolerance_seconds: float = MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS
    reason: str | None = None


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
        initial_mode: ControllerMode = ControllerMode.DISABLED,
        mode_restore_source: str = "default",
        production_startup_strategy: ProductionStartupStrategy = ProductionStartupStrategy.SAFE,
        takeover_limit_percent: int = 100,
        auto_resume_production: bool = False,
        battery_manager: BatteryManager | None = None,
        persistent_history_recorder: PersistentHistoryRecorder | None = None,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._acquisition = acquisition
        # V1 deliberately never reads this object. V1.1 will make any battery
        # policy depend on this neutral interface rather than a vendor API.
        self._battery_manager: BatteryManager = battery_manager or NullBatteryManager()
        self._mode = initial_mode
        self._mode_restore_source = mode_restore_source
        self._production_startup_strategy = production_startup_strategy
        self._takeover_limit_percent = takeover_limit_percent
        self._auto_resume_production = auto_resume_production
        self._takeover_pending = (
            initial_mode is ControllerMode.PRODUCTION
            and auto_resume_production
            and production_startup_strategy is ProductionStartupStrategy.TAKEOVER
        )
        self._target_grid_power_w = DEFAULT_TARGET_GRID_POWER_W
        self._deadband_w = DEFAULT_DEADBAND_W
        self._stabilization_delay_seconds = DEFAULT_STABILIZATION_DELAY_SECONDS
        self._installed_nominal_power_w = 0
        self._installed_power_source = installed_power_source
        self._installed_power_updated_at: datetime | None = None
        self._previous_installed_nominal_power_w: int | None = None
        self._maximum_step_percent = DEFAULT_MAXIMUM_STEP_PERCENT
        self._predictive_error_threshold_w = DEFAULT_PREDICTIVE_ERROR_THRESHOLD_W
        self._fine_correction_step_percent = DEFAULT_FINE_CORRECTION_STEP_PERCENT
        self._scheduler = SafetyScheduler(self._stabilization_delay_seconds)
        self._history = DecisionHistory()
        self._learning = PassiveLearningEngine()
        self._context_analyzer = ContextAnalyzer()
        self._calibration_manager = CalibrationManager()
        self._energy_policy_engine = EnergyPolicyEngine()
        self._trace_recorder = TraceRecorder()
        self._persistent_history_recorder = persistent_history_recorder
        self._last_history_transition_signature: tuple[object, ...] | None = None
        self._last_history_battery_signature: tuple[object, ...] | None = None
        self._status = ControllerStatus(
            mode=initial_mode,
            state=initial_mode.value,
            last_decision=(
                "Controller disabled"
                if initial_mode is ControllerMode.DISABLED
                else None
            ),
            scheduler_inactive_reason=(
                "Controller disabled"
                if initial_mode is ControllerMode.DISABLED
                else None
            ),
        )
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
        self._last_requested_limit_percent: int | None = None
        self._last_requested_limit_at: datetime | None = None
        self._last_dtu_limit_observation: dict[str, Any] | None = None
        self._last_evaluated_snapshot: DecisionSnapshot | None = None
        self._measurement_sync_diagnostics = MeasurementSyncDiagnostics()
        self._last_evaluated_configuration_generation = -1
        self._configuration_generation = 0
        self.set_installed_nominal_power(
            installed_nominal_power_w, source=installed_power_source, log_change=False
        )

    @property
    def mode(self) -> ControllerMode:
        return self._mode

    @property
    def mode_restore_source(self) -> str:
        """Return how the controller mode was selected at startup."""
        return self._mode_restore_source

    @property
    def takeover_pending(self) -> bool:
        """Return whether a deliberate Production takeover still has to run."""
        return self._takeover_pending

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
    def battery_manager(self) -> BatteryManager:
        """Expose the future V1.1 battery contract without using it in V1."""
        return self._battery_manager

    @property
    def context_analyzer(self) -> ContextAnalyzer:
        """Expose the passive Build005 contract without control authority."""
        return self._context_analyzer

    @property
    def calibration_manager(self) -> CalibrationManager:
        """Expose passive calibration diagnostics without control influence."""
        return self._calibration_manager

    @property
    def energy_policy_engine(self) -> EnergyPolicyEngine:
        """Expose the V1-compatible target policy boundary."""
        return self._energy_policy_engine

    @property
    def trace_recorder(self) -> TraceRecorder:
        """Expose the passive RC3 recorder for diagnostics only."""
        return self._trace_recorder

    @property
    def measurement_sync_diagnostics(self) -> MeasurementSyncDiagnostics:
        """Expose the latest snapshot validation without triggering I/O."""
        return self._measurement_sync_diagnostics

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
    def dtu_limit_power_observation(self) -> dict[str, Any] | None:
        """Return the latest coherent limit/power evidence without DTU I/O."""
        if self._last_dtu_limit_observation is None:
            return None
        return dict(self._last_dtu_limit_observation)

    @property
    def waiting_state(self) -> str:
        """Describe why Simulation is currently holding its recommendation."""
        return (
            "Nouvelles mesures significatives attendues"
            if self._mode is ControllerMode.SIMULATION
            and self._last_evaluated_snapshot is not None
            else "Aucune attente"
        )

    @property
    def scheduler_display_state(self) -> str:
        """Return a user-facing state without exposing an expired wait."""
        if self._mode is ControllerMode.SIMULATION:
            return (
                "Simulation awaiting measurements"
                if self._last_evaluated_snapshot is not None
                else "Simulation active"
            )
        if (
            self._mode is ControllerMode.PRODUCTION
            and self._scheduler.state in {SchedulerState.IDLE, SchedulerState.WAITING}
            and self._scheduler.remaining_seconds() == 0
        ):
            return "Monitoring"
        return self._scheduler.state.value

    async def async_start(self) -> None:
        """Start periodic local acquisition using the restored controller mode."""
        if self._cancel_tick is not None:
            return
        restored_mode = (
            "active" if self._mode is ControllerMode.PRODUCTION else self._mode.value.lower()
        )
        _LOGGER.info("Controller mode restored: %s", restored_mode)
        _LOGGER.info("Controller mode source: %s", self._mode_restore_source)
        if self._persistent_history_recorder is not None:
            await self._persistent_history_recorder.async_start()
        if self._mode is ControllerMode.PRODUCTION:
            self._trace_recorder.start_session(
                reason="controller_started_in_production",
                configuration=self._trace_configuration(),
            )
        self._cancel_tick = async_track_time_interval(
            self._hass, self._async_scheduled_tick, CONTROLLER_INTERVAL
        )

    async def async_stop(self) -> None:
        """Stop periodic evaluation without changing DTU values."""
        self._trace_recorder.stop_session(reason="integration_unload_or_reload")
        if self._persistent_history_recorder is not None:
            await self._persistent_history_recorder.async_stop()
        if self._cancel_tick is not None:
            self._cancel_tick()
            self._cancel_tick = None

    async def _async_scheduled_tick(self, _now: datetime) -> None:
        await self.async_tick()

    async def async_set_mode(self, mode: str) -> None:
        """Select an explicit mode; persistence is handled by the coordinator."""
        previous_mode = self._mode
        self._mode = ControllerMode(mode)
        if previous_mode is ControllerMode.PRODUCTION and self._mode is not ControllerMode.PRODUCTION:
            self._trace_recorder.stop_session(reason=f"mode_changed_to_{self._mode.value}")
        elif previous_mode is not ControllerMode.PRODUCTION and self._mode is ControllerMode.PRODUCTION:
            self._trace_recorder.start_session(
                reason="mode_changed_to_production",
                configuration=self._trace_configuration(),
            )
        self._mode_restore_source = "options"
        self._configuration_generation += 1
        if self._mode is ControllerMode.DISABLED:
            self._scheduler.reset()
            self._simulated_current_limit = None
            self._last_simulated_limit = None
            self._last_simulated_command_time = None
            self._last_evaluated_snapshot = None
            self._takeover_pending = False
        elif self._scheduler.state is SchedulerState.PAUSED:
            self._scheduler.reset()
        if self._mode is ControllerMode.SIMULATION and previous_mode is not ControllerMode.SIMULATION:
            self._simulated_current_limit = self._current_consistent_limit(require_fresh=True)
            self._last_simulated_limit = None
            self._last_simulated_command_time = None
        if self._mode is ControllerMode.PRODUCTION and previous_mode is not ControllerMode.PRODUCTION:
            # A virtual recommendation can never be a basis or a visible value
            # for a real command.
            self._simulated_current_limit = None
            self._last_simulated_limit = None
            self._last_simulated_command_time = None
            self.commands_simulated = 0
            self._takeover_pending = (
                self._production_startup_strategy
                is ProductionStartupStrategy.TAKEOVER
            )
        self._set_status(
            state=self._mode.value,
            simulated_limit_percent=self._simulated_current_limit,
            calculated_limit_percent=(
                None
                if self._mode in {ControllerMode.DISABLED, ControllerMode.PRODUCTION}
                else self._status.calculated_limit_percent
            ),
            last_command_result=(
                None
                if self._mode is ControllerMode.PRODUCTION
                and previous_mode is not ControllerMode.PRODUCTION
                else self._status.last_command_result
            ),
            last_command_time=(
                None
                if self._mode is ControllerMode.PRODUCTION
                and previous_mode is not ControllerMode.PRODUCTION
                else self._status.last_command_time
            ),
            last_error=None,
            scheduler_inactive_reason=(
                "Controller disabled" if self._mode is ControllerMode.DISABLED else None
            ),
        )

    def set_target_grid_power(self, value: int) -> None:
        self._target_grid_power_w = value
        self._configuration_generation += 1
        self._rotate_trace_session("target_grid_power_changed")

    def set_deadband(self, value: int) -> None:
        self._deadband_w = value
        self._configuration_generation += 1
        self._rotate_trace_session("deadband_changed")

    def set_stabilization_delay(self, value: int) -> None:
        self._stabilization_delay_seconds = value
        self._scheduler.configure(value)
        self._configuration_generation += 1
        self._rotate_trace_session("stabilization_delay_changed")

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
        self._rotate_trace_session("installed_nominal_power_changed")
        if log_change:
            logging.getLogger(__name__).info(
                "Installed nominal PV power updated from %s W to %s W", old_value, new_value
            )
        self._coordinator.async_update_listeners()

    def set_maximum_step(self, value: int) -> None:
        """Keep the historical setting as the V2 fine-correction step."""
        self._maximum_step_percent = value
        self._fine_correction_step_percent = value
        self._configuration_generation += 1
        self._rotate_trace_session("fine_correction_step_changed")

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
                real_limit = self._current_consistent_limit(require_fresh=False)
                measurement = self._acquisition.read_grid_power()
                self._set_status(
                    state="Disabled",
                    grid_power_w=measurement.power_w,
                    current_limit_percent=real_limit,
                    real_dtu_limit_percent=real_limit,
                    calculated_limit_percent=None,
                    commanded_limit_percent=None,
                    simulated_limit_percent=None,
                    last_decision="Controller disabled",
                    last_error=None,
                    scheduler_inactive_reason="Controller disabled",
                )
                return

            if self._mode is ControllerMode.PRODUCTION and self._takeover_pending:
                await self._async_run_takeover()
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
                stabilizing = self._scheduler.remaining_seconds() > 0
                if not stabilizing:
                    self._scheduler.pause()
                reason = (
                    "Waiting for stabilization"
                    if stabilizing
                    else "Waiting for valid grid data"
                )
                self._record(measurement.power_w, None, None, reason, False, False, None)
                self._set_status(
                    state=self._scheduler.state.value if stabilizing else "Paused",
                    grid_power_w=measurement.power_w,
                    last_decision=reason,
                    last_error=None,
                )
                return
            if self._valid_grid_measurements == VALID_GRID_MEASUREMENTS_REQUIRED:
                self._scheduler.reset()

            real_limit = self._current_consistent_limit(require_fresh=True)
            current_limit = real_limit
            if current_limit is None:
                dtu_connected = bool(self._coordinator.data and self._coordinator.data.connected)
                limit_error = (
                    "Temporary limits are stale or inconsistent"
                    if dtu_connected and self._mode is ControllerMode.PRODUCTION
                    else "Temporary limits are unavailable or inconsistent"
                )
                self._scheduler.pause()
                self._record(
                    measurement.power_w,
                    None,
                    None,
                    (
                        "Temporary limit reference unavailable"
                        if dtu_connected
                        else "DTU unavailable"
                    ),
                    False,
                    False,
                    limit_error,
                )
                self._set_status(
                    state="Paused",
                    grid_power_w=measurement.power_w,
                    last_decision=(
                        "Temporary limit reference unavailable"
                        if dtu_connected
                        else "DTU unavailable"
                    ),
                    last_error=limit_error,
                )
                return

            scheduler_recovered = self._scheduler.state is SchedulerState.PAUSED
            if scheduler_recovered:
                self._scheduler.reset()

            snapshot = self._build_snapshot(measurement.power_w, measurement.timestamp)
            if snapshot is None:
                sync_reason = self._measurement_sync_diagnostics.reason
                self._set_status(
                    state="Paused",
                    grid_power_w=measurement.power_w,
                    last_decision="Measurements not synchronized",
                    last_error=sync_reason or "Measurements not synchronized",
                )
                return
            # A valid snapshot proves that a transient measurement failure has
            # recovered. Clear the former error and show the actual scheduler
            # state even when the values do not require another decision.
            if (
                scheduler_recovered
                or self._status.last_error is not None
                or self._status.state == "Paused"
            ):
                display_state = self.scheduler_display_state
                self._set_status(
                    state=display_state,
                    last_decision=(
                        "Monitoring"
                        if display_state == "Monitoring"
                        else self._status.last_decision
                    ),
                    last_error=None,
                )
            self._trace_recorder.observe_measurement(
                grid_power_w=snapshot.grid_power_w,
                grid_source_timestamp=snapshot.grid_power_timestamp,
                pv_power_w=snapshot.dtu_power_w,
                pv_source_timestamp=snapshot.dtu_power_timestamp,
                target_grid_power_w=snapshot.target_power_w,
                deadband_w=self._deadband_w,
                dtu_limit_observation=self._record_dtu_limit_power_observation(snapshot),
            )
            self._record_periodic_history(snapshot, current_limit)
            if not self._requires_new_decision(snapshot):
                if (
                    self._mode is ControllerMode.PRODUCTION
                    and self.scheduler_display_state == "Monitoring"
                    and self._status.state == SchedulerState.WAITING.value
                ):
                    self._set_status(state="Monitoring", last_decision="Monitoring")
                return
            self._last_evaluated_snapshot = snapshot
            self._last_evaluated_configuration_generation = self._configuration_generation

            policy = self._energy_policy_engine.decide(
                snapshot.target_power_w,
                input_snapshot_id=snapshot.created_at.isoformat(),
                decision_timestamp=snapshot.created_at,
                compare_battery_priority=self._mode is ControllerMode.SIMULATION,
                activate_battery_priority=self._mode is ControllerMode.PRODUCTION,
            )
            if policy.comparison is not None:
                comparison = policy.comparison
                self._trace_recorder.record_strategy_comparison(
                    input_snapshot_id=policy.input_snapshot_id,
                    controller_mode=self._mode.value,
                    effective_target_grid_power_w=(
                        comparison.effective_target_grid_power_w
                    ),
                    candidate_target_grid_power_w=(
                        comparison.candidate_target_grid_power_w
                    ),
                    target_delta_w=comparison.target_delta_w,
                    candidate_expected_storage_gain_w=(
                        comparison.candidate_expected_storage_gain_w
                    ),
                    reason_code=comparison.reason_code.value,
                    fallback_used=comparison.fallback_used,
                    eligible_resource_ids=comparison.eligible_resource_ids,
                    dtu_control_directive=comparison.dtu_control_directive.value,
                    max_charge_power_w=comparison.max_charge_power_w,
                    observed_charge_power_w=comparison.observed_charge_power_w,
                    remaining_charge_power_w=comparison.remaining_charge_power_w,
                )
            context = self._context_analyzer.classify()
            decision = self._calculate_decision(
                snapshot,
                current_limit,
                policy.target_grid_power_w,
                policy.dtu_control_directive,
                policy.requested_dtu_limit_percent,
            )
            self._record_history_transition_if_changed(
                snapshot, current_limit, policy
            )
            if self._persistent_history_recorder is not None:
                self._record_persistent_history(
                    HistoryEventType.DECISION,
                    self._history_payload(snapshot, current_limit, decision, policy),
                    timestamp=snapshot.created_at,
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
                    commanded_limit_percent=None,
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
                    estimated_load_w=getattr(decision, "estimated_load_w", None),
                    predictive_strategy=getattr(decision, "strategy", "cautious_correction"),
                    policy_id=policy.policy_id,
                    policy_reason=policy.reason,
                )
                return

            if decision.command_needed and self._coordinator.automatic_write_allowed:
                block_reason = self._scheduler.command_block_reason()
                if block_reason is not None:
                    # Stabilization is an intentional safety state, not a failed
                    # command. Do not create command accounting or an error.
                    self._set_status(
                        state=self._scheduler.state.value,
                        grid_power_w=snapshot.grid_power_w,
                        grid_error_w=decision.grid_error_w,
                        current_limit_percent=current_limit,
                        real_dtu_limit_percent=real_limit,
                        calculated_limit_percent=decision.calculated_limit_percent,
                        commanded_limit_percent=decision.applied_limit_percent,
                        simulated_limit_percent=None,
                        last_decision=block_reason,
                        last_error=None,
                        estimated_load_w=getattr(decision, "estimated_load_w", None),
                        predictive_strategy=getattr(decision, "strategy", "cautious_correction"),
                        policy_id=policy.policy_id,
                        policy_reason=policy.reason,
                    )
                    return

            self._set_status(
                state=self.scheduler_display_state,
                grid_power_w=snapshot.grid_power_w,
                grid_error_w=decision.grid_error_w,
                current_limit_percent=current_limit,
                real_dtu_limit_percent=real_limit,
                calculated_limit_percent=decision.calculated_limit_percent,
                commanded_limit_percent=(
                    decision.applied_limit_percent if decision.command_needed else None
                ),
                simulated_limit_percent=self._simulated_current_limit,
                last_decision=decision.reason.value,
                last_error=None,
                estimated_load_w=getattr(decision, "estimated_load_w", None),
                predictive_strategy=getattr(decision, "strategy", "cautious_correction"),
                policy_id=policy.policy_id,
                policy_reason=policy.reason,
            )
            if not decision.command_needed:
                if decision.reason.value == "Within deadband":
                    self.decisions_within_deadband += 1
                else:
                    self.decisions_limit_unchanged += 1
                self._record(snapshot.grid_power_w, current_limit, decision, decision.reason.value, False, False, None)
                return

            if not self._coordinator.automatic_write_allowed:
                self._scheduler.pause()
                self._record(
                    measurement.power_w,
                    current_limit,
                    decision,
                    "Automatic writes unavailable",
                    False,
                    False,
                    None,
                )
                self._set_status(
                    state="Paused",
                    last_error="Automatic DTU writes are unavailable",
                )
                return

            self.commands_sent += 1
            self._last_command_sequence = (self._last_command_sequence or 0) + 1
            self._trace_recorder.start_command(
                decision_id=self.decisions_evaluated + 1,
                command_id=self._last_command_sequence,
                controller_mode=self._mode.value,
                grid_power_w=snapshot.grid_power_w,
                grid_source_timestamp=snapshot.grid_power_timestamp,
                pv_power_w=snapshot.dtu_power_w,
                pv_source_timestamp=snapshot.dtu_power_timestamp,
                real_limit_before_percent=current_limit,
                calculated_limit_percent=decision.calculated_limit_percent,
                requested_limit_percent=decision.applied_limit_percent,
                decision_reason=decision.reason.value,
                strategy=getattr(decision, "strategy", "cautious_correction"),
                target_grid_power_w=policy.target_grid_power_w,
                deadband_w=self._deadband_w,
                policy_id=policy.policy_id,
                policy_reason=policy.reason,
                policy_confidence=policy.confidence,
                policy_fallback_used=policy.fallback_used,
                context_kind=context.kind.value,
                context_confidence=context.confidence,
                context_reason=context.reason,
                objective="target_grid_power",
                rationale=decision.reason.value,
                configuration=self._trace_configuration(),
                dtu_limit_observation=self._build_dtu_limit_power_observation(
                    snapshot, requested_limit_percent=decision.applied_limit_percent
                ),
            )
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
            self._trace_recorder.finish_command(
                confirmed=success,
                confirmed_limit_percent=decision.applied_limit_percent if success else None,
                error=None if success else result,
                stabilization_delay_seconds=(
                    self._stabilization_delay_seconds if success else None
                ),
            )
            if self._persistent_history_recorder is not None:
                self._record_persistent_history(
                    HistoryEventType.COMMAND_RESULT,
                    self._history_payload(
                        snapshot,
                        current_limit,
                        decision,
                        policy,
                        command_result=result,
                        command_confirmed=success,
                    ),
                )
            self._record(measurement.power_w, current_limit, decision, result, success, success, None if success else result)
            confirmed_limit = (
                self._current_consistent_limit(require_fresh=True) if success else real_limit
            )
            self._set_status(
                state=self._scheduler.state.value,
                last_decision=result,
                last_command_result=result,
                last_command_time=datetime.now(UTC),
                current_limit_percent=confirmed_limit,
                real_dtu_limit_percent=confirmed_limit,
                calculated_limit_percent=None if success else decision.calculated_limit_percent,
                commanded_limit_percent=None if success else decision.applied_limit_percent,
                simulated_limit_percent=None,
                last_error=None if success else result,
                estimated_load_w=getattr(decision, "estimated_load_w", None),
                predictive_strategy=getattr(decision, "strategy", "cautious_correction"),
                policy_id=policy.policy_id,
                policy_reason=policy.reason,
            )
            if success:
                self._last_requested_limit_percent = decision.applied_limit_percent
                self._last_requested_limit_at = datetime.now(UTC)

    def _calculate_decision(
        self,
        snapshot: DecisionSnapshot,
        current_limit: int,
        target_grid_power_w: float,
        directive: DtuControlDirective = DtuControlDirective.NORMAL_REGULATION,
        requested_limit_percent: int | None = None,
    ) -> ControlDecision | PredictiveControlDecision:
        """Use prediction when PV telemetry is usable; otherwise retain safe fallback."""
        if directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM:
            limit = requested_limit_percent or 100
            return PredictiveControlDecision(
                grid_error_w=snapshot.grid_power_w - target_grid_power_w,
                estimated_load_w=(snapshot.dtu_power_w or 0.0) + snapshot.grid_power_w,
                calculated_limit_percent=limit,
                applied_limit_percent=limit,
                reason=DecisionReason.BATTERY_CAPACITY_RELEASE_APPLIED,
                strategy="battery_capacity_release",
                command_needed=limit != current_limit,
            )
        if snapshot.dtu_power_w is not None:
            return calculate_predictive_power_limit(
                grid_power_w=snapshot.grid_power_w,
                pv_power_w=snapshot.dtu_power_w,
                target_grid_power_w=target_grid_power_w,
                deadband_w=self._deadband_w,
                current_limit_percent=current_limit,
                installed_nominal_power_w=self._installed_nominal_power_w,
                predictive_error_threshold_w=self._predictive_error_threshold_w,
                fine_correction_step_percent=self._fine_correction_step_percent,
                minimum_limit_percent=2,
                maximum_limit_percent=100,
            )
        return calculate_power_limit(
            grid_power_w=snapshot.grid_power_w,
            target_grid_power_w=target_grid_power_w,
            deadband_w=self._deadband_w,
            current_limit_percent=current_limit,
            watts_per_percent=self.watts_per_percent,
            minimum_limit_percent=2,
            maximum_limit_percent=100,
            maximum_step_percent=self._fine_correction_step_percent,
        )

    async def _async_run_takeover(self) -> None:
        """Write one configured reference before normal Production decisions."""
        data = self._coordinator.data
        if data is None or not data.connected:
            self._set_status(
                state="Paused",
                last_decision="Takeover waiting for DTU connection",
                last_error="DTU is not connected",
                scheduler_inactive_reason="Takeover waiting for DTU connection",
            )
            return

        self.commands_sent += 1
        self._last_command_sequence = (self._last_command_sequence or 0) + 1
        context = self._context_analyzer.classify()
        self._trace_recorder.start_command(
            decision_id=self.decisions_evaluated + 1,
            command_id=self._last_command_sequence,
            controller_mode=ControllerMode.PRODUCTION.value,
            grid_power_w=None,
            grid_source_timestamp=None,
            pv_power_w=self._coordinator.data.active_power_w if self._coordinator.data else None,
            pv_source_timestamp=self._coordinator.data.last_success if self._coordinator.data else None,
            real_limit_before_percent=self._current_consistent_limit(require_fresh=False),
            calculated_limit_percent=self._takeover_limit_percent,
            requested_limit_percent=self._takeover_limit_percent,
            decision_reason="Takeover",
            strategy="takeover",
            target_grid_power_w=self._target_grid_power_w,
            deadband_w=self._deadband_w,
            policy_id="zero_injection",
            policy_reason="Configured zero-injection target",
            policy_confidence=1.0,
            policy_fallback_used=False,
            context_kind=context.kind.value,
            context_confidence=context.confidence,
            context_reason=context.reason,
            objective="establish_temporary_limit_reference",
            rationale="takeover",
            configuration=self._trace_configuration(),
        )
        success, result = await self._scheduler.async_execute(
            ControllerMode.PRODUCTION,
            lambda: self._coordinator.async_takeover_temporary_power_limits(
                self._takeover_limit_percent
            ),
        )
        if success:
            self.commands_succeeded += 1
            self._trace_recorder.finish_command(
                confirmed=True,
                confirmed_limit_percent=self._takeover_limit_percent,
                stabilization_delay_seconds=self._stabilization_delay_seconds,
            )
            self._takeover_pending = False
            self._set_status(
                state=self._scheduler.state.value,
                current_limit_percent=self._takeover_limit_percent,
                real_dtu_limit_percent=self._takeover_limit_percent,
                commanded_limit_percent=self._takeover_limit_percent,
                last_decision="Takeover confirmed",
                last_command_result=result,
                last_command_time=datetime.now(UTC),
                last_error=None,
                scheduler_inactive_reason=None,
            )
            self._last_requested_limit_percent = self._takeover_limit_percent
            self._last_requested_limit_at = datetime.now(UTC)
            return

        self.commands_failed += 1
        self._trace_recorder.finish_command(
            confirmed=False, confirmed_limit_percent=None, error=result
        )
        self._takeover_pending = False
        self._set_status(
            state=self._scheduler.state.value,
            last_decision="Takeover failed",
            last_command_result=result,
            last_command_time=datetime.now(UTC),
            last_error=result,
            scheduler_inactive_reason="Takeover failed",
        )

    def _current_consistent_limit(self, *, require_fresh: bool) -> int | None:
        data = self._coordinator.data
        if data is None or not data.connected:
            return None
        validation_mode = getattr(self._coordinator, "temporary_limit_validation_mode", None)
        compatibility_mode = getattr(validation_mode, "value", validation_mode) == "compatibility"
        if (
            require_fresh
            and not compatibility_mode
            and not self._coordinator.temporary_limits_ready
        ):
            return None
        effective_limit = getattr(self._coordinator, "effective_temporary_limit", None)
        if effective_limit is not None:
            return effective_limit
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
            self._measurement_sync_diagnostics = MeasurementSyncDiagnostics(
                grid_source_timestamp=grid_timestamp,
                tolerance_seconds=MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS,
                reason=(
                    "Grid timestamp unavailable"
                    if grid_timestamp is None
                    else "DTU telemetry unavailable"
                ),
            )
            return None
        now = datetime.now(UTC)
        telemetry_timestamp = getattr(self._coordinator, "telemetry_timestamp", None)
        dtu_timestamp = (
            telemetry_timestamp("active_power_w")
            if callable(telemetry_timestamp)
            else None
        ) or getattr(data, "last_success", None) or now
        limits_timestamp = getattr(self._coordinator, "temporary_limits_timestamp", None)
        if callable(limits_timestamp):
            limits_timestamp = limits_timestamp()
        if limits_timestamp is None:
            limits_timestamp = dtu_timestamp
        if dtu_timestamp is None or limits_timestamp is None:
            self._measurement_sync_diagnostics = MeasurementSyncDiagnostics(
                grid_source_timestamp=grid_timestamp,
                pv_source_timestamp=dtu_timestamp,
                tolerance_seconds=MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS,
                reason="PV timestamp unavailable",
            )
            return None
        grid_age = max(0.0, (now - grid_timestamp).total_seconds())
        pv_age = max(0.0, (now - dtu_timestamp).total_seconds())
        difference = abs((grid_timestamp - dtu_timestamp).total_seconds())
        reason = None
        if grid_age > GRID_MEASUREMENT_MAX_AGE_SECONDS:
            reason = "Grid measurement is older than the allowed age"
        elif pv_age > DTU_MEASUREMENT_MAX_AGE_SECONDS:
            reason = "PV measurement is older than the allowed age"
        elif difference > MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS:
            reason = "Grid/PV timestamp difference exceeds the allowed tolerance"
        self._measurement_sync_diagnostics = MeasurementSyncDiagnostics(
            grid_source_timestamp=grid_timestamp,
            pv_source_timestamp=dtu_timestamp,
            grid_age_seconds=grid_age,
            pv_age_seconds=pv_age,
            difference_seconds=difference,
            tolerance_seconds=MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS,
            reason=reason,
        )
        if reason is not None:
            return None
        current_limit = self._current_consistent_limit(require_fresh=True)
        if current_limit is None:
            return None
        return DecisionSnapshot(
            grid_power_w=grid_power_w,
            grid_power_timestamp=grid_timestamp,
            dtu_power_w=data.active_power_w,
            dtu_power_timestamp=dtu_timestamp,
            temporary_limits=(current_limit, current_limit, current_limit),
            temporary_limits_timestamp=limits_timestamp,
            target_power_w=self._target_grid_power_w,
            created_at=now,
        )

    def _record_dtu_limit_power_observation(
        self, snapshot: DecisionSnapshot
    ) -> dict[str, Any]:
        """Persist one already-acquired limit/power snapshot for diagnostics."""
        observation = self._build_dtu_limit_power_observation(snapshot)
        self._last_dtu_limit_observation = observation
        return observation

    def _build_dtu_limit_power_observation(
        self,
        snapshot: DecisionSnapshot,
        *,
        requested_limit_percent: int | None = None,
    ) -> dict[str, Any]:
        """Describe existing DTU evidence without a read, write or scheduler change."""
        data = self._coordinator.data
        requested_limit = (
            requested_limit_percent
            if requested_limit_percent is not None
            else self._last_requested_limit_percent
        )
        requested_at = (
            snapshot.created_at
            if requested_limit_percent is not None
            else self._last_requested_limit_at
        )
        confirmation_timestamp = getattr(
            self._coordinator, "temporary_limits_confirmation_timestamp", None
        )
        if callable(confirmation_timestamp):
            confirmation_timestamp = confirmation_timestamp()
        if confirmation_timestamp is None:
            confirmation_timestamp = snapshot.temporary_limits_timestamp
        confirmation_age = max(
            0.0, (snapshot.created_at - confirmation_timestamp).total_seconds()
        )
        remaining_seconds = self._scheduler.remaining_seconds(snapshot.created_at)
        return {
            "observation_timestamp_utc": snapshot.created_at.isoformat(),
            "installed_nominal_power_w": self._installed_nominal_power_w,
            "requested_limit_percent": requested_limit,
            "requested_limit_timestamp_utc": (
                requested_at.isoformat() if requested_at else None
            ),
            "theoretical_max_power_w": (
                self._installed_nominal_power_w * requested_limit / 100
                if requested_limit is not None
                else None
            ),
            "active_power_w": snapshot.dtu_power_w,
            "temporary_port_limits_percent": {
                "port_1": (
                    data.port_1_temporary_power_limit_percent if data else None
                ),
                "port_2": (
                    data.port_2_temporary_power_limit_percent if data else None
                ),
                "port_3": (
                    data.port_3_temporary_power_limit_percent if data else None
                ),
            },
            "limits_confirmation_timestamp_utc": confirmation_timestamp.isoformat(),
            "limits_confirmation_age_seconds": confirmation_age,
            "limit_confirmation_source": getattr(
                self._coordinator, "temporary_limit_source", "unknown"
            ),
            "scheduler_state": self._scheduler.state.value,
            "scheduler_stabilizing": remaining_seconds > 0,
            "scheduler_remaining_seconds": remaining_seconds,
        }

    def _requires_new_decision(self, snapshot: DecisionSnapshot) -> bool:
        """Return whether input changed enough to justify a new decision.

        Timestamp-only refreshes and small sensor noise are deliberately ignored.
        A configuration or mode change is represented by the configuration
        generation and always gets one fresh evaluation.
        """
        if (
            self._mode is ControllerMode.PRODUCTION
            and self._energy_policy_engine.battery_priority_input_changed()
        ):
            return True
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
            >= INTERNAL_SIMULATION_DIAGNOSTIC_REFRESH_SECONDS
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
            self._trace_recorder.record_decision()
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

    def _record_persistent_history(
        self,
        event_type: HistoryEventType,
        payload: dict[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """Pass a fact to optional storage; it has no control-plane authority."""
        if self._persistent_history_recorder is not None:
            self._persistent_history_recorder.record(event_type, payload, timestamp=timestamp)

    def _record_periodic_history(
        self, snapshot: DecisionSnapshot, current_limit: int
    ) -> None:
        """Request a deduplicated context sample from an existing controller tick."""
        if self._persistent_history_recorder is not None:
            self._persistent_history_recorder.record_periodic_if_due(
                self._history_payload(snapshot, current_limit, None, None),
                timestamp=snapshot.created_at,
            )
            self._record_history_battery_transition_if_changed(snapshot, current_limit)

    def _record_history_battery_transition_if_changed(
        self, snapshot: DecisionSnapshot, current_limit: int
    ) -> None:
        """Persist a material cached battery transition without requesting data."""
        energy = self._coordinator.energy_manager.snapshot()
        battery = energy.resources[0] if energy.resources else None
        signature = (
            battery.health.value if battery else None,
            self._history_power_bucket(battery.charge_power_w) if battery else None,
            self._history_power_bucket(battery.discharge_power_w) if battery else None,
            round(battery.soc_percent) if battery and battery.soc_percent is not None else None,
            self._history_power_bucket(battery.max_charge_power_w) if battery else None,
            self._history_power_bucket(battery.remaining_charge_power_w) if battery else None,
        )
        if signature == self._last_history_battery_signature:
            return
        self._last_history_battery_signature = signature
        self._record_persistent_history(
            HistoryEventType.TRANSITION,
            self._history_payload(snapshot, current_limit, None, None),
            timestamp=snapshot.created_at,
        )

    @staticmethod
    def _history_power_bucket(value: float | None) -> int | None:
        """Avoid recording insignificant battery-power noise as transitions."""
        return round(value / 25) if value is not None else None

    def _record_history_transition_if_changed(
        self, snapshot: DecisionSnapshot, current_limit: int, policy: Any
    ) -> None:
        """Persist only meaningful strategy/battery state changes."""
        if self._persistent_history_recorder is None:
            return
        energy = self._coordinator.energy_manager.snapshot()
        battery = energy.resources[0] if energy.resources else None
        signature = (
            self._mode.value,
            policy.policy_id,
            getattr(policy.dtu_control_directive, "value", None),
            getattr(policy.reason_code, "value", None),
            battery.health.value if battery else None,
            battery.charge_power_w if battery else None,
            battery.discharge_power_w if battery else None,
            battery.max_charge_power_w if battery else None,
        )
        if signature == self._last_history_transition_signature:
            return
        self._last_history_transition_signature = signature
        self._record_persistent_history(
            HistoryEventType.TRANSITION,
            self._history_payload(snapshot, current_limit, None, policy),
            timestamp=snapshot.created_at,
        )

    def _history_payload(
        self,
        snapshot: DecisionSnapshot,
        current_limit: int,
        decision: ControlDecision | PredictiveControlDecision | None,
        policy: Any | None,
        *,
        command_result: str | None = None,
        command_confirmed: bool | None = None,
    ) -> dict[str, Any]:
        """Build a primitive, coherent passive history snapshot from cached data."""
        energy = self._coordinator.energy_manager.snapshot()
        battery = energy.resources[0] if energy.resources else None
        limit_observation = self._build_dtu_limit_power_observation(snapshot)
        return {
            "controller_mode": self._mode.value,
            "scheduler_state": self._scheduler.state.value,
            "scheduler_waiting_seconds": self._scheduler.remaining_seconds(),
            "reason_code": getattr(getattr(policy, "reason_code", None), "value", None),
            "policy_id": getattr(policy, "policy_id", None),
            "dtu_control_directive": getattr(
                getattr(policy, "dtu_control_directive", None), "value", None
            ),
            "fallback_used": getattr(policy, "fallback_used", None),
            "real_dtu_limit_before_percent": current_limit,
            "last_confirmed_temporary_limit_percent": getattr(
                self._coordinator, "last_confirmed_temporary_limit", None
            ),
            "temporary_limit_source": getattr(
                self._coordinator, "temporary_limit_source", "unknown"
            ),
            "calculated_limit_percent": (
                decision.calculated_limit_percent if decision else None
            ),
            "requested_limit_percent": decision.applied_limit_percent if decision else None,
            "confirmed_limit_percent": (
                decision.applied_limit_percent if command_confirmed else None
            ),
            "command_result": command_result,
            "command_confirmed": command_confirmed,
            "grid_power_w": snapshot.grid_power_w,
            "grid_source_timestamp": snapshot.grid_power_timestamp,
            "pv_power_w": snapshot.dtu_power_w,
            "pv_source_timestamp": snapshot.dtu_power_timestamp,
            "dtu_active_power_w": snapshot.dtu_power_w,
            "temporary_limit_port_1_percent": snapshot.temporary_limits[0],
            "temporary_limit_port_2_percent": snapshot.temporary_limits[1],
            "temporary_limit_port_3_percent": snapshot.temporary_limits[2],
            "temporary_limits_source_timestamp": snapshot.temporary_limits_timestamp,
            "target_grid_power_w": snapshot.target_power_w,
            "installed_nominal_power_w": self._installed_nominal_power_w,
            # This is OpenEMS' configured linear reference only.  It is
            # recorded for field correlation and is not evidence that the DTU
            # firmware applies the same relationship to these registers.
            "openems_theoretical_max_power_at_real_limit_w": (
                self._installed_nominal_power_w * current_limit / 100
            ),
            "dtu_limit_power_observation": limit_observation,
            "battery": {
                "resource_id": battery.resource_id if battery else None,
                "health": battery.health.value if battery else None,
                "soc_percent": battery.soc_percent if battery else None,
                "charge_power_w": battery.charge_power_w if battery else None,
                "discharge_power_w": battery.discharge_power_w if battery else None,
                "max_charge_power_w": battery.max_charge_power_w if battery else None,
                "remaining_charge_power_w": battery.remaining_charge_power_w if battery else None,
                "data_age_seconds": battery.data_age_seconds if battery else None,
                "source_freshness": battery.source_freshness if battery else {},
            },
            "battery_count": energy.battery_count,
            "total_remaining_charge_power_w": energy.total_remaining_charge_power_w,
            "battery_aggregate_coverage": energy.remaining_charge_coverage.status,
        }

    def _set_status(self, **changes: object) -> None:
        updated = replace(self._status, **{**changes, "mode": self._mode})
        if updated == self._status:
            return
        self._status = updated
        self._coordinator.async_update_listeners()

    def _rotate_trace_session(self, reason: str) -> None:
        """Segment passive RC4 metrics after a material Production change."""
        if self._mode is ControllerMode.PRODUCTION:
            self._trace_recorder.rotate_session(
                reason=reason, configuration=self._trace_configuration()
            )

    def _trace_configuration(self) -> dict[str, int | float | str]:
        """Return primitive decision inputs for the passive replay-ready trace."""
        return {
            "target_grid_power_w": self._target_grid_power_w,
            "deadband_w": self._deadband_w,
            "installed_nominal_power_w": self._installed_nominal_power_w,
            "watts_per_percent": self.watts_per_percent,
            "fine_correction_step_percent": self._fine_correction_step_percent,
            "predictive_error_threshold_w": self._predictive_error_threshold_w,
            "stabilization_delay_seconds": self._stabilization_delay_seconds,
            "controller_mode": self._mode.value,
        }
