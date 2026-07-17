"""Tests for the Build004 automatic-command safety scheduler."""

from unittest.mock import AsyncMock

from custom_components.openems_zero_injection.const import ControllerMode, SchedulerState
from custom_components.openems_zero_injection.scheduler import SafetyScheduler


async def test_scheduler_allows_production_command_then_waits() -> None:
    scheduler = SafetyScheduler(12)
    command = AsyncMock()
    success, reason = await scheduler.async_execute(ControllerMode.PRODUCTION, command)
    assert success and reason == "Command confirmed"
    command.assert_awaited_once()
    assert scheduler.state is SchedulerState.WAITING
    assert scheduler.remaining_seconds() > 0


async def test_scheduler_refuses_disabled_and_simulation() -> None:
    scheduler = SafetyScheduler(12)
    command = AsyncMock()
    assert not (await scheduler.async_execute(ControllerMode.DISABLED, command))[0]
    scheduler.reset()
    assert not (await scheduler.async_execute(ControllerMode.SIMULATION, command))[0]
    command.assert_not_awaited()


async def test_scheduler_records_error_without_retry() -> None:
    scheduler = SafetyScheduler(12)
    command = AsyncMock(side_effect=RuntimeError("DTU failed"))
    success, reason = await scheduler.async_execute(ControllerMode.PRODUCTION, command)
    assert not success
    assert "Command failed" in reason
    assert scheduler.state is SchedulerState.ERROR
    assert scheduler.last_error == "DTU failed"
