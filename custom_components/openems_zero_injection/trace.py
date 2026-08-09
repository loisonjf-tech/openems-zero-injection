"""Passive, bounded and replay-ready command tracing for OpenEMS.

The recorder is intentionally an observer.  It has no Home Assistant listener,
timer, Modbus client, scheduler lock, retry loop or persistent storage.  The
controller and coordinator feed it facts they have already obtained during
their normal work.  Detailed timelines are bounded, while session aggregates
are accumulated separately so a long-running session is never truncated by the
100-command diagnostic buffer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median
import time
from typing import Any
from uuid import uuid4


# Version 4 adds the exact cached SolarFlow inputs consumed by each energy
# strategy evaluation. It is additive, primitive-only and replay-safe.
TRACE_SCHEMA_VERSION = 4
TRACE_BUFFER_SIZE = 100
TRACE_MAX_EVENTS_PER_COMMAND = 64
TRACE_OBSERVATION_WINDOW_SECONDS = 60.0
TRACE_MAX_SAMPLE_GAP_SECONDS = 12.0
TRACE_SIGNIFICANT_PV_CHANGE_W = 50.0
TRACE_METRIC_RESERVOIR_SIZE = 512


class TraceMode(StrEnum):
    """Recorder retention mode implemented by this build."""

    NORMAL = "normal"


class CommandOutcome(StrEnum):
    """Lifecycle and observed effectiveness of one command."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"
    INDETERMINATE = "indeterminate"


class DataQuality(StrEnum):
    """How safely post-command observations can be interpreted."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    GAPPED = "gapped"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class BatteryStrategyInputTrace:
    """Battery facts consumed by one already-evaluated policy decision."""

    resource_id: str
    source_entity_id: str | None
    raw_directional_power_value: str | None
    raw_directional_power_unit: str | None
    directional_power_w: float | None
    charge_power_w: float | None
    discharge_power_w: float | None
    health: str
    directional_freshness: str | None
    directional_source_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class StrategyComparisonTrace:
    """One passive Battery Priority comparison from an existing snapshot."""

    timestamp_utc: datetime
    monotonic_ms: float
    input_snapshot_id: str
    controller_mode: str
    effective_target_grid_power_w: float
    candidate_target_grid_power_w: float
    target_delta_w: float
    candidate_expected_storage_gain_w: float
    reason_code: str
    fallback_used: bool
    eligible_resource_ids: tuple[str, ...]
    dtu_control_directive: str = "normal_regulation"
    max_charge_power_w: float | None = None
    observed_charge_power_w: float | None = None
    observed_discharge_power_w: float | None = None
    remaining_charge_power_w: float | None = None
    battery_inputs: tuple[BatteryStrategyInputTrace, ...] = ()


@dataclass(frozen=True, slots=True)
class EnergyStrategyTickTrace:
    """One valid Controller tick, whether or not it required a decision."""

    timestamp_utc: datetime
    monotonic_ms: float
    input_snapshot_id: str
    controller_mode: str
    decision_evaluated: bool
    decision_timestamp: datetime | None
    decision_input_snapshot_id: str | None
    reason_code: str | None
    dtu_control_directive: str | None
    battery_inputs: tuple[BatteryStrategyInputTrace, ...] = ()


@dataclass(slots=True)
class TraceEvent:
    """One timeline event with source and receipt times kept separate."""

    event_type: str
    timestamp_utc: datetime
    monotonic_ms: float
    source_timestamp: datetime | None
    observed_timestamp: datetime
    result: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return only serializable primitives for diagnostics or future replay."""
        return _to_primitives(asdict(self))


