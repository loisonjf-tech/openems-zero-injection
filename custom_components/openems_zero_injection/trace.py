"""Bounded, passive command tracing for OpenEMS Zero Injection.

The recorder deliberately owns no timer, Home Assistant listener, Modbus client,
or disk storage.  It only observes values that the controller and coordinator
already obtained for their normal work.
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


TRACE_BUFFER_SIZE = 100
TRACE_MAX_EVENTS_PER_COMMAND = 64
TRACE_OBSERVATION_WINDOW_SECONDS = 60.0
TRACE_MAX_SAMPLE_GAP_SECONDS = 12.0
TRACE_SIGNIFICANT_PV_CHANGE_W = 50.0


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


@dataclass(slots=True)
class TraceEvent:
    """One observed event with source and receipt times kept separate."""

    event_type: str
    timestamp_utc: datetime
    monotonic_ms: float
    source_timestamp: datetime | None
    observed_timestamp: datetime
    result: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a diagnostics-safe representation."""
        return asdict(self)


@dataclass(slots=True)
class CommandTrace:
    """One bounded timeline for an already requested DTU command."""

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
        """Return diagnostics-safe data without exposing implementation objects."""
        result = asdict(self)
        result["events"] = [event.as_dict() for event in self.events]
        result["modbus_duration_ms"] = self.modbus_duration_ms
        result["command_amplitude_percent"] = self.command_amplitude_percent
        return result


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    """Aggregate quality and command-performance values for one session."""

    decisions: int
    commands_confirmed: int
    commands_failed: int
    commands_effective: int
    commands_ineffective: int
    commands_indeterminate: int
    retained_command_count: int
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


@dataclass(frozen=True, slots=True)
class SessionReport:
    """Immutable summary produced when a regulation session is closed."""

    session_id: str
    started_at: datetime
    ended_at: datetime
    end_reason: str
    metrics: SessionMetrics

    @property
    def duration_seconds(self) -> float:
        """Return the real wall-clock duration of the session."""
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


@dataclass(slots=True)
class _ActiveSession:
    """Private mutable state for a currently active production session."""

    session_id: str
    started_at: datetime
    started_monotonic_ms: float
    decisions: int = 0
    samples: deque[TraceEvent] = field(
        default_factory=lambda: deque(maxlen=TRACE_BUFFER_SIZE * 2)
    )


