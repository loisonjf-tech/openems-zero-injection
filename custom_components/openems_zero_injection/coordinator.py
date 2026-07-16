"""Read-only telemetry coordinator for the Hoymiles DTU Pro-S."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN, SCAN_INTERVAL
from .models import DtuMeasurements
from .modbus import DtuConnectionError, DtuProSModbusClient
from .registers import (
    ACTIVE_POWER_SCALE,
    REACTIVE_POWER_SCALE,
    REG_DAILY_ENERGY,
    REG_DAILY_ENERGY_COUNT,
    REG_DTU_SERIAL,
    REG_DTU_SERIAL_COUNT,
    REG_INVERTER_COUNT,
    REG_INVERTER_COUNT_COUNT,
    REG_METER_COUNT,
    REG_METER_COUNT_COUNT,
    REG_TOTAL_ACTIVE_POWER,
    REG_TOTAL_ACTIVE_POWER_COUNT,
    REG_TOTAL_ENERGY,
    REG_TOTAL_ENERGY_COUNT,
    REG_TOTAL_REACTIVE_POWER,
    REG_TOTAL_REACTIVE_POWER_COUNT,
    RegisterDecodeError,
    decode_dtu_serial,
    decode_uint16,
    decode_uint32,
    decode_uint64,
)

_LOGGER = logging.getLogger(__name__)


class DtuProSCoordinator(DataUpdateCoordinator[DtuMeasurements]):
    """Periodically obtain documented, read-only DTU telemetry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self._modbus = DtuProSModbusClient(
            entry.data[CONF_DTU_HOST], entry.data[CONF_DTU_PORT]
        )

    async def _optional_read(self, address: int, count: int) -> list[int] | None:
        try:
            return await self._modbus.async_read_input_registers(address, count)
        except DtuConnectionError as err:
            _LOGGER.warning("DTU register 0x%04X unavailable: %s", address, err)
            return None

    async def _async_update_data(self) -> DtuMeasurements:
        """Read the approved registers and decode only confirmed value types."""
        started = monotonic()
        try:
            inverter_registers = await self._modbus.async_read_input_registers(
                REG_INVERTER_COUNT, REG_INVERTER_COUNT_COUNT
            )
            inverter_count = decode_uint16(inverter_registers)
        except (DtuConnectionError, RegisterDecodeError) as err:
            _LOGGER.warning("DTU communication failed: %s", err)
            raise UpdateFailed(str(err)) from err

        serial = await self._optional_read(REG_DTU_SERIAL, REG_DTU_SERIAL_COUNT)
        meter = await self._optional_read(REG_METER_COUNT, REG_METER_COUNT_COUNT)
        total = await self._optional_read(REG_TOTAL_ENERGY, REG_TOTAL_ENERGY_COUNT)
        daily = await self._optional_read(REG_DAILY_ENERGY, REG_DAILY_ENERGY_COUNT)
        active = await self._optional_read(
            REG_TOTAL_ACTIVE_POWER, REG_TOTAL_ACTIVE_POWER_COUNT
        )
        reactive = await self._optional_read(
            REG_TOTAL_REACTIVE_POWER, REG_TOTAL_REACTIVE_POWER_COUNT
        )
        try:
            return DtuMeasurements(
                connected=True,
                serial_number=decode_dtu_serial(serial) if serial else None,
                inverter_count=inverter_count,
                meter_count=decode_uint16(meter) if meter else None,
                active_power_w=(decode_uint32(active) * ACTIVE_POWER_SCALE if active else None),
                reactive_power_var=(
                    decode_uint32(reactive) * REACTIVE_POWER_SCALE if reactive else None
                ),
                daily_energy_wh=decode_uint64(daily) if daily else None,
                total_energy_wh=decode_uint64(total) if total else None,
                response_time_ms=(monotonic() - started) * 1000,
                last_success=datetime.now(UTC),
                last_error=None,
            )
        except RegisterDecodeError as err:
            _LOGGER.warning("DTU response could not be decoded: %s", err)
            raise UpdateFailed(str(err)) from err

    async def async_shutdown(self) -> None:
        """Close the Modbus client during integration unload."""
        await self._modbus.async_disconnect()