@dataclass(slots=True)
class CommandTrace:
    """One replay-compatible command timeline, retained only in a bounded ring."""

    trace_id: str
    session_id: str
    decision_id: int | None
    command_id: int
    controller_mode: str
    timestamp_utc: datetime
    monotonic_ms: float
    grid_power_w: float | None
    grid_source_timestamp: datetime | None
    grid_observed_timestamp: datetime
    pv_power_w: float | None
    pv_source_timestamp: datetime | None
    pv_observed_timestamp: datetime
    real_limit_before_percent: int | None
    calculated_limit_percent: int | None
    requested_limit_percent: int
    decision_reason: str | None
    strategy: str | None
    target_grid_power_w: float
    deadband_w: float
    schema_version: int = TRACE_SCHEMA_VERSION
    algorithm_version: str = "build004_rc4"
    policy_id: str | None = None
    policy_version: str | None = None
    policy_reason: str | None = None
    policy_confidence: float | None = None
    policy_fallback_used: bool | None = None
    context_kind: str | None = None
    context_confidence: float | None = None
    context_reason: str | None = None
    objective: str | None = None
    rationale: str | None = None
    pre_decision_inputs: dict[str, Any] = field(default_factory=dict)
    events: deque[TraceEvent] = field(
        default_factory=lambda: deque(maxlen=TRACE_MAX_EVENTS_PER_COMMAND)
    )
    port_results: dict[int, str] = field(default_factory=dict)
    confirmed_limit_percent: int | None = None
    write_started_monotonic_ms: float | None = None
    write_finished_monotonic_ms: float | None = None
    outcome: CommandOutcome = CommandOutcome.PENDING
    data_quality: DataQuality = DataQuality.INSUFFICIENT
    first_pv_change_latency_ms: float | None = None
    return_to_target_latency_ms: float | None = None
    final_grid_error_w: float | None = None
    overshoot_detected: bool = False
    oscillation_suspected: bool = False
    post_command_evaluation: dict[str, Any] = field(default_factory=dict)
    _finished_accounted: bool = False
    _evaluation_accounted: bool = False

    @property
    def modbus_duration_ms(self) -> float | None:
        """Return whole three-port write duration, if the transaction ended."""
        if self.write_started_monotonic_ms is None or self.write_finished_monotonic_ms is None:
            return None
        return max(0.0, self.write_finished_monotonic_ms - self.write_started_monotonic_ms)

    @property
    def command_amplitude_percent(self) -> int | None:
        """Return requested variation from the known pre-command limit."""
        if self.real_limit_before_percent is None:
            return None
        return abs(self.requested_limit_percent - self.real_limit_before_percent)

    def as_dict(self) -> dict[str, Any]:
        """Return a primitive-only detailed timeline suitable for later replay."""
        result = asdict(self)
        result.pop("_finished_accounted", None)
        result.pop("_evaluation_accounted", None)
        result["events"] = [event.as_dict() for event in self.events]
        result["modbus_duration_ms"] = self.modbus_duration_ms
        result["command_amplitude_percent"] = self.command_amplitude_percent
        return _to_primitives(result)


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    """Aggregate metrics for the complete session, not only retained traces."""

    decisions: int
    commands_started: int
    commands_confirmed: int
    commands_failed: int
    commands_effective: int
    commands_ineffective: int
    commands_indeterminate: int
    retained_command_count: int
    detailed_traces_truncated: bool
    data_coverage_percent: float | None
    average_modbus_duration_ms: float | None
    median_modbus_duration_ms: float | None
    average_energy_response_ms: float | None
    median_energy_response_ms: float | None
    maximum_energy_response_ms: float | None
    weighted_time_in_tolerance_percent: float | None
    average_absolute_error_w: float | None
    median_absolute_error_w: float | None
    average_command_amplitude_percent: float | None
    maximum_command_amplitude_percent: int | None
    overshoots: int
    suspected_oscillations: int
    metric_sample_size: int


@dataclass(frozen=True, slots=True)
class SessionReport:
    """Immutable session summary with a versioned replay-compatible schema."""

    session_id: str
    started_at: datetime
    ended_at: datetime
    end_reason: str
    metrics: SessionMetrics
    schema_version: int = TRACE_SCHEMA_VERSION
    algorithm_version: str = "build004_rc4"
    configuration: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """Return real wall-clock duration of the session."""
        return max(0.0, (self.ended_at - self.started_at).total_seconds())

    def as_dict(self) -> dict[str, Any]:
        return _to_primitives(asdict(self) | {"duration_seconds": self.duration_seconds})