class TraceRecorder:
    """Passive bounded black box for controller commands and observations."""

    def __init__(self, *, max_traces: int = TRACE_BUFFER_SIZE) -> None:
        if max_traces < 1:
            raise ValueError("max_traces must be positive")
        self._mode = TraceMode.NORMAL
        self._traces: deque[CommandTrace] = deque(maxlen=max_traces)
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

    def start_session(self, *, reason: str) -> None:
        """Start a production session; close an earlier one first if necessary."""
        if self._active is not None:
            self.stop_session(reason=f"restarted: {reason}")
        now = _utc_now()
        self._active = _ActiveSession(
            session_id=uuid4().hex,
            started_at=now,
            started_monotonic_ms=_monotonic_ms(),
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
        )
        self._last_report = report
        self._active = None
        return report

    def rotate_session(self, *, reason: str) -> None:
        """Segment a running session after a major configuration change."""
        if self._active is None:
            return
        self.stop_session(reason=reason)
        self.start_session(reason=reason)

    def record_decision(self) -> None:
        """Count an existing controller decision without changing its outcome."""
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
    ) -> CommandTrace | None:
        """Create a trace for a command that the controller already decided to send."""
        if self._active is None:
            return None
        now = _utc_now()
        trace = CommandTrace(
            trace_id=uuid4().hex,
            session_id=self._active.session_id,
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
        )
        trace.events.append(_event("command_started", result="pending"))
        self._traces.append(trace)
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
        """Record one existing port result; this method never emits a frame."""
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
        self, *, confirmed: bool, confirmed_limit_percent: int | None, error: str | None = None
    ) -> None:
        """Store the controller result after its normal scheduler call returns."""
        trace = self._pending_trace()
        if trace is None:
            return
        trace.confirmed_limit_percent = confirmed_limit_percent if confirmed else None
        trace.outcome = CommandOutcome.CONFIRMED if confirmed else CommandOutcome.FAILED
        trace.events.append(
            _event(
                "command_finished",
                result=trace.outcome.value,
                details={"error": error},
            )
        )

    def observe_measurement(
        self,
        *,
        grid_power_w: float,
        grid_source_timestamp: datetime,
        pv_power_w: float | None,
        pv_source_timestamp: datetime | None,
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
            },
        )
        active.samples.append(observation)
        for trace in self._traces:
            if trace.session_id != active.session_id or trace.outcome not in {
                CommandOutcome.CONFIRMED,
                CommandOutcome.PENDING,
            }:
                continue
            trace.events.append(observation)
            self._evaluate(trace)

    def diagnostics(self) -> dict[str, Any]:
        """Return compact non-sensitive current/last session diagnostics."""
        active = self._active
        metrics = self._build_metrics(active) if active else (
            self._last_report.metrics if self._last_report else None
        )
        return {
            "mode": self._mode.value,
            "session_active": active is not None,
            "session_started_at": active.started_at.isoformat() if active else None,
            "session_id": active.session_id if active else None,
            "last_session_end_reason": self._last_report.end_reason if self._last_report else None,
            "metrics": asdict(metrics) if metrics else None,
            "retained_traces": len(self._traces),
        }

    def _pending_trace(self) -> CommandTrace | None:
        """Return the newest trace that has not received a final result yet."""
        if self._active is None:
            return None
        for trace in reversed(self._traces):
            if trace.session_id == self._active.session_id and trace.outcome is CommandOutcome.PENDING:
                return trace
        return None

    def _evaluate(self, trace: CommandTrace) -> None:
        """Classify only from existing post-command measurements."""
        if trace.outcome is not CommandOutcome.CONFIRMED:
            return
        observations = _post_command_observations(trace)
        trace.data_quality = _data_quality(trace, observations)
        if observations:
            grid_errors = [float(event.details["grid_power_w"]) - trace.target_grid_power_w for event in observations]
            trace.final_grid_error_w = grid_errors[-1]
            if trace.return_to_target_latency_ms is None:
                for event, error in zip(observations, grid_errors):
                    if abs(error) <= trace.deadband_w:
                        trace.return_to_target_latency_ms = event.monotonic_ms - trace.monotonic_ms
                        break
            if trace.first_pv_change_latency_ms is None and trace.pv_power_w is not None:
                for event in observations:
                    power = event.details.get("pv_power_w")
                    if power is not None and abs(float(power) - trace.pv_power_w) >= TRACE_SIGNIFICANT_PV_CHANGE_W:
                        trace.first_pv_change_latency_ms = event.monotonic_ms - trace.monotonic_ms
                        break
            trace.overshoot_detected = _has_overshoot(grid_errors, trace.deadband_w)
            trace.oscillation_suspected = _has_oscillation(grid_errors, trace.deadband_w)
            if trace.return_to_target_latency_ms is not None and trace.data_quality is DataQuality.COMPLETE:
                trace.outcome = CommandOutcome.EFFECTIVE
                return
        elapsed = _monotonic_ms() - trace.monotonic_ms
        if elapsed >= TRACE_OBSERVATION_WINDOW_SECONDS * 1000:
            trace.outcome = (
                CommandOutcome.INEFFECTIVE
                if trace.data_quality is DataQuality.COMPLETE
                else CommandOutcome.INDETERMINATE
            )

    def _finalize_pending(self, active: _ActiveSession) -> None:
        """End all unresolved confirmed commands conservatively at session close."""
        for trace in self._traces:
            if trace.session_id != active.session_id:
                continue
            if trace.outcome is CommandOutcome.CONFIRMED:
                self._evaluate(trace)
                if trace.outcome is CommandOutcome.CONFIRMED:
                    trace.outcome = CommandOutcome.INDETERMINATE

    def _build_metrics(self, active: _ActiveSession | None) -> SessionMetrics:
        """Build metrics from bounded retained traces and interval-weighted samples."""
        if active is None:
            return _empty_metrics()
        traces = [trace for trace in self._traces if trace.session_id == active.session_id]
        modbus = [value for trace in traces if (value := trace.modbus_duration_ms) is not None]
        response = [value for trace in traces if (value := trace.first_pv_change_latency_ms) is not None]
        errors = [abs(trace.final_grid_error_w) for trace in traces if trace.final_grid_error_w is not None]
        amplitudes = [value for trace in traces if (value := trace.command_amplitude_percent) is not None]
        coverage, tolerance = _interval_metrics(active.samples, target=None, deadband=None)
        # Target/deadband can vary only after a deliberate session rotation. Use
        # each trace target for post-command quality; session tolerance uses the
        # latest active trace when available, otherwise has no semantic value.
        if traces:
            coverage, tolerance = _interval_metrics(
                active.samples, target=traces[-1].target_grid_power_w, deadband=traces[-1].deadband_w
            )
        return SessionMetrics(
            decisions=active.decisions,
            commands_confirmed=sum(
                trace.outcome
                in {
                    CommandOutcome.CONFIRMED,
                    CommandOutcome.EFFECTIVE,
                    CommandOutcome.INEFFECTIVE,
                    CommandOutcome.INDETERMINATE,
                }
                for trace in traces
            ),
            commands_failed=sum(trace.outcome is CommandOutcome.FAILED for trace in traces),
            commands_effective=sum(trace.outcome is CommandOutcome.EFFECTIVE for trace in traces),
            commands_ineffective=sum(trace.outcome is CommandOutcome.INEFFECTIVE for trace in traces),
            commands_indeterminate=sum(trace.outcome is CommandOutcome.INDETERMINATE for trace in traces),
            retained_command_count=len(traces),
            data_coverage_percent=coverage,
            average_modbus_duration_ms=_mean(modbus),
            median_modbus_duration_ms=_median(modbus),
            average_energy_response_ms=_mean(response),
            median_energy_response_ms=_median(response),
            maximum_energy_response_ms=max(response) if response else None,
            weighted_time_in_tolerance_percent=tolerance,
            average_absolute_error_w=_mean(errors),
            median_absolute_error_w=_median(errors),
            average_command_amplitude_percent=_mean(amplitudes),
            maximum_command_amplitude_percent=max(amplitudes) if amplitudes else None,
            overshoots=sum(trace.overshoot_detected for trace in traces),
            suspected_oscillations=sum(trace.oscillation_suspected for trace in traces),
        )


