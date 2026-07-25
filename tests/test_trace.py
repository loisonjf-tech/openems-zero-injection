"""Unit tests for the passive Build004 RC3 Trace Recorder."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json

from custom_components.openems_zero_injection.trace import (
    CommandOutcome,
    DataQuality,
    TraceRecorder,
)


def _start(
    recorder: TraceRecorder,
    command_id: int = 1,
    *,
    before_modbus_finish: Callable[[], None] | None = None,
    start_session: bool = True,
):
    if start_session:
        recorder.start_session(reason="test")
    trace = recorder.start_command(
        decision_id=command_id,
        command_id=command_id,
        controller_mode="Production",
        grid_power_w=-500,
        grid_source_timestamp=datetime.now(UTC),
        pv_power_w=1000,
        pv_source_timestamp=datetime.now(UTC),
        real_limit_before_percent=50,
        calculated_limit_percent=20,
        requested_limit_percent=20,
        decision_reason="Predictive limit applied",
        strategy="predictive",
        target_grid_power_w=-40,
        deadband_w=30,
    )
    assert trace is not None
    recorder.record_modbus_started()
    for port in (1, 2, 3):
        recorder.record_port_result(port=port, result="confirmed")
    if before_modbus_finish is not None:
        before_modbus_finish()
    recorder.finish_modbus(result="confirmed")
    return trace


def _observe(recorder: TraceRecorder, grid: float, pv: float, timestamp: datetime) -> None:
    recorder.observe_measurement(
        grid_power_w=grid,
        grid_source_timestamp=timestamp,
        pv_power_w=pv,
        pv_source_timestamp=timestamp,
    )


def test_session_creation_and_closure() -> None:
    recorder = TraceRecorder()
    recorder.start_session(reason="production")
    recorder.record_decision()
    report = recorder.stop_session(reason="manual")

    assert report is not None
    assert report.end_reason == "manual"
    assert report.metrics.decisions == 1
    assert not recorder.session_active


def test_buffer_is_limited_to_100_commands() -> None:
    recorder = TraceRecorder(max_traces=100)
    recorder.start_session(reason="production")
    for command_id in range(101):
        trace = recorder.start_command(
            decision_id=command_id,
            command_id=command_id,
            controller_mode="Production",
            grid_power_w=-100,
            grid_source_timestamp=datetime.now(UTC),
            pv_power_w=100,
            pv_source_timestamp=datetime.now(UTC),
            real_limit_before_percent=50,
            calculated_limit_percent=49,
            requested_limit_percent=49,
            decision_reason="test",
            strategy="test",
            target_grid_power_w=-40,
            deadband_w=30,
        )
        assert trace is not None

    assert len(recorder.traces) == 100
    assert recorder.traces[0].command_id == 1


def test_confirmed_command_records_three_port_results(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("custom_components.openems_zero_injection.trace._monotonic_ms", lambda: clock[0])
    recorder = TraceRecorder()
    trace = _start(recorder, before_modbus_finish=lambda: clock.__setitem__(0, 120))
    recorder.finish_command(confirmed=True, confirmed_limit_percent=20)

    assert trace.outcome is CommandOutcome.CONFIRMED
    assert trace.confirmed_limit_percent == 20
    assert trace.port_results == {1: "confirmed", 2: "confirmed", 3: "confirmed"}
    assert trace.modbus_duration_ms == 120


def test_failed_command_is_not_classified_as_ineffective() -> None:
    recorder = TraceRecorder()
    trace = _start(recorder)
    recorder.finish_command(confirmed=False, confirmed_limit_percent=None, error="port 2")

    assert trace.outcome is CommandOutcome.FAILED


def test_effective_command_requires_covered_post_command_measurements(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("custom_components.openems_zero_injection.trace._monotonic_ms", lambda: clock[0])
    recorder = TraceRecorder()
    trace = _start(recorder)
    recorder.finish_command(confirmed=True, confirmed_limit_percent=20)
    now = datetime.now(UTC)
    clock[0] = 1_000
    _observe(recorder, -200, 900, now)
    clock[0] = 4_000
    _observe(recorder, -40, 800, now)

    assert trace.outcome is CommandOutcome.EFFECTIVE
    assert trace.data_quality is DataQuality.COMPLETE
    assert trace.return_to_target_latency_ms == 4_000
    assert trace.first_pv_change_latency_ms == 1_000


def test_ineffective_command_needs_a_complete_observation_window(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("custom_components.openems_zero_injection.trace._monotonic_ms", lambda: clock[0])
    recorder = TraceRecorder()
    trace = _start(recorder)
    recorder.finish_command(confirmed=True, confirmed_limit_percent=20)
    now = datetime.now(UTC)
    for millisecond in range(1_000, 62_000, 10_000):
        clock[0] = millisecond
        _observe(recorder, -200, 1000, now)

    assert trace.outcome is CommandOutcome.INEFFECTIVE


def test_missing_or_gapped_measurements_are_indeterminate(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("custom_components.openems_zero_injection.trace._monotonic_ms", lambda: clock[0])
    recorder = TraceRecorder()
    trace = _start(recorder)
    recorder.finish_command(confirmed=True, confirmed_limit_percent=20)
    now = datetime.now(UTC)
    clock[0] = 1_000
    _observe(recorder, -200, 1000, now)
    clock[0] = 20_000
    _observe(recorder, -200, 1000, now)
    clock[0] = 61_000
    _observe(recorder, -200, 1000, now)

    assert trace.data_quality is DataQuality.GAPPED
    assert trace.outcome is CommandOutcome.INDETERMINATE


def test_weighted_time_in_tolerance_ignores_telemetry_holes(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("custom_components.openems_zero_injection.trace._monotonic_ms", lambda: clock[0])
    recorder = TraceRecorder()
    _start(recorder)
    recorder.finish_command(confirmed=True, confirmed_limit_percent=20)
    now = datetime.now(UTC)
    _observe(recorder, -40, 1000, now)
    clock[0] = 3_000
    _observe(recorder, -35, 1000, now)
    clock[0] = 6_000
    _observe(recorder, -200, 1000, now)
    clock[0] = 30_000  # gap excluded from both coverage and tolerance
    _observe(recorder, -40, 1000, now)
    report = recorder.stop_session(reason="done")

    assert report is not None
    assert report.metrics.data_coverage_percent == 20.0
    assert report.metrics.weighted_time_in_tolerance_percent == 50.0


def test_recorder_has_no_modbus_or_scheduler_api() -> None:
    recorder = TraceRecorder()
    assert not hasattr(recorder, "async_read_registers")
    assert not hasattr(recorder, "async_write_temporary_power_limit")
    assert not hasattr(recorder, "async_tick")


def test_session_aggregates_are_not_truncated_by_detailed_trace_buffer() -> None:
    """All session counts survive after the 100 detailed timelines roll over."""
    recorder = TraceRecorder(max_traces=2)
    recorder.start_session(reason="test")
    for command_id in range(5):
        _start(recorder, command_id=command_id, start_session=False)
        recorder.finish_command(confirmed=True, confirmed_limit_percent=20)

    report = recorder.stop_session(reason="done")

    assert report is not None
    assert report.metrics.commands_started == 5
    assert report.metrics.commands_confirmed == 5
    assert report.metrics.commands_indeterminate == 5
    assert report.metrics.retained_command_count == 2
    assert report.metrics.detailed_traces_truncated


def test_timeline_is_serializable_and_keeps_explainability_inputs() -> None:
    """Future offline replay can consume primitive, language-neutral trace data."""
    recorder = TraceRecorder()
    recorder.start_session(
        reason="production", configuration={"target_grid_power_w": -40}
    )
    trace = recorder.start_command(
        decision_id=7,
        command_id=3,
        controller_mode="Production",
        grid_power_w=-500,
        grid_source_timestamp=datetime.now(UTC),
        pv_power_w=1000,
        pv_source_timestamp=datetime.now(UTC),
        real_limit_before_percent=50,
        calculated_limit_percent=20,
        requested_limit_percent=20,
        decision_reason="Predictive limit applied",
        strategy="predictive_tracking",
        target_grid_power_w=-40,
        deadband_w=30,
        policy_id="zero_injection",
        policy_reason="Configured zero-injection target",
        policy_confidence=1.0,
        policy_fallback_used=False,
        context_kind="stable",
        context_confidence=0.9,
        context_reason="measurements_stable",
    )

    assert trace is not None
    timeline = trace.as_dict()
    assert timeline["schema_version"] == 2
    assert timeline["policy_id"] == "zero_injection"
    assert timeline["context_kind"] == "stable"
    assert timeline["pre_decision_inputs"]["grid_power_w"] == -500
    assert timeline["events"][0]["event_type"] == "decision_created"
    json.dumps(timeline)