@dataclass(slots=True)
class _MetricAccumulator:
    """Exact counters plus bounded numeric reservoirs for session statistics."""

    commands_started: int = 0
    commands_confirmed: int = 0
    commands_failed: int = 0
    commands_effective: int = 0
    commands_ineffective: int = 0
    commands_indeterminate: int = 0
    overshoots: int = 0
    suspected_oscillations: int = 0
    modbus_total_ms: float = 0.0
    modbus_count: int = 0
    response_total_ms: float = 0.0
    response_count: int = 0
    response_max_ms: float | None = None
    error_total_w: float = 0.0
    error_count: int = 0
    amplitude_total_percent: float = 0.0
    amplitude_count: int = 0
    amplitude_max_percent: int | None = None
    modbus_samples: deque[float] = field(
        default_factory=lambda: deque(maxlen=TRACE_METRIC_RESERVOIR_SIZE)
    )
    response_samples: deque[float] = field(
        default_factory=lambda: deque(maxlen=TRACE_METRIC_RESERVOIR_SIZE)
    )
    error_samples: deque[float] = field(
        default_factory=lambda: deque(maxlen=TRACE_METRIC_RESERVOIR_SIZE)
    )
    amplitude_samples: deque[float] = field(
        default_factory=lambda: deque(maxlen=TRACE_METRIC_RESERVOIR_SIZE)
    )
    first_sample: TraceEvent | None = None
    previous_sample: TraceEvent | None = None
    covered_ms: float = 0.0
    tolerance_ms: float = 0.0
    target_grid_power_w: float | None = None
    deadband_w: float | None = None

    def record_sample(
        self, sample: TraceEvent, *, target_grid_power_w: float | None, deadband_w: float | None
    ) -> None:
        """Add one existing snapshot using interval weighting, without polling."""
        if self.first_sample is None:
            self.first_sample = sample
        if self.target_grid_power_w is None:
            self.target_grid_power_w = target_grid_power_w
            self.deadband_w = deadband_w
        previous = self.previous_sample
        if previous is not None:
            interval = sample.monotonic_ms - previous.monotonic_ms
            if 0 < interval <= TRACE_MAX_SAMPLE_GAP_SECONDS * 1000:
                self.covered_ms += interval
                target = self.target_grid_power_w
                deadband = self.deadband_w
                if target is not None and deadband is not None:
                    previous_error = float(previous.details["grid_power_w"]) - target
                    current_error = float(sample.details["grid_power_w"]) - target
                    if abs(previous_error) <= deadband and abs(current_error) <= deadband:
                        self.tolerance_ms += interval
        self.previous_sample = sample

    def record_finished(self, trace: CommandTrace) -> None:
        """Account a command write once, independently of raw trace retention."""
        if trace._finished_accounted:
            return
        trace._finished_accounted = True
        if trace.outcome is CommandOutcome.FAILED:
            self.commands_failed += 1
        else:
            self.commands_confirmed += 1
        if (duration := trace.modbus_duration_ms) is not None:
            self.modbus_count += 1
            self.modbus_total_ms += duration
            self.modbus_samples.append(duration)
        if (amplitude := trace.command_amplitude_percent) is not None:
            self.amplitude_count += 1
            self.amplitude_total_percent += amplitude
            self.amplitude_samples.append(float(amplitude))
            self.amplitude_max_percent = max(self.amplitude_max_percent or amplitude, amplitude)

    def record_evaluation(self, trace: CommandTrace) -> None:
        """Account a final effectiveness assessment once."""
        if trace._evaluation_accounted or trace.outcome not in {
            CommandOutcome.EFFECTIVE,
            CommandOutcome.INEFFECTIVE,
            CommandOutcome.INDETERMINATE,
        }:
            return
        trace._evaluation_accounted = True
        if trace.outcome is CommandOutcome.EFFECTIVE:
            self.commands_effective += 1
        elif trace.outcome is CommandOutcome.INEFFECTIVE:
            self.commands_ineffective += 1
        else:
            self.commands_indeterminate += 1
        if (response := trace.first_pv_change_latency_ms) is not None:
            self.response_count += 1
            self.response_total_ms += response
            self.response_samples.append(response)
            self.response_max_ms = max(self.response_max_ms or response, response)
        if (error := trace.final_grid_error_w) is not None:
            absolute_error = abs(error)
            self.error_count += 1
            self.error_total_w += absolute_error
            self.error_samples.append(absolute_error)
        self.overshoots += int(trace.overshoot_detected)
        self.suspected_oscillations += int(trace.oscillation_suspected)


@dataclass(slots=True)
class _ActiveSession:
    """Private mutable state for one production session."""

    session_id: str
    started_at: datetime
    started_monotonic_ms: float
    decisions: int = 0
    samples: deque[TraceEvent] = field(
        default_factory=lambda: deque(maxlen=TRACE_BUFFER_SIZE * 2)
    )
    metrics: _MetricAccumulator = field(default_factory=_MetricAccumulator)
    configuration: dict[str, Any] = field(default_factory=dict)


