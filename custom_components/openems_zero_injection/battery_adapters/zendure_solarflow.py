"""Read-only Home Assistant state adapter for Zendure SolarFlow."""

from __future__ import annotations

from datetime import UTC, datetime
import math

from homeassistant.core import HomeAssistant, State
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN

from ..battery import (
    BatteryHealth,
    BatteryPowerSign,
    BatteryReasonCode,
    BatteryResource,
)
from ..const import DEFAULT_SOLARFLOW_SOC_MAX_AGE_SECONDS, VERSION


ADAPTER_ID = "zendure_solarflow"
ADAPTER_VERSION = VERSION
BAT_IN_OUT_ENTITY_ID = "sensor.solarflow_800_plus_bat_in_out"


class ZendureSolarFlowAdapter:
    """Normalize configured HA entity states only; never polls or writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        soc_entity_id: str,
        power_entity_id: str,
        grid_input_power_entity_id: str | None,
        charge_limit_entity_id: str | None,
        power_sign: BatteryPowerSign,
        charge_limit_verified: bool,
        max_age_seconds: int,
    ) -> None:
        self._hass = hass
        self._soc_entity_id = soc_entity_id
        self._power_entity_id = power_entity_id
        self._grid_input_power_entity_id = grid_input_power_entity_id
        self._charge_limit_entity_id = charge_limit_entity_id
        self._power_sign = power_sign
        self._charge_limit_verified = charge_limit_verified
        self._max_age_seconds = max_age_seconds
        self._started_at = datetime.now(UTC)

    def read_resource(self, now: datetime | None = None) -> BatteryResource:
        """Build one passive resource from current HA state machine values."""
        now = now or datetime.now(UTC)
        anomalies: list[BatteryReasonCode] = []
        soc, soc_time, soc_issue = self._read_soc()
        power, power_time, power_issue = self._read_power()
        for issue in (soc_issue, power_issue):
            if issue is not None:
                anomalies.append(issue)
        # Directional power is the only operationally required SolarFlow value:
        # it determines whether the battery is currently charging or
        # discharging. SOC is intentionally a slower, optional state signal.
        last_updated = power_time
        age = (now - last_updated).total_seconds() if last_updated else None
        source_timestamps = {
            "soc_percent": soc_time,
            "directional_power_w": power_time,
        }
        source_max_ages = {
            "soc_percent": DEFAULT_SOLARFLOW_SOC_MAX_AGE_SECONDS,
            "directional_power_w": self._max_age_seconds,
        }
        (
            grid_input_power,
            grid_input_time,
            grid_input_issue,
        ) = self._read_grid_input_power()
        if self._grid_input_power_entity_id:
            source_timestamps["grid_input_power_w"] = grid_input_time
            source_max_ages["grid_input_power_w"] = self._max_age_seconds
        source_ages = {
            source: _source_age(now, timestamp)
            for source, timestamp in source_timestamps.items()
        }
        source_freshness = {
            source: _source_freshness(
                timestamp=timestamp,
                age_seconds=source_ages[source],
                issue={
                    "soc_percent": soc_issue,
                    "directional_power_w": power_issue,
                    "grid_input_power_w": grid_input_issue,
                }.get(source),
                started_at=self._started_at,
                max_age_seconds=source_max_ages[source],
            )
            for source, timestamp in source_timestamps.items()
        }

        for freshness in source_freshness.values():
            if freshness == "not_refreshed":
                anomalies.append(BatteryReasonCode.SOURCE_NOT_REFRESHED)
            elif freshness == "stale":
                anomalies.append(BatteryReasonCode.DATA_STALE)

        # The optional SOC and diagnostic grid-input source can be stale or
        # unavailable without invalidating a fresh directional-power sample.
        if power_issue is BatteryReasonCode.SOURCE_UNAVAILABLE:
            health = BatteryHealth.UNAVAILABLE
        elif source_freshness["directional_power_w"] in {"not_refreshed", "stale"}:
            health = BatteryHealth.STALE
        elif power_issue in {
            BatteryReasonCode.POWER_UNIT_UNSUPPORTED,
            BatteryReasonCode.POWER_NON_FINITE,
        }:
            health = BatteryHealth.INCONSISTENT
        else:
            health = BatteryHealth.HEALTHY

        charge_power: float | None = None
        discharge_power: float | None = None
        if power is not None:
            if self._power_entity_id == BAT_IN_OUT_ENTITY_ID:
                # Confirmed SolarFlow convention: negative = charging,
                # positive = discharging, and zero = inactive.
                charge_power, discharge_power = max(0.0, -power), max(0.0, power)
            elif self._power_sign is BatteryPowerSign.UNKNOWN:
                anomalies.append(BatteryReasonCode.POWER_SIGN_UNKNOWN)
            elif self._power_sign is BatteryPowerSign.POSITIVE_CHARGING:
                charge_power, discharge_power = max(0.0, power), max(0.0, -power)
            else:
                charge_power, discharge_power = max(0.0, -power), max(0.0, power)

        if grid_input_issue is not None:
            anomalies.append(
                BatteryReasonCode.GRID_INPUT_POWER_UNAVAILABLE
                if grid_input_issue is BatteryReasonCode.SOURCE_UNAVAILABLE
                else BatteryReasonCode.GRID_INPUT_POWER_INVALID
            )
        # chargeMaxLimit is confirmed not to describe a usable charge-power
        # ceiling on this installation. Do not derive a capacity from it.
        max_charge = None
        remaining = None
        anomalies.append(BatteryReasonCode.REMAINING_POWER_UNAVAILABLE)

        return BatteryResource(
            resource_id=ADAPTER_ID,
            name="Zendure SolarFlow",
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            available=health is not BatteryHealth.UNAVAILABLE,
            health=health,
            last_updated=last_updated,
            data_age_seconds=max(0.0, age) if age is not None else None,
            soc_percent=soc,
            charge_power_w=charge_power,
            discharge_power_w=discharge_power,
            grid_input_power_w=grid_input_power,
            max_charge_power_w=max_charge,
            remaining_charge_power_w=remaining,
            anomalies=tuple(dict.fromkeys(anomalies)),
            source_entities={
                "soc_percent": self._soc_entity_id,
                "directional_power_w": self._power_entity_id,
                **(
                    {"grid_input_power_w": self._grid_input_power_entity_id}
                    if self._grid_input_power_entity_id
                    else {}
                ),
            },
            source_timestamps=source_timestamps,
            source_ages_seconds=source_ages,
            source_max_age_seconds=source_max_ages,
            source_freshness=source_freshness,
        )

    def _read_soc(self) -> tuple[float | None, datetime | None, BatteryReasonCode | None]:
        state = self._hass.states.get(self._soc_entity_id)
        value, timestamp, issue = _numeric_state(state, expected_units={"%"})
        if issue is not None:
            return None, timestamp, issue
        if value is None or not 0 <= value <= 100:
            return None, timestamp, BatteryReasonCode.SOC_OUT_OF_RANGE
        return value, timestamp, None

    def _read_power(self) -> tuple[float | None, datetime | None, BatteryReasonCode | None]:
        state = self._hass.states.get(self._power_entity_id)
        value, timestamp, issue = _numeric_state(
            state, expected_units={"W", "kW"}
        )
        if issue is not None or value is None:
            return value, timestamp, issue
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        return (value * 1000 if unit == "kW" else value), timestamp, None

    def _read_grid_input_power(
        self,
    ) -> tuple[float | None, datetime | None, BatteryReasonCode | None]:
        """Read optional gridInputPower only for diagnostics and coherence."""
        if not self._grid_input_power_entity_id:
            return None, None, None
        state = self._hass.states.get(self._grid_input_power_entity_id)
        value, timestamp, issue = _numeric_state(state, expected_units={"W", "kW"})
        if issue is not None or value is None:
            return None, timestamp, issue
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        return value * 1000 if unit == "kW" else value, timestamp, None


def _numeric_state(
    state: State | None, *, expected_units: set[str]
) -> tuple[float | None, datetime | None, BatteryReasonCode | None]:
    if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
        return None, None, BatteryReasonCode.SOURCE_UNAVAILABLE
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None, state.last_updated, BatteryReasonCode.SOURCE_UNAVAILABLE
    if not math.isfinite(value):
        return None, state.last_updated, BatteryReasonCode.POWER_NON_FINITE
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if unit is not None and unit not in expected_units:
        return None, state.last_updated, BatteryReasonCode.POWER_UNIT_UNSUPPORTED
    return value, state.last_updated.astimezone(UTC), None


def _source_age(now: datetime, timestamp: datetime | None) -> float | None:
    """Return a non-negative source age without modifying entity state."""
    return max(0.0, (now - timestamp).total_seconds()) if timestamp else None


def _source_freshness(
    *,
    timestamp: datetime | None,
    age_seconds: float | None,
    issue: BatteryReasonCode | None,
    started_at: datetime,
    max_age_seconds: int,
) -> str:
    """Expose why one required source is fresh or unusable.

    This does not alter the existing global BatteryHealth policy. It makes the
    oldest required source visible so a stale aggregate can be diagnosed
    without guessing whether the adapter or the source integration is late.
    """
    if issue is BatteryReasonCode.SOURCE_UNAVAILABLE:
        return "unavailable"
    if issue is not None:
        return "invalid"
    if timestamp is None or timestamp <= started_at:
        return "not_refreshed"
    if age_seconds is None or age_seconds > max_age_seconds:
        return "stale"
    return "fresh"
