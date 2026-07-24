"""Acquire and validate local Home Assistant measurements for Build004."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant

from .const import GRID_POWER_MAX_W, GRID_POWER_MIN_W


@dataclass(frozen=True, slots=True)
class GridMeasurement:
    """A validated grid-power value using the integration sign convention."""

    power_w: float | None
    error: str | None
    timestamp: datetime | None = None


class AcquisitionEngine:
    """Read one user-selected local grid-power entity without polling Modbus."""

    def __init__(self, hass: HomeAssistant, entity_id: str, inverted: bool) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._inverted = inverted

    @property
    def entity_id(self) -> str:
        return self._entity_id

    def configure(self, entity_id: str, inverted: bool) -> None:
        """Apply updated integration options."""
        self._entity_id = entity_id
        self._inverted = inverted

    def read_grid_power(self) -> GridMeasurement:
        """Read the current state, rejecting unknown, non-numeric, and outliers."""
        state = self._hass.states.get(self._entity_id)
        if state is None or state.state in {"unknown", "unavailable", "none"}:
            return GridMeasurement(None, "Grid sensor unavailable")
        try:
            power = float(state.state)
        except (TypeError, ValueError):
            return GridMeasurement(None, "Grid sensor value is not numeric")
        if not GRID_POWER_MIN_W <= power <= GRID_POWER_MAX_W:
            return GridMeasurement(None, "Grid sensor value is outside the allowed range")
        return GridMeasurement(
            -power if self._inverted else power,
            None,
            # ``last_changed`` remains frozen while a meter keeps reporting
            # the same numeric value.  ``last_updated`` instead represents
            # the latest state publication known by Home Assistant and avoids
            # rejecting a fresh, stable grid measurement as stale.
            state.last_updated,
        )