class TraceRecorder:
    """Passive bounded black box for commands, timelines and session metrics."""

    def __init__(self, *, max_traces: int = TRACE_BUFFER_SIZE) -> None:
        if max_traces < 1:
            raise ValueError("max_traces must be positive")
        self._mode = TraceMode.NORMAL
        self._max_traces = max_traces
        self._traces: deque[CommandTrace] = deque(maxlen=max_traces)
        self._strategy_comparisons: deque[StrategyComparisonTrace] = deque(
            maxlen=max_traces
        )
        self._energy_strategy_ticks: deque[EnergyStrategyTickTrace] = deque(
            maxlen=max_traces
        )
        self._active: _ActiveSession | None = None
        self._last_report: SessionReport | None = None

    @property
    def mode(self) -> TraceMode:
        return self._mode

    @property
    def session_active(self) -> bool:
        return self._active is not None

    @property
    def session_started_at(self) -> datetime | None:
        return self._active.started_at if self._active else None

    @property
    def last_report(self) -> SessionReport | None:
        return self._last_report

    @property
    def traces(self) -> tuple[CommandTrace, ...]:
        return tuple(self._traces)

    @property
    def strategy_comparisons(self) -> tuple[StrategyComparisonTrace, ...]:
        """Return the bounded comparison history without creating I/O."""
        return tuple(self._strategy_comparisons)

    @property
    def energy_strategy_ticks(self) -> tuple[EnergyStrategyTickTrace, ...]:
        """Return a bounded chronology of existing Controller tick facts."""
        return tuple(self._energy_strategy_ticks)

    def record_energy_strategy_tick(
        self,
        *,
        input_snapshot_id: str,
        controller_mode: str,
        decision_evaluated: bool,
        decision_timestamp: datetime | None,
        decision_input_snapshot_id: str | None,
        reason_code: str | None,
        dtu_control_directive: str | None,
        battery_inputs: tuple[BatteryStrategyInputTrace, ...] = (),
        tick_timestamp: datetime | None = None,
    ) -> None:
        """Append cached decision evidence without reading any source."""
        self._energy_strategy_ticks.append(
            EnergyStrategyTickTrace(
                timestamp_utc=tick_timestamp or _utc_now(),
                monotonic_ms=_monotonic_ms(),
                input_snapshot_id=input_snapshot_id,
                controller_mode=controller_mode,
                decision_evaluated=decision_evaluated,
                decision_timestamp=decision_timestamp,
                decision_input_snapshot_id=decision_input_snapshot_id,
                reason_code=reason_code,
                dtu_control_directive=dtu_control_directive,
                battery_inputs=battery_inputs,
            )
        )

    def record_strategy_comparison(
        self,
        *,
        input_snapshot_id: str,
        controller_mode: str,
        effective_target_grid_power_w: float,
        candidate_target_grid_power_w: float,
        target_delta_w: float,
        candidate_expected_storage_gain_w: float,
        reason_code: str,
        fallback_used: bool,
        eligible_resource_ids: tuple[str, ...],
        dtu_control_directive: str = "normal_regulation",
        max_charge_power_w: float | None = None,
        observed_charge_power_w: float | None = None,
        observed_discharge_power_w: float | None = None,
        remaining_charge_power_w: float | None = None,
        battery_inputs: tuple[BatteryStrategyInputTrace, ...] = (),
        decision_timestamp: datetime | None = None,
    ) -> None:
        """Record a Simulation-only policy comparison from existing data."""
        self._strategy_comparisons.append(
            StrategyComparisonTrace(
                timestamp_utc=decision_timestamp or _utc_now(),
                monotonic_ms=_monotonic_ms(),
                input_snapshot_id=input_snapshot_id,
                controller_mode=controller_mode,
                effective_target_grid_power_w=effective_target_grid_power_w,
                candidate_target_grid_power_w=candidate_target_grid_power_w,
                target_delta_w=target_delta_w,
                candidate_expected_storage_gain_w=candidate_expected_storage_gain_w,
                reason_code=reason_code,
                fallback_used=fallback_used,
                eligible_resource_ids=eligible_resource_ids,
                dtu_control_directive=dtu_control_directive,
                max_charge_power_w=max_charge_power_w,
                observed_charge_power_w=observed_charge_power_w,
                observed_discharge_power_w=observed_discharge_power_w,
                remaining_charge_power_w=remaining_charge_power_w,
                battery_inputs=battery_inputs,
            )
        )

    def start_session(self, *, reason: str, configuration: dict[str, Any] | None = None) -> None:
        """Start a production session; close an earlier one first if necessary."""
        if self._active is not None:
            self.stop_session(reason=f"restarted: {reason}")
        self._active = _ActiveSession(
            session_id=uuid4().hex,
            started_at=_utc_now(),
            started_monotonic_ms=_monotonic_ms(),
            configuration=_primitive_mapping(configuration or {}),
        )

    def stop_session(self, *, reason: str) -> SessionReport | None:
        """Close the active session without touching controller state or I/O."""
        active = self._active
        if active is None:
            return None
        self._finalize_pending(active)
        report = SessionReport(
            session_id=active.session_id,
            started_at=active.started_at,
            ended_at=_utc_now(),
            end_reason=reason,
            metrics=self._build_metrics(active),
            configuration=active.configuration,
        )
        self._last_report = report
        self._active = None
        return report

    def rotate_session(self, *, reason: str, configuration: dict[str, Any] | None = None) -> None:
        """Segment a running session after a major configuration change."""
        if self._active is None:
            return
        self.stop_session(reason=reason)
        self.start_session(reason=reason, configuration=configuration)

    def record_decision(self) -> None:
        """Count a real controller decision without changing its outcome."""
        if self._active is not None:
            self._active.decisions += 1

    def start_command(
        self,
        *,
        decision_id: int | None,
        command_id: int,
        controller_mode: str,
        grid_power_w: float | None,
        grid_source_timestamp: datetime | None,
        pv_power_w: float | None,
        pv_source_timestamp: datetime | None,
        real_limit_before_percent: int | None,
        calculated_limit_percent: int | None,
        requested_limit_percent: int,
        decision_reason: str | None,
        strategy: str | None,
        target_grid_power_w: float,
        deadband_w: float,
        policy_id: str | None = None,
        policy_reason: str | None = None,
        policy_confidence: float | None = None,
        policy_fallback_used: bool | None = None,
        context_kind: str | None = None,
        context_confidence: float | None = None,
        context_reason: str | None = None,
        objective: str | None = None,
        rationale: str | None = None,
        configuration: dict[str, Any] | None = None,
        dtu_limit_observation: dict[str, Any] | None = None,
    ) -> CommandTrace | None:
        """Create a timeline for a command that was already selected normally."""
        active = self._active
        if active is None:
            return None
        now = _utc_now()
        inputs = {
            "grid_power_w": grid_power_w,
            "grid_source_timestamp": grid_source_timestamp,
            "pv_power_w": pv_power_w,
            "pv_source_timestamp": pv_source_timestamp,
            "real_limit_before_percent": real_limit_before_percent,
            "calculated_limit_percent": calculated_limit_percent,
            "requested_limit_percent": requested_limit_percent,
            "target_grid_power_w": target_grid_power_w,
            "deadband_w": deadband_w,
            "dtu_limit_observation": dtu_limit_observation or {},
        }
        trace = CommandTrace(
            trace_id=uuid4().hex,
            session_id=active.session_id,
            decision_id=decision_id,
            command_id=command_id,
            controller_mode=controller_mode,
            timestamp_utc=now,
            monotonic_ms=_monotonic_ms(),
            grid_power_w=grid_power_w,
            grid_source_timestamp=grid_source_timestamp,
            grid_observed_timestamp=now,
            pv_power_w=pv_power_w,
            pv_source_timestamp=pv_source_timestamp,
            pv_observed_timestamp=now,
            real_limit_before_percent=real_limit_before_percent,
            calculated_limit_percent=calculated_limit_percent,
            requested_limit_percent=requested_limit_percent,
            decision_reason=decision_reason,
            strategy=strategy,
            target_grid_power_w=target_grid_power_w,
            deadband_w=deadband_w,
            policy_id=policy_id,
            policy_reason=policy_reason,
            policy_confidence=policy_confidence,
            policy_fallback_used=policy_fallback_used,
            context_kind=context_kind,
            context_confidence=context_confidence,
            context_reason=context_reason,
            objective=objective or "target_grid_power",
            rationale=rationale or decision_reason,
            pre_decision_inputs=_primitive_mapping(inputs),
        )
        trace.events.append(
            _event(
                "decision_created",
                source_timestamp=grid_source_timestamp,
                result="command_requested",
                details={
                    "decision_reason": decision_reason,
                    "strategy": strategy,
                    "policy_id": policy_id,
                    "context_kind": context_kind,
                    "objective": trace.objective,
                },
            )
        )
        self._append_trace(trace, active)
        active.metrics.commands_started += 1
        if not active.configuration and configuration:
            active.configuration = _primitive_mapping(configuration)
        return trace

    def record_modbus_started(self) -> None:
        """Mark the start of the existing three-port Modbus transaction."""
        trace = self._pending_trace()
        if trace is None:
            return
        event = _event("modbus_write_started")
        trace.write_started_monotonic_ms = event.monotonic_ms
        trace.events.append(event)

    def record_port_result(
        self,
        *,
        port: int,
        result: str,
        address: int | None = None,
        error: str | None = None,
    ) -> None:
        """Record an existing port result; this method never emits a frame."""
        trace = self._pending_trace()
        if trace is None:
            return
        trace.port_results[port] = result
        trace.events.append(
            _event(
                "modbus_port_result",
                result=result,
                details={"port": port, "address": address, "error": error},
            )
        )

    def finish_modbus(self, *, result: str, error: str | None = None) -> None:
        """Mark completion of the existing coordinator write sequence."""
        trace = self._pending_trace()
        if trace is None:
            return
        event = _event("modbus_write_finished", result=result, details={"error": error})
        trace.write_finished_monotonic_ms = event.monotonic_ms
        trace.events.append(event)

    def finish_command(
        self,
        *,
        confirmed: bool,
        confirmed_limit_percent: int | None,
        error: str | None = None,
        stabilization_delay_seconds: int | None = None,
    ) -> None:
        """Store the normal scheduler result after the write callback returns."""
        trace = self._pending_trace()
        active = self._active
        if trace is None or active is None:
            return
        trace.confirmed_limit_percent = confirmed_limit_percent if confirmed else None
        trace.outcome = CommandOutcome.CONFIRMED if confirmed else CommandOutcome.FAILED
        trace.events.append(
            _event(
                "command_confirmation",
                result=trace.outcome.value,
                details={"confirmed_limit_percent": trace.confirmed_limit_percent, "error": error},
            )
        )
        if confirmed and stabilization_delay_seconds is not None:
            trace.events.append(
                _event(
                    "stabilization_started",
                    result="waiting",
                    details={"stabilization_delay_seconds": stabilization_delay_seconds},
                )
            )
        active.metrics.record_finished(trace)

    def observe_measurement(
        self,
        *,
        grid_power_w: float,
        grid_source_timestamp: datetime,
        pv_power_w: float | None,
        pv_source_timestamp: datetime | None,
        target_grid_power_w: float | None = None,
        deadband_w: float | None = None,
        dtu_limit_observation: dict[str, Any] | None = None,
    ) -> None:
        """Observe a coherent snapshot already built by the controller."""
        active = self._active
        if active is None:
            return
        observation = _event(
            "measurement_observed",
            source_timestamp=grid_source_timestamp,
            details={
                "grid_power_w": grid_power_w,
                "pv_power_w": pv_power_w,
                "pv_source_timestamp": pv_source_timestamp,
                "dtu_limit_observation": dtu_limit_observation or {},
            },
        )
        active.samples.append(observation)
        if target_grid_power_w is None:
            for trace in reversed(self._traces):
                if trace.session_id == active.session_id:
                    target_grid_power_w = trace.target_grid_power_w
                    deadband_w = trace.deadband_w
                    break
        active.metrics.record_sample(
            observation,
            target_grid_power_w=target_grid_power_w,
            deadband_w=deadband_w,
        )
        for trace in self._traces:
            if trace.session_id != active.session_id or trace.outcome not in {
                CommandOutcome.CONFIRMED,
                CommandOutcome.PENDING,
            }:
                continue
            trace.events.append(observation)
            self._evaluate(trace, active.metrics)

    def diagnostics(self) -> dict[str, Any]:
        """Return compact, primitive-only current/last session diagnostics."""
        active = self._active
        metrics = self._build_metrics(active) if active else (
            self._last_report.metrics if self._last_report else None
        )
        recent = [
            {
                "trace_id": trace.trace_id,
                "decision_id": trace.decision_id,
                "command_id": trace.command_id,
                "outcome": trace.outcome.value,
                "strategy": trace.strategy,
                "policy_id": trace.policy_id,
                "context_kind": trace.context_kind,
                "requested_limit_percent": trace.requested_limit_percent,
                "confirmed_limit_percent": trace.confirmed_limit_percent,
            }
            for trace in list(self._traces)[-10:]
        ]
        latest_trace = self._traces[-1] if self._traces else None
        return _to_primitives(
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "mode": self._mode.value,
                "session_active": active is not None,
                "session_started_at": active.started_at if active else None,
                "session_id": active.session_id if active else None,
                "last_session_end_reason": (
                    self._last_report.end_reason if self._last_report else None
                ),
                "last_session_report": self._last_report.as_dict() if self._last_report else None,
                "metrics": asdict(metrics) if metrics else None,
                "retained_traces": len(self._traces),
                "detailed_trace_capacity": self._max_traces,
                "recent_timeline": recent,
                "last_command_decision": (
                    _last_command_decision(latest_trace)
                    if latest_trace is not None
                    else {
                        "available": False,
                        "reason_code": "no_command_trace_recorded",
                    }
                ),
                "battery_priority_comparisons": [
                    asdict(comparison)
                    for comparison in list(self._strategy_comparisons)[-10:]
                ],
                "energy_strategy_timeline": [
                    asdict(tick)
                    for tick in list(self._energy_strategy_ticks)[-20:]
                ],
            }
        )

    def _append_trace(self, trace: CommandTrace, active: _ActiveSession) -> None:
        """Append while conservatively finalizing an evicted unresolved trace."""
        if len(self._traces) == self._max_traces:
            evicted = self._traces[0]
            if evicted.session_id == active.session_id:
                self._finalize_trace(evicted, active.metrics)
        self._traces.append(trace)

    def _pending_trace(self) -> CommandTrace | None:
        """Return newest trace that has not received a final result yet."""
        if self._active is None:
            return None
        for trace in reversed(self._traces):
            if (
                trace.session_id == self._active.session_id
                and trace.outcome is CommandOutcome.PENDING
            ):
                return trace
        return None

    def _evaluate(self, trace: CommandTrace, metrics: _MetricAccumulator) -> None:
        """Classify only from normal post-command measurements."""
        if trace.outcome is not CommandOutcome.CONFIRMED:
            return
        observations = _post_command_observations(trace)
        trace.data_quality = _data_quality(trace, observations)
        if observations:
            grid_errors = [
                float(event.details["grid_power_w"]) - trace.target_grid_power_w
                for event in observations
            ]
            trace.final_grid_error_w = grid_errors[-1]
            if trace.return_to_target_latency_ms is None:
                for event, error in zip(observations, grid_errors):
                    if abs(error) <= trace.deadband_w:
                        trace.return_to_target_latency_ms = event.monotonic_ms - trace.monotonic_ms
                        break
            if trace.first_pv_change_latency_ms is None and trace.pv_power_w is not None:
                for event in observations:
                    power = event.details.get("pv_power_w")
                    if (
                        power is not None
                        and abs(float(power) - trace.pv_power_w)
                        >= TRACE_SIGNIFICANT_PV_CHANGE_W
                    ):
                        trace.first_pv_change_latency_ms = event.monotonic_ms - trace.monotonic_ms
                        break
            trace.overshoot_detected = _has_overshoot(grid_errors, trace.deadband_w)
            trace.oscillation_suspected = _has_oscillation(grid_errors, trace.deadband_w)
            if (
                trace.return_to_target_latency_ms is not None
                and trace.data_quality is DataQuality.COMPLETE
            ):
                trace.outcome = CommandOutcome.EFFECTIVE
        elapsed = _monotonic_ms() - trace.monotonic_ms
        if (
            trace.outcome is CommandOutcome.CONFIRMED
            and elapsed >= TRACE_OBSERVATION_WINDOW_SECONDS * 1000
        ):
            trace.outcome = (
                CommandOutcome.INEFFECTIVE
                if trace.data_quality is DataQuality.COMPLETE
                else CommandOutcome.INDETERMINATE
            )
        if trace.outcome in {
            CommandOutcome.EFFECTIVE,
            CommandOutcome.INEFFECTIVE,
            CommandOutcome.INDETERMINATE,
        }:
            self._finalize_trace(trace, metrics)

    def _finalize_trace(self, trace: CommandTrace, metrics: _MetricAccumulator) -> None:
        """Complete unresolved outcomes conservatively, then account them once."""
        if trace.outcome is CommandOutcome.CONFIRMED:
            trace.outcome = CommandOutcome.INDETERMINATE
        if trace.outcome is CommandOutcome.PENDING:
            trace.outcome = CommandOutcome.FAILED
            metrics.record_finished(trace)
        if trace.outcome in {
            CommandOutcome.EFFECTIVE,
            CommandOutcome.INEFFECTIVE,
            CommandOutcome.INDETERMINATE,
        }:
            trace.post_command_evaluation = {
                "outcome": trace.outcome.value,
                "data_quality": trace.data_quality.value,
                "final_grid_error_w": trace.final_grid_error_w,
                "overshoot_detected": trace.overshoot_detected,
                "oscillation_suspected": trace.oscillation_suspected,
            }
            trace.events.append(
                _event(
                    "outcome_evaluated",
                    result=trace.outcome.value,
                    details=trace.post_command_evaluation,
                )
            )
            metrics.record_evaluation(trace)

    def _finalize_pending(self, active: _ActiveSession) -> None:
        """End unresolved commands conservatively when a session closes."""
        for trace in self._traces:
            if trace.session_id == active.session_id:
                if trace.outcome is CommandOutcome.CONFIRMED:
                    self._evaluate(trace, active.metrics)
                self._finalize_trace(trace, active.metrics)

    def _build_metrics(self, active: _ActiveSession | None) -> SessionMetrics:
        """Build full-session metrics from aggregates, never only the ring buffer."""
        if active is None:
            return _empty_metrics()
        accumulator = active.metrics
        retained = sum(trace.session_id == active.session_id for trace in self._traces)
        total_span = (
            accumulator.previous_sample.monotonic_ms - accumulator.first_sample.monotonic_ms
            if accumulator.first_sample is not None and accumulator.previous_sample is not None
            else 0.0
        )
        coverage = accumulator.covered_ms / total_span * 100 if total_span else None
        tolerance = (
            accumulator.tolerance_ms / accumulator.covered_ms * 100
            if accumulator.covered_ms and accumulator.target_grid_power_w is not None
            else None
        )
        sample_size = max(
            len(accumulator.modbus_samples),
            len(accumulator.response_samples),
            len(accumulator.error_samples),
            len(accumulator.amplitude_samples),
        )
        return SessionMetrics(
            decisions=active.decisions,
            commands_started=accumulator.commands_started,
            commands_confirmed=accumulator.commands_confirmed,
            commands_failed=accumulator.commands_failed,
            commands_effective=accumulator.commands_effective,
            commands_ineffective=accumulator.commands_ineffective,
            commands_indeterminate=accumulator.commands_indeterminate,
            retained_command_count=retained,
            detailed_traces_truncated=accumulator.commands_started > retained,
            data_coverage_percent=coverage,
            average_modbus_duration_ms=(
                accumulator.modbus_total_ms / accumulator.modbus_count
                if accumulator.modbus_count
                else None
            ),
            median_modbus_duration_ms=_median(list(accumulator.modbus_samples)),
            average_energy_response_ms=(
                accumulator.response_total_ms / accumulator.response_count
                if accumulator.response_count
                else None
            ),
            median_energy_response_ms=_median(list(accumulator.response_samples)),
            maximum_energy_response_ms=accumulator.response_max_ms,
            weighted_time_in_tolerance_percent=tolerance,
            average_absolute_error_w=(
                accumulator.error_total_w / accumulator.error_count
                if accumulator.error_count
                else None
            ),
            median_absolute_error_w=_median(list(accumulator.error_samples)),
            average_command_amplitude_percent=(
                accumulator.amplitude_total_percent / accumulator.amplitude_count
                if accumulator.amplitude_count
                else None
            ),
            maximum_command_amplitude_percent=accumulator.amplitude_max_percent,
            overshoots=accumulator.overshoots,
            suspected_oscillations=accumulator.suspected_oscillations,
            metric_sample_size=sample_size,
        )


