"""Tests for optional, passive JSONL history persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from custom_components.openems_zero_injection.persistent_history import (
    HISTORY_PERIODIC_SECONDS,
    HistoryEventType,
    PersistentHistoryRecorder,
)


class _Config:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, *parts: str) -> str:
        return str(self._root.joinpath(*parts))


class _Hass:
    """Minimal async executor surface; no Home Assistant services are used."""

    def __init__(self, root: Path) -> None:
        self.config = _Config(root)

    async def async_add_executor_job(self, target, *args):
        return target(*args)

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


@pytest.mark.asyncio
async def test_disabled_history_never_creates_storage(tmp_path: Path) -> None:
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=False, retention_days=30,
        integration_version="test", algorithm_version="algorithm",
    )
    await recorder.async_start()
    recorder.record(HistoryEventType.DECISION, {"grid_power_w": -40})
    await recorder.async_stop()
    assert not (tmp_path / "openems_zero_injection").exists()


@pytest.mark.asyncio
async def test_history_writes_versioned_daily_jsonl(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=True, retention_days=30,
        integration_version="0.8.0", algorithm_version="capacity_release", directory=directory,
    )
    timestamp = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    await recorder.async_start()
    recorder.record(
        HistoryEventType.DECISION,
        {"battery": {"soc_percent": 60}},
        timestamp=timestamp,
    )
    await recorder.async_stop()

    event = json.loads((directory / "2026-08-07.jsonl").read_text(encoding="utf-8"))
    assert event["schema_version"] == 1
    assert event["integration_version"] == "0.8.0"
    assert event["algorithm_version"] == "capacity_release"
    assert event["event_type"] == "decision"
    assert event["payload"]["battery"]["soc_percent"] == 60


@pytest.mark.asyncio
async def test_history_start_creates_no_daily_file_before_an_event(tmp_path: Path) -> None:
    """Startup only prepares the directory and worker; it does not write JSONL."""
    directory = tmp_path / "history"
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=True, retention_days=30,
        integration_version="test", algorithm_version="algorithm", directory=directory,
    )

    await recorder.async_start()

    assert directory.exists()
    assert list(directory.glob("*.jsonl")) == []
    await recorder.async_stop()


@pytest.mark.asyncio
async def test_periodic_sample_is_limited_to_fifteen_minutes(tmp_path: Path) -> None:
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=True, retention_days=30,
        integration_version="test", algorithm_version="algorithm", directory=tmp_path / "history",
    )
    timestamp = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    await recorder.async_start()
    recorder.record_periodic_if_due({}, timestamp=timestamp)
    recorder.record_periodic_if_due(
        {}, timestamp=timestamp + timedelta(seconds=HISTORY_PERIODIC_SECONDS - 1)
    )
    recorder.record_periodic_if_due(
        {}, timestamp=timestamp + timedelta(seconds=HISTORY_PERIODIC_SECONDS)
    )
    await recorder.async_stop()
    lines = (tmp_path / "history" / "2026-08-07.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_retention_purges_only_expired_daily_history(tmp_path: Path) -> None:
    directory = tmp_path / "history"
    directory.mkdir()
    (directory / "2000-01-01.jsonl").write_text("old\n", encoding="utf-8")
    (directory / "not-history.jsonl").write_text("keep\n", encoding="utf-8")
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=True, retention_days=30,
        integration_version="test", algorithm_version="algorithm", directory=directory,
    )
    await recorder.async_start()
    await recorder.async_stop()
    assert not (directory / "2000-01-01.jsonl").exists()
    assert (directory / "not-history.jsonl").exists()


def test_full_queue_drops_without_waiting(tmp_path: Path) -> None:
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=True, retention_days=30,
        integration_version="test", algorithm_version="algorithm", directory=tmp_path / "history",
    )
    for number in range(501):
        recorder.record(HistoryEventType.DECISION, {"number": number})
    assert recorder.diagnostics()["events_dropped"] == 1
    assert recorder.diagnostics()["queue_size"] == 500


@pytest.mark.asyncio
async def test_write_error_is_diagnostic_only(tmp_path: Path, monkeypatch) -> None:
    recorder = PersistentHistoryRecorder(
        _Hass(tmp_path), enabled=True, retention_days=30,
        integration_version="test", algorithm_version="algorithm", directory=tmp_path / "history",
    )
    await recorder.async_start()
    monkeypatch.setattr(
        recorder, "_write_batch_sync", lambda _batch: (_ for _ in ()).throw(OSError("disk full"))
    )
    recorder.record(HistoryEventType.DECISION, {"grid_power_w": -40})
    await recorder.async_stop()
    assert recorder.diagnostics()["write_errors"] == 1
    assert recorder.diagnostics()["events_written"] == 0