def _event(
    event_type: str,
    *,
    source_timestamp: datetime | None = None,
    result: str | None = None,
    details: dict[str, Any] | None = None,
) -> TraceEvent:
    now = _utc_now()
    return TraceEvent(event_type, now, _monotonic_ms(), source_timestamp, now, result, details or {})


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


def _interval_metrics(
    samples: deque[TraceEvent], *, target: float | None, deadband: float | None
) -> tuple[float | None, float | None]:
    if len(samples) < 2:
        return None, None
    covered_ms = 0.0
    tolerance_ms = 0.0
    total_ms = max(0.0, samples[-1].monotonic_ms - samples[0].monotonic_ms)
    for previous, current in zip(samples, list(samples)[1:]):
        interval = current.monotonic_ms - previous.monotonic_ms
        if interval <= 0 or interval > TRACE_MAX_SAMPLE_GAP_SECONDS * 1000:
            continue
        covered_ms += interval
        if target is not None and deadband is not None:
            previous_error = float(previous.details["grid_power_w"]) - target
            current_error = float(current.details["grid_power_w"]) - target
            if abs(previous_error) <= deadband and abs(current_error) <= deadband:
                tolerance_ms += interval
    coverage = covered_ms / total_ms * 100 if total_ms else None
    tolerance = tolerance_ms / covered_ms * 100 if covered_ms and target is not None else None
    return coverage, tolerance


def _empty_metrics() -> SessionMetrics:
    return SessionMetrics(0, 0, 0, 0, 0, 0, 0, None, None, None, None, None, None, None, None, None, None, None, None, None, 0, 0)


def _mean(values: list[float | int]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float | int]) -> float | None:
    return float(median(values)) if values else None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _monotonic_ms() -> float:
    return time.monotonic_ns() / 1_000_000