def _event(
    event_type: str,
    *,
    source_timestamp: datetime | None = None,
    result: str | None = None,
    details: dict[str, Any] | None = None,
) -> TraceEvent:
    now = _utc_now()
    return TraceEvent(
        event_type, now, _monotonic_ms(), source_timestamp, now, result, details or {}
    )


def _post_command_observations(trace: CommandTrace) -> list[TraceEvent]:
    start = trace.write_finished_monotonic_ms or trace.monotonic_ms
    return [
        event
        for event in trace.events
        if event.event_type == "measurement_observed" and event.monotonic_ms >= start
    ]


def _data_quality(trace: CommandTrace, observations: list[TraceEvent]) -> DataQuality:
    if len(observations) < 2:
        return DataQuality.INSUFFICIENT
    start = trace.write_finished_monotonic_ms or trace.monotonic_ms
    if observations[0].monotonic_ms - start > TRACE_MAX_SAMPLE_GAP_SECONDS * 1000:
        return DataQuality.GAPPED
    gaps = [
        current.monotonic_ms - previous.monotonic_ms
        for previous, current in zip(observations, observations[1:])
    ]
    if any(gap > TRACE_MAX_SAMPLE_GAP_SECONDS * 1000 for gap in gaps):
        return DataQuality.GAPPED
    return DataQuality.COMPLETE


