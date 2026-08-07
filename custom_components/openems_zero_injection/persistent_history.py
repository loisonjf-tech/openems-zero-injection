"""Optional, non-blocking long-term JSONL observability history.

This module is deliberately outside the control plane.  It observes facts
already collected by the integration, keeps a bounded memory queue and writes
them asynchronously.  A full queue or a filesystem error is diagnostic-only:
it must never affect a controller decision, a scheduler state or Modbus I/O.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


_LOGGER = logging.getLogger(__name__)

HISTORY_SCHEMA_VERSION = 1
HISTORY_DIRECTORY_NAME = "history"
HISTORY_QUEUE_MAXSIZE = 500
HISTORY_BATCH_SIZE = 25
HISTORY_FLUSH_SECONDS = 0.25
HISTORY_PERIODIC_SECONDS = 15 * 60


class HistoryEventType(StrEnum):
    """Stable event kinds for a future exporter or offline replay tool."""

    DECISION = "decision"
    COMMAND_RESULT = "command_result"
    TRANSITION = "transition"
    PERIODIC_SNAPSHOT = "periodic_snapshot"


def _to_primitives(value: Any) -> Any:
    """Convert supported values to stable JSON primitives."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _to_primitives(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_primitives(item) for item in value]
    return value


class PersistentHistoryRecorder:
    """Write selected passive facts to daily JSONL files when enabled."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        enabled: bool,
        retention_days: int,
        integration_version: str,
        algorithm_version: str,
        directory: Path | None = None,
    ) -> None:
        self._hass = hass
        self._enabled = enabled
        self._retention_days = retention_days
        self._integration_version = integration_version
        self._algorithm_version = algorithm_version
        self._directory = directory or Path(
            hass.config.path("openems_zero_injection", HISTORY_DIRECTORY_NAME)
        )
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(HISTORY_QUEUE_MAXSIZE)
        self._worker: asyncio.Task[None] | None = None
        self._stopping = False
        self._last_periodic_at: datetime | None = None
        self._events_queued = 0
        self._events_written = 0
        self._events_dropped = 0
        self._write_errors = 0
        self._last_error: str | None = None
        self._last_error_log_at: float | None = None

    @property
    def enabled(self) -> bool:
        """Whether persistence is explicitly enabled by the user."""
        return self._enabled

    async def async_start(self) -> None:
        """Start the passive writer only when persistence is enabled."""
        if not self._enabled or self._worker is not None:
            return
        try:
            await self._hass.async_add_executor_job(self._prepare_directory_sync)
        except OSError as err:
            self._record_write_error(err)
            return
        self._stopping = False
        self._worker = self._hass.async_create_task(self._async_worker())

    async def async_stop(self) -> None:
        """Drain briefly on unload; never let storage delay integration shutdown."""
        if self._worker is None:
            return
        self._stopping = True
        try:
            await asyncio.wait_for(self._worker, timeout=2)
        except TimeoutError:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        except Exception:  # pragma: no cover - defensive task containment
            _LOGGER.debug("Persistent history worker stopped with an error", exc_info=True)
        self._worker = None

    def record(
        self,
        event_type: HistoryEventType,
        payload: Mapping[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """Queue one already-known fact without waiting for I/O."""
        if not self._enabled or self._stopping:
            return
        observed_at = timestamp or datetime.now(UTC)
        event = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "integration_version": self._integration_version,
            "algorithm_version": self._algorithm_version,
            "event_type": event_type.value,
            "timestamp_utc": observed_at.astimezone(UTC).isoformat(),
            "payload": _to_primitives(dict(payload)),
        }
        try:
            self._queue.put_nowait(event)
            self._events_queued += 1
        except asyncio.QueueFull:
            self._events_dropped += 1
            self._last_error = "history_queue_full"

    def record_periodic_if_due(
        self, payload: Mapping[str, Any], *, timestamp: datetime | None = None
    ) -> None:
        """Queue a bounded 15-minute context sample, never an extra poll."""
        if not self._enabled:
            return
        now = timestamp or datetime.now(UTC)
        if (
            self._last_periodic_at
            and (now - self._last_periodic_at).total_seconds()
            < HISTORY_PERIODIC_SECONDS
        ):
            return
        self._last_periodic_at = now
        self.record(HistoryEventType.PERIODIC_SNAPSHOT, payload, timestamp=now)

    def diagnostics(self) -> dict[str, Any]:
        """Return safe status only; no absolute host path is exposed."""
        return {
            "enabled": self._enabled,
            "storage": f"/config/openems_zero_injection/{HISTORY_DIRECTORY_NAME}",
            "retention_days": self._retention_days,
            "queue_size": self._queue.qsize(),
            "queue_capacity": HISTORY_QUEUE_MAXSIZE,
            "events_queued": self._events_queued,
            "events_written": self._events_written,
            "events_dropped": self._events_dropped,
            "write_errors": self._write_errors,
            "last_error": self._last_error,
            "periodic_interval_seconds": HISTORY_PERIODIC_SECONDS,
        }

    async def _async_worker(self) -> None:
        """Batch queue contents and execute blocking filesystem work off-loop."""
        while not self._stopping or not self._queue.empty():
            batch: list[dict[str, Any]] = []
            try:
                batch.append(await asyncio.wait_for(self._queue.get(), HISTORY_FLUSH_SECONDS))
            except TimeoutError:
                continue
            while len(batch) < HISTORY_BATCH_SIZE:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                written = await self._hass.async_add_executor_job(self._write_batch_sync, batch)
                self._events_written += written
            except OSError as err:
                self._record_write_error(err)
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _prepare_directory_sync(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._purge_expired_sync(dt_util.now().date())

    def _write_batch_sync(self, batch: list[dict[str, Any]]) -> int:
        self._directory.mkdir(parents=True, exist_ok=True)
        by_day: dict[str, list[dict[str, Any]]] = {}
        for event in batch:
            event_date = datetime.fromisoformat(event["timestamp_utc"]).astimezone(
                dt_util.DEFAULT_TIME_ZONE
            ).date()
            by_day.setdefault(event_date.isoformat(), []).append(event)
        for day, events in by_day.items():
            target = self._directory / f"{day}.jsonl"
            with target.open("a", encoding="utf-8") as file:
                for event in events:
                    file.write(
                        json.dumps(
                            event, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                        )
                    )
                    file.write("\n")
        self._purge_expired_sync(dt_util.now().date())
        return len(batch)

    def _purge_expired_sync(self, today: date) -> None:
        cutoff = today - timedelta(days=self._retention_days)
        for candidate in self._directory.glob("????-??-??.jsonl"):
            try:
                candidate_day = date.fromisoformat(candidate.stem)
            except ValueError:
                continue
            if candidate_day < cutoff:
                candidate.unlink(missing_ok=True)

    def _record_write_error(self, err: OSError) -> None:
        self._write_errors += 1
        self._last_error = str(err)
        now = asyncio.get_running_loop().time()
        if self._last_error_log_at is None or now - self._last_error_log_at >= 300:
            self._last_error_log_at = now
            _LOGGER.warning("Persistent OpenEMS history write failed: %s", err)
