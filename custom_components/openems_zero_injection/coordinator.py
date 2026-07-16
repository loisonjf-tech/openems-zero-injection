"""Read-only telemetry coordinator for the Hoymiles DTU Pro-S."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
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
    PORT_PERMANENT_POWER_LIMIT_REGISTERS,
    PORT_TEMPORARY_POWER_LIMIT_REGISTERS,
    RegisterDecodeError,
    decode_dtu_serial,
    decode_power_limit_percent,
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
        # Deliberately reset on every integration startup. The switch is a
        # physical safety interlock, never an automation setting.
        self._manual_writes_enabled = False

    async def _optional_read(self, address: int, count: int) -> list[int] | None:
        try:
            return await self._modbus.async_read_input_registers(address, count)
        except DtuConnectionError as err:
            _LOGGER.warning("DTU register 0x%04X unavailable: %s", address, err)
            return None

    async def _optional_power_limit_read(self, address: int) -> int | None:
        """Read one limit without allowing a bad port to fail the integration."""
        try:
            return decode_power_limit_percent(
                [await self._modbus.async_read_power_limit_register(address)]
            )
        except (DtuConnectionError, RegisterDecodeError) as err:
            _LOGGER.warning("DTU power-limit register 0x%04X unavailable: %s", address, err)
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

        power_limit_values = await self._async_read_all_power_limits()
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
                **power_limit_values,
            )
        except RegisterDecodeError as err:
            _LOGGER.warning("DTU response could not be decoded: %s", err)
            raise UpdateFailed(str(err)) from err

    async def _async_read_all_power_limits(self) -> dict[str, int | None]:
        """Read each approved register independently for Phase A diagnostics."""
        fields: dict[str, int | None] = {}
        for port, address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.items():
            fields[f"port_{port}_temporary_power_limit_percent"] = (
                await self._optional_power_limit_read(address)
            )
        for port, address in PORT_PERMANENT_POWER_LIMIT_REGISTERS.items():
            fields[f"port_{port}_permanent_power_limit_percent"] = (
                await self._optional_power_limit_read(address)
            )
        return fields

    @property
    def manual_writes_enabled(self) -> bool:
        """Return the state of the manual-write safety interlock."""
        return self._manual_writes_enabled

    async def async_set_manual_writes_enabled(self, enabled: bool) -> None:
        """Change only the local manual-write safety interlock."""
        self._manual_writes_enabled = enabled
        _LOGGER.warning(
            "Manual DTU temporary power-limit writes %s",
            "enabled" if enabled else "disabled",
        )
        self.async_update_listeners()

    def active_temporary_power_limit_ports(self) -> tuple[int, ...]:
        """Return ports whose temporary limit was read as a valid percentage."""
        if self.data is None:
            return ()
        return tuple(
            port
            for port in PORT_TEMPORARY_POWER_LIMIT_REGISTERS
            if getattr(self.data, f"port_{port}_temporary_power_limit_percent")
            is not None
        )

    async def async_set_temporary_power_limit(self, port: int, value: int) -> None:
        """Manually set, acknowledge, and immediately re-read one temporary limit."""
        if not self._manual_writes_enabled:
            raise HomeAssistantError("Manual DTU writes are disabled")
        if port not in PORT_TEMPORARY_POWER_LIMIT_REGISTERS:
            raise HomeAssistantError("Unsupported DTU port")
        if not isinstance(value, int) or not 2 <= value <= 100:
            raise HomeAssistantError("DTU power limit must be between 2 and 100%")

        address = PORT_TEMPORARY_POWER_LIMIT_REGISTERS[port]
        _LOGGER.info("Manual temporary DTU power-limit request: port %s, %s%%", port, value)
        try:
            await self._modbus.async_write_temporary_power_limit(address, value)
            confirmed = await self._modbus.async_read_power_limit_register(address)
        except DtuConnectionError as err:
            _LOGGER.error(
                "Manual temporary DTU power-limit write failed for port %s: %s",
                port,
                err,
            )
            raise HomeAssistantError(
                f"DTU temporary power-limit write failed for port {port}: {err}"
            ) from err

        if confirmed != value:
            _LOGGER.error(
                "DTU temporary power-limit verification failed for port %s: requested %s%%, read %s%%",
                port,
                value,
                confirmed,
            )
            raise HomeAssistantError(
                f"DTU did not confirm {value}% for port {port}; read {confirmed}%"
            )

        if self.data is not None:
            self.async_set_updated_data(
                replace(
                    self.data,
                    **{f"port_{port}_temporary_power_limit_percent": confirmed},
                )
            )
        _LOGGER.info(
            "Manual temporary DTU power limit confirmed: port %s, %s%%", port, value
        )

    async def async_shutdown(self) -> None:
        """Close the Modbus client during integration unload."""
        await self._modbus.async_disconnect()