def _has_overshoot(errors: list[float], deadband_w: float) -> bool:
    significant = [error for error in errors if abs(error) > deadband_w]
    return bool(significant and significant[0] * significant[-1] < 0)


def _has_oscillation(errors: list[float], deadband_w: float) -> bool:
    signs = [1 if error > 0 else -1 for error in errors if abs(error) > deadband_w]
    return sum(left != right for left, right in zip(signs, signs[1:])) >= 2


def _last_command_decision(trace: CommandTrace) -> dict[str, Any]:
    """Build one coherent diagnostic summary from exactly one command trace."""
    latest_observation = next(
        (
            event.details.get("dtu_limit_observation")
            for event in reversed(trace.events)
            if event.event_type == "measurement_observed"
            and event.details.get("dtu_limit_observation")
        ),
        None,
    )
    return {
        "available": True,
        "trace_id": trace.trace_id,
        "decision_id": trace.decision_id,
        "command_id": trace.command_id,
        "timestamp_utc": trace.timestamp_utc,
        "grid_power_w": trace.grid_power_w,
        "grid_source_timestamp": trace.grid_source_timestamp,
        "pv_power_w": trace.pv_power_w,
        "pv_source_timestamp": trace.pv_source_timestamp,
        "real_limit_before_percent": trace.real_limit_before_percent,
        "calculated_limit_percent": trace.calculated_limit_percent,
        "requested_limit_percent": trace.requested_limit_percent,
        "command_sent": trace.write_started_monotonic_ms is not None,
        "confirmed_limit_percent": trace.confirmed_limit_percent,
        "outcome": trace.outcome.value,
        "decision_reason": trace.decision_reason,
        "policy_id": trace.policy_id,
        "policy_reason": trace.policy_reason,
        "strategy": trace.strategy,
        "modbus_duration_ms": trace.modbus_duration_ms,
        "port_results": trace.port_results,
        "dtu_limit_at_decision": trace.pre_decision_inputs.get(
            "dtu_limit_observation"
        ),
        "latest_dtu_limit_observation": latest_observation,
    }


def _empty_metrics() -> SessionMetrics:
    return SessionMetrics(
        decisions=0,
        commands_started=0,
        commands_confirmed=0,
        commands_failed=0,
        commands_effective=0,
        commands_ineffective=0,
        commands_indeterminate=0,
        retained_command_count=0,
        detailed_traces_truncated=False,
        data_coverage_percent=None,
        average_modbus_duration_ms=None,
        median_modbus_duration_ms=None,
        average_energy_response_ms=None,
        median_energy_response_ms=None,
        maximum_energy_response_ms=None,
        weighted_time_in_tolerance_percent=None,
        average_absolute_error_w=None,
        median_absolute_error_w=None,
        average_command_amplitude_percent=None,
        maximum_command_amplitude_percent=None,
        overshoots=0,
        suspected_oscillations=0,
        metric_sample_size=0,
    )


def _mean(values: list[float | int]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float | int]) -> float | None:
    return float(median(values)) if values else None


def _primitive_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return _to_primitives(value)


def _to_primitives(value: Any) -> Any:
    """Convert datetimes/enums/containers without coupling traces to HA objects."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_primitives(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [_to_primitives(item) for item in value]
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _monotonic_ms() -> float:
    return time.monotonic_ns() / 1_000_000
