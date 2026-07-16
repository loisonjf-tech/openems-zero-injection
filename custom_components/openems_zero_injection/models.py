"""Integration data models independent from Home Assistant entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DtuMeasurements:
    """Immutable telemetry obtained from one DTU Modbus read cycle."""

    connected: bool
    serial_number: str | None
    inverter_count: int | None
    meter_count: int | None
    active_power_w: float | None
    reactive_power_var: float | None
    daily_energy_wh: int | None
    total_energy_wh: int | None
    response_time_ms: float | None
    last_success: datetime | None
    last_error: str | None
