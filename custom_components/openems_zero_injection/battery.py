"""Manufacturer-neutral, read-only battery contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class BatteryHealth(StrEnum):
    """Prioritised health calculated centrally by EnergyManager."""

    HEALTHY = "healthy"
    STALE = "stale"
    INCONSISTENT = "inconsistent"
    FAULT = "fault"
    UNAVAILABLE = "unavailable"


class BatteryReasonCode(StrEnum):
    """Stable, serializable diagnostic codes; never user-facing prose."""

    NO_BATTERIES_CONFIGURED = "no_batteries_configured"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_NOT_REFRESHED = "source_not_refreshed"
    DATA_STALE = "data_stale"
    SOC_OUT_OF_RANGE = "soc_out_of_range"
    POWER_NON_FINITE = "power_non_finite"
    POWER_UNIT_UNSUPPORTED = "power_unit_unsupported"
    POWER_SIGN_UNKNOWN = "power_sign_unknown"
    GRID_INPUT_POWER_UNAVAILABLE = "grid_input_power_unavailable"
    GRID_INPUT_POWER_INVALID = "grid_input_power_invalid"
    CHARGE_LIMIT_UNVERIFIED = "charge_limit_unverified"
    CHARGE_LIMIT_INVALID = "charge_limit_invalid"
    REMAINING_POWER_UNAVAILABLE = "remaining_power_unavailable"
    BATTERY_FAULT = "battery_fault"


class BatteryPowerSign(StrEnum):
    """Explicit convention for an adapter-provided directional power sensor."""

    UNKNOWN = "unknown"
    POSITIVE_CHARGING = "positive_charging"
    POSITIVE_DISCHARGING = "positive_discharging"


@dataclass(frozen=True, slots=True)
class BatteryState:
    """Legacy passive controller contract retained for Build004 compatibility."""

    is_charging: bool | None
    can_charge: bool | None
    soc: float | None
    charge_power_w: float | None
    max_charge_power_w: float | None


@dataclass(frozen=True, slots=True)
class BatteryResource:
    """One normalized battery resource without any command capability."""

    resource_id: str
    name: str
    adapter_id: str
    adapter_version: str
    available: bool
    health: BatteryHealth
    last_updated: datetime | None
    data_age_seconds: float | None
    soc_percent: float | None = None
    charge_power_w: float | None = None
    discharge_power_w: float | None = None
    grid_input_power_w: float | None = None
    max_charge_power_w: float | None = None
    max_discharge_power_w: float | None = None
    remaining_charge_power_w: float | None = None
    charging_allowed: bool | None = None
    charging_state: str | None = None
    full: bool | None = None
    fault: bool | None = None
    autonomous: bool = True
    anomalies: tuple[BatteryReasonCode, ...] = ()
    source_entities: dict[str, str] = field(default_factory=dict)


class BatteryManager(Protocol):
    """Read-only contract; it cannot influence the current controller."""

    async def async_get_state(self) -> BatteryState:
        """Return a latest normalized state without changing the battery."""


class NullBatteryManager:
    """V1 implementation: declares no battery source and performs no I/O."""

    async def async_get_state(self) -> BatteryState:
        return BatteryState(None, None, None, None, None)
