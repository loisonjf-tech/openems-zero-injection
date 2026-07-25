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


ADAPTER_ID = "zendure_solarflow"
ADAPTER_VERSION = "0.5.0-alpha.1"


class ZendureSolarFlowAdapter:
    """Normalize configured HA entity states only; never polls or writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        soc_entity_id: str,
        power_entity_id: str,
        charge_limit_entity_id: str | None,
        power_sign: BatteryPowerSign,
        charge_limit_verified: bool,
        max_age_seconds: int,
    ) -> None:
        self._hass = hass
        self._soc_entity_id = soc_entity_id
        self._power_entity_id = power_entity_id
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
        required_times = [timestamp for timestamp in (soc_time, power_time) if timestamp]
        last_updated = min(required_times) if len(required_times) == 2 else None
        age = (now - last_updated).total_seconds() if last_updated else None

        if any(issue is BatteryReasonCode.SOURCE_UNAVAILABLE for issue in anomalies):
            health = BatteryHealth.UNAVAILABLE
        elif last_updated is None or last_updated <= self._started_at or (
            age is not None and age > self._max_age_seconds
        ):
            anomalies.append(BatteryReasonCode.SOURCE_NOT_REFRESHED if last_updated is None or last_updated <= self._started_at else BatteryReasonCode.DATA_STALE)
            health = BatteryHealth.STALE
        elif any(issue in {BatteryReasonCode.SOC_OUT_OF_RANGE, BatteryReasonCode.POWER_UNIT_UNSUPPORTED, BatteryReasonCode.POWER_NON_FINITE} for issue in anomalies):
            health = BatteryHealth.INCONSISTENT
        else:
            health = BatteryHealth.HEALTHY

        charge_power: float | None = None
        discharge_power: float | None = None
        if power is not None:
            if self._power_sign is BatteryPowerSign.UNKNOWN:
                anomalies.append(BatteryReasonCode.POWER_SIGN_UNKNOWN)
            elif self._power_sign is BatteryPowerSign.POSITIVE_CHARGING:
                charge_power, discharge_power = max(0.0, power), max(0.0, -power)
            else:
                charge_power, discharge_power = max(0.0, -power), max(0.0, power)

        max_charge = self._read_verified_charge_limit(anomalies)
        remaining = None
        if max_charge is not None and charge_power is not None and max_charge >= charge_power:
            remaining = max_charge - charge_power
        else:
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
            max_charge_power_w=max_charge,
            remaining_charge_power_w=remaining,
            anomalies=tuple(dict.fromkeys(anomalies)),
            source_entities={
                "soc_percent": self._soc_entity_id,
                "directional_power_w": self._power_entity_id,
                **({"max_charge_power_w": self._charge_limit_entity_id} if self._charge_limit_entity_id else {}),
            },
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

    def _read_verified_charge_limit(self, anomalies: list[BatteryReasonCode]) -> float | None:
        if not self._charge_limit_entity_id:
            return None
        if not self._charge_limit_verified:
            anomalies.append(BatteryReasonCode.CHARGE_LIMIT_UNVERIFIED)
            return None
        state = self._hass.states.get(self._charge_limit_entity_id)
        value, _, issue = _numeric_state(state, expected_units={"W", "kW"})
        if issue is not None or value is None or value < 0:
            anomalies.append(BatteryReasonCode.CHARGE_LIMIT_INVALID)
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        return value * 1000 if unit == "kW" else value


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
