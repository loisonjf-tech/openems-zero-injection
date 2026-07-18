"""Manufacturer-neutral battery abstraction reserved for V1.1.

This module intentionally performs no I/O and is not consulted by the V1
controller. It defines the sole contract that a future battery adapter must
implement, independently of Zendure, Anker, EcoFlow, or Hoymiles APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BatteryState:
    """A normalized, optional battery snapshot supplied by an adapter."""

    is_charging: bool | None
    can_charge: bool | None
    soc: float | None
    charge_power_w: float | None
    max_charge_power_w: float | None


class BatteryManager(Protocol):
    """Read-only contract for a future manufacturer-specific battery adapter."""

    async def async_get_state(self) -> BatteryState:
        """Return the latest normalized state without changing the battery."""


class NullBatteryManager:
    """V1 implementation: declares that no battery source is configured."""

    async def async_get_state(self) -> BatteryState:
        """Return an explicitly unknown state without performing any I/O."""
        return BatteryState(
            is_charging=None,
            can_charge=None,
            soc=None,
            charge_power_w=None,
            max_charge_power_w=None,
        )
