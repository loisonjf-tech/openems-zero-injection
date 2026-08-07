"""Read-only telemetry coordinator for the Hoymiles DTU Pro-S."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    CONF_CONTROLLER_MODE,
    CONF_LAST_CONFIRMED_TEMPORARY_LIMIT,
    CONF_LAST_CONFIRMED_TEMPORARY_LIMIT_SOURCE,
    CONF_AUTO_RESUME_PRODUCTION,
    CONF_BATTERY_PRIORITY_CHARGE_THRESHOLD_W,
    CONF_BATTERY_PRIORITY_CONFIRMATION_SAMPLES,
    CONF_BATTERY_PRIORITY_MARGIN_W,
    CONF_BATTERY_PRIORITY_MODE,
    CONF_PERSISTENT_HISTORY_ENABLED,
    CONF_PERSISTENT_HISTORY_RETENTION_DAYS,
    CONF_INSTALLED_NOMINAL_POWER_W,
    CONF_PRODUCTION_STARTUP_STRATEGY,
    CONF_TAKEOVER_LIMIT_PERCENT,
    CONF_TEMPORARY_LIMIT_VALIDATION_MODE,
    CONF_SOLARFLOW_CHARGE_LIMIT_ENTITY_ID,
    CONF_SOLARFLOW_CHARGE_LIMIT_VERIFIED,
    CONF_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID,
    CONF_SOLARFLOW_POWER_ENTITY_ID,
    CONF_SOLARFLOW_POWER_SIGN,
    CONF_SOLARFLOW_SOC_ENTITY_ID,
    CONF_SOLARFLOW_ENABLED,
    DEFAULT_TEMPORARY_LIMIT_VALIDATION_MODE,
    DEFAULT_AUTO_RESUME_PRODUCTION,
    DEFAULT_BATTERY_DATA_MAX_AGE_SECONDS,
    DEFAULT_BATTERY_PRIORITY_CHARGE_THRESHOLD_W,
    DEFAULT_BATTERY_PRIORITY_CONFIRMATION_SAMPLES,
    DEFAULT_BATTERY_PRIORITY_MARGIN_W,
    DEFAULT_BATTERY_PRIORITY_MODE,
    DEFAULT_PERSISTENT_HISTORY_ENABLED,
    DEFAULT_PERSISTENT_HISTORY_RETENTION_DAYS,
    DEFAULT_INSTALLED_NOMINAL_POWER_W,
    DEFAULT_PRODUCTION_STARTUP_STRATEGY,
    DEFAULT_SOLARFLOW_CHARGE_LIMIT_ENTITY_ID,
    DEFAULT_SOLARFLOW_CHARGE_LIMIT_VERIFIED,
    DEFAULT_SOLARFLOW_ENABLED,
    DEFAULT_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID,
    DEFAULT_SOLARFLOW_POWER_ENTITY_ID,
    DEFAULT_SOLARFLOW_POWER_SIGN,
    DEFAULT_SOLARFLOW_SOC_ENTITY_ID,
    DEFAULT_TAKEOVER_LIMIT_PERCENT,
    DOMAIN,
    ALGORITHM_VERSION,
    VERSION,
    ENERGY_SCAN_INTERVAL,
    GENERAL_INFO_SCAN_INTERVAL,
    GLOBAL_TRANSPORT_FAILURES_UNAVAILABLE,
    PERMANENT_LIMIT_SCAN_INTERVAL,
    PERMANENT_LIMIT_FAILURE_BACKOFF,
    POWER_LIMIT_FAILURE_LOG_INTERVAL_SECONDS,
    SCAN_INTERVAL,
    TEMPORARY_LIMIT_SCAN_INTERVAL,
    TEMPORARY_LIMIT_MAX_AGE_SECONDS,
    ControllerMode,
    ProductionStartupStrategy,
    TemporaryLimitValidationMode,
)
from .acquisition import AcquisitionEngine
from .controller import ZeroInjectionController
from .energy_manager import EnergyManager
from .battery import BatteryPowerSign, BatteryResource
from .battery_adapters.zendure_solarflow import ZendureSolarFlowAdapter
from .energy_strategy import BatteryPriorityContext
from .persistent_history import PersistentHistoryRecorder
from .const import (
    CONF_GRID_POWER_ENTITY_ID,
    CONF_GRID_POWER_INVERTED,
    DEFAULT_GRID_POWER_ENTITY_ID,
    DEFAULT_GRID_POWER_INVERTED,
)
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


class _PowerLimitHealth:
    """Last known value and freshness of one independently-read register."""

    def __init__(self) -> None:
        self.value: str | int | float | None = None
        self.last_success: datetime | None = None
        self.available = False
        self.error: str | None = None
        self.last_failure_log_time: float | None = None
        self.consecutive_failures = 0


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
        self._skip_next_options_reload = False
        self._temporary_limit_validation_mode = self._restore_temporary_limit_validation_mode(
            entry
        )
        self._last_confirmed_temporary_limit = self._restore_confirmed_temporary_limit(
            entry
        )
        self._last_confirmed_temporary_limit_source = entry.options.get(
            CONF_LAST_CONFIRMED_TEMPORARY_LIMIT_SOURCE, "unknown"
        )
        if self._last_confirmed_temporary_limit_source == "last_confirmed_command":
            self._last_confirmed_temporary_limit_source = "automatic_correction"
        self._temporary_limits_synchronized = True
        self._last_manual_command_confirmed: datetime | None = None
        self._last_manual_command_error: str | None = None
        self._production_startup_strategy = self._restore_production_startup_strategy(
            entry
        )
        self._takeover_limit_percent = self._restore_takeover_limit_percent(entry)
        self._auto_resume_production = bool(
            entry.options.get(
                CONF_AUTO_RESUME_PRODUCTION, DEFAULT_AUTO_RESUME_PRODUCTION
            )
        )
        installed_power_source = (
            "options"
            if CONF_INSTALLED_NOMINAL_POWER_W in entry.options
            else "initial_configuration"
        )
        self._telemetry_health = {
            field: _PowerLimitHealth()
            for field in (
                "serial_number",
                "inverter_count",
                "meter_count",
                "total_energy_wh",
                "daily_energy_wh",
                "active_power_w",
                "reactive_power_var",
            )
        }
        self._limit_health = {
            address: _PowerLimitHealth()
            for address in (
                *PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values(),
                *PORT_PERMANENT_POWER_LIMIT_REGISTERS.values(),
            )
        }
        self._last_permanent_limit_read: datetime | None = None
        self._permanent_limit_suppressed_until: dict[int, datetime] = {}
        self._last_temporary_limit_read: datetime | None = None
        self._last_energy_read: datetime | None = None
        self._last_general_info_read: datetime | None = None
        self._update_lock = asyncio.Lock()
        self._shutdown = False
        self._consecutive_transport_failures = 0
        self._cycle_timings_ms: dict[str, float | None] = {}
        self._cycle_successes = 0
        self._transport_failed_this_cycle = False
        self._total_register_errors = 0
        self._last_raw_error: str | None = None
        self._last_battery_source_freshness: dict[str, str] = {}
        self.energy_manager = EnergyManager()
        self.persistent_history_recorder = PersistentHistoryRecorder(
            hass,
            enabled=bool(
                entry.options.get(
                    CONF_PERSISTENT_HISTORY_ENABLED,
                    DEFAULT_PERSISTENT_HISTORY_ENABLED,
                )
            ),
            retention_days=int(
                entry.options.get(
                    CONF_PERSISTENT_HISTORY_RETENTION_DAYS,
                    DEFAULT_PERSISTENT_HISTORY_RETENTION_DAYS,
                )
            ),
            integration_version=VERSION,
            algorithm_version=ALGORITHM_VERSION,
        )
        self._solarflow_enabled = bool(
            entry.options.get(CONF_SOLARFLOW_ENABLED, DEFAULT_SOLARFLOW_ENABLED)
        )
        self._solarflow_adapter = ZendureSolarFlowAdapter(
            hass,
            soc_entity_id=entry.options.get(
                CONF_SOLARFLOW_SOC_ENTITY_ID, DEFAULT_SOLARFLOW_SOC_ENTITY_ID
            ),
            power_entity_id=self._solarflow_directional_power_entity_id(entry),
            grid_input_power_entity_id=entry.options.get(
                CONF_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID,
                DEFAULT_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID,
            ) or None,
            charge_limit_entity_id=entry.options.get(
                CONF_SOLARFLOW_CHARGE_LIMIT_ENTITY_ID,
                DEFAULT_SOLARFLOW_CHARGE_LIMIT_ENTITY_ID,
            ) or None,
            power_sign=BatteryPowerSign._value2member_map_.get(
                entry.options.get(CONF_SOLARFLOW_POWER_SIGN),
                BatteryPowerSign(DEFAULT_SOLARFLOW_POWER_SIGN),
            ),
            charge_limit_verified=bool(entry.options.get(
                CONF_SOLARFLOW_CHARGE_LIMIT_VERIFIED,
                DEFAULT_SOLARFLOW_CHARGE_LIMIT_VERIFIED,
            )),
            max_age_seconds=DEFAULT_BATTERY_DATA_MAX_AGE_SECONDS,
        )
        initial_mode, mode_restore_source = self._restore_controller_mode(entry)
        self.controller = ZeroInjectionController(
            hass,
            self,
            AcquisitionEngine(
                hass,
                entry.options.get(CONF_GRID_POWER_ENTITY_ID, DEFAULT_GRID_POWER_ENTITY_ID),
                entry.options.get(CONF_GRID_POWER_INVERTED, DEFAULT_GRID_POWER_INVERTED),
            ),
            installed_nominal_power_w=entry.options.get(
                CONF_INSTALLED_NOMINAL_POWER_W,
                DEFAULT_INSTALLED_NOMINAL_POWER_W,
            ),
            installed_power_source=installed_power_source,
            initial_mode=initial_mode,
            mode_restore_source=mode_restore_source,
            production_startup_strategy=self._production_startup_strategy,
            takeover_limit_percent=self._takeover_limit_percent,
            auto_resume_production=(
                self._auto_resume_production and mode_restore_source == "options"
            ),
            persistent_history_recorder=self.persistent_history_recorder,
        )
        self.controller.energy_policy_engine.set_battery_context_provider(
            self._battery_priority_context
        )
        self.controller.energy_policy_engine.configure_battery_priority(
            mode=entry.options.get(
                CONF_BATTERY_PRIORITY_MODE, DEFAULT_BATTERY_PRIORITY_MODE
            ),
            margin_w=float(entry.options.get(
                CONF_BATTERY_PRIORITY_MARGIN_W,
                DEFAULT_BATTERY_PRIORITY_MARGIN_W,
            )),
            charge_threshold_w=float(entry.options.get(
                CONF_BATTERY_PRIORITY_CHARGE_THRESHOLD_W,
                DEFAULT_BATTERY_PRIORITY_CHARGE_THRESHOLD_W,
            )),
            confirmation_samples=int(entry.options.get(
                CONF_BATTERY_PRIORITY_CONFIRMATION_SAMPLES,
                DEFAULT_BATTERY_PRIORITY_CONFIRMATION_SAMPLES,
            )),
        )

    @staticmethod
    def _solarflow_directional_power_entity_id(entry: ConfigEntry) -> str:
        """Use the confirmed bat_in_out source for pre-alpha.2 default options."""
        configured = entry.options.get(CONF_SOLARFLOW_POWER_ENTITY_ID)
        if configured in {None, DEFAULT_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID}:
            return DEFAULT_SOLARFLOW_POWER_ENTITY_ID
        return configured

    def _battery_priority_context(self) -> BatteryPriorityContext:
        """Expose generic passive battery data to the strategy boundary only."""
        snapshot = self.energy_manager.snapshot()
        return BatteryPriorityContext(
            resources=snapshot.resources,
            total_remaining_charge_power_w=snapshot.total_remaining_charge_power_w,
            remaining_charge_coverage=snapshot.remaining_charge_coverage.status,
        )

    def _log_battery_source_freshness(self, freshness: dict[str, str]) -> None:
        """Log a SolarFlow source transition once, never once per coordinator cycle."""
        for source, state in freshness.items():
            previous = self._last_battery_source_freshness.get(source)
            if state == previous:
                continue
            if state == "fresh":
                _LOGGER.info("SolarFlow source %s is fresh", source)
            elif previous is not None:
                _LOGGER.warning("SolarFlow source %s is %s", source, state)
            else:
                _LOGGER.info("SolarFlow source %s initial state: %s", source, state)
        self._last_battery_source_freshness = dict(freshness)

    @staticmethod
    def _restore_controller_mode(entry: ConfigEntry) -> tuple[ControllerMode, str]:
        """Read a persisted mode safely without ever silently accepting bad data."""
        raw_mode = entry.options.get(CONF_CONTROLLER_MODE)
        if raw_mode is None:
            return ControllerMode.DISABLED, "default"
        if raw_mode == ControllerMode.SIMULATION.value:
            _LOGGER.info("Legacy Simulation mode migrated to Manual")
            return ControllerMode.DISABLED, "legacy_simulation_migrated"
        try:
            return ControllerMode(raw_mode), "options"
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Controller mode fallback to disabled: invalid config-entry option %r",
                raw_mode,
            )
            return ControllerMode.DISABLED, "fallback"

    @staticmethod
    def _restore_temporary_limit_validation_mode(
        entry: ConfigEntry,
    ) -> TemporaryLimitValidationMode:
        """Restore Strict or Compatibility, falling back safely to Compatibility."""
        try:
            return TemporaryLimitValidationMode(
                entry.options.get(
                    CONF_TEMPORARY_LIMIT_VALIDATION_MODE,
                    DEFAULT_TEMPORARY_LIMIT_VALIDATION_MODE,
                )
            )
        except (TypeError, ValueError):
            _LOGGER.warning("Invalid temporary-limit validation mode; using compatibility")
            return TemporaryLimitValidationMode.COMPATIBILITY

    @staticmethod
    def _restore_confirmed_temporary_limit(entry: ConfigEntry) -> int | None:
        """Restore only a previously Modbus-confirmed, safe local limit."""
        value = entry.options.get(CONF_LAST_CONFIRMED_TEMPORARY_LIMIT)
        return value if isinstance(value, int) and 2 <= value <= 100 else None

    @staticmethod
    def _restore_production_startup_strategy(
        entry: ConfigEntry,
    ) -> ProductionStartupStrategy:
        """Restore a safe strategy if an option value is invalid."""
        try:
            return ProductionStartupStrategy(
                entry.options.get(
                    CONF_PRODUCTION_STARTUP_STRATEGY,
                    DEFAULT_PRODUCTION_STARTUP_STRATEGY,
                )
            )
        except (TypeError, ValueError):
            _LOGGER.warning("Invalid Production startup strategy; using safe mode")
            return ProductionStartupStrategy.SAFE

    @staticmethod
    def _restore_takeover_limit_percent(entry: ConfigEntry) -> int:
        """Restore only a documented, safe takeover percentage."""
        value = entry.options.get(
            CONF_TAKEOVER_LIMIT_PERCENT, DEFAULT_TAKEOVER_LIMIT_PERCENT
        )
        return value if isinstance(value, int) and 2 <= value <= 100 else DEFAULT_TAKEOVER_LIMIT_PERCENT

    async def _async_refresh_telemetry(
        self,
        field: str,
        address: int,
        count: int,
        decoder: Callable[[list[int]], str | int | float],
    ) -> str | int | float | None:
        """Refresh one telemetry value without discarding a valid cached value."""
        health = self._telemetry_health[field]
        if self._transport_failed_this_cycle:
            self._mark_stale_after_global_failure(health)
            return health.value
        try:
            registers = await self._modbus.async_read_input_registers(address, count)
            value = decoder(registers)
        except (DtuConnectionError, RegisterDecodeError) as err:
            self._mark_register_failure(address, health, str(err))
            self._mark_transport_failure_if_disconnected()
            return health.value

        self._mark_register_success(address, health, value)
        return value

    async def _async_refresh_power_limit(self, address: int) -> None:
        """Refresh one register while retaining its last valid value on failure."""
        health = self._limit_health[address]
        if self._transport_failed_this_cycle:
            self._mark_stale_after_global_failure(health)
            return
        try:
            raw_value = await self._modbus.async_read_power_limit_register(address)
            _LOGGER.debug("DTU power-limit register 0x%04X raw value: %s", address, raw_value)
            value = decode_power_limit_percent([raw_value])
        except DtuConnectionError as err:
            if (
                address in PORT_PERMANENT_POWER_LIMIT_REGISTERS.values()
                and str(err).startswith("Modbus exception")
            ):
                self._mark_unsupported_permanent_limit(address, None, str(err))
                return
            self._mark_power_limit_failure(address, str(err))
            self._mark_transport_failure_if_disconnected()
            return
        except RegisterDecodeError as err:
            if address in PORT_PERMANENT_POWER_LIMIT_REGISTERS.values():
                self._mark_unsupported_permanent_limit(address, raw_value, str(err))
            else:
                self._mark_power_limit_failure(address, str(err))
            return

        self._mark_register_success(address, health, value)

    def _mark_register_success(
        self, address: int, health: _PowerLimitHealth, value: str | int | float
    ) -> None:
        """Record a valid read and log only a meaningful recovery."""
        recovered = health.error is not None
        health.value = value
        health.last_success = datetime.now(UTC)
        health.available = True
        health.error = None
        health.last_failure_log_time = None
        health.consecutive_failures = 0
        self._cycle_successes += 1
        if recovered:
            _LOGGER.info("DTU register 0x%04X communication restored", address)

    def _mark_power_limit_failure(self, address: int, error: str) -> None:
        self._mark_register_failure(address, self._limit_health[address], error)

    def _mark_unsupported_permanent_limit(
        self, address: int, raw_value: int | None, error: str
    ) -> None:
        """Treat a permanent-register sentinel as optional unavailable data."""
        health = self._limit_health[address]
        full_error = f"{error}; raw value={raw_value}"
        if health.available or health.error != full_error:
            _LOGGER.debug(
                "DTU optional permanent register 0x%04X unavailable: %s",
                address,
                full_error,
            )
        health.value = None
        health.available = False
        health.error = full_error
        health.consecutive_failures += 1

    def _mark_register_failure(
        self, address: int, health: _PowerLimitHealth, error: str
    ) -> None:
        """Mark one register stale, preserving its value and rate-limiting logs."""
        now = monotonic()
        changed = health.available or health.error != error
        if (
            changed
            or health.last_failure_log_time is None
            or now - health.last_failure_log_time >= POWER_LIMIT_FAILURE_LOG_INTERVAL_SECONDS
        ):
            _LOGGER.warning("DTU register 0x%04X unavailable: %s", address, error)
            health.last_failure_log_time = now
        health.available = False
        health.error = error
        health.consecutive_failures += 1
        self._total_register_errors += 1
        self._last_raw_error = error

    def _mark_transport_failure_if_disconnected(self) -> None:
        """Stop this cycle after a socket-level failure; retry next normal cycle."""
        diagnostics = self._modbus.connection_diagnostics()
        if diagnostics.get("connected") is False:
            self._transport_failed_this_cycle = True

    def _mark_stale_after_global_failure(self, health: _PowerLimitHealth) -> None:
        """Mark cached data stale without logging one warning per skipped register."""
        health.available = False
        health.error = self._last_raw_error or "DTU communication failed"
        health.consecutive_failures += 1

    async def _async_update_data(self) -> DtuMeasurements:
        """Serialize coordinator refreshes and reuse the latest complete cache."""
        if self._shutdown:
            raise UpdateFailed("DTU coordinator is shutting down")
        if self._update_lock.locked():
            if self.data is not None:
                return self.data
            raise UpdateFailed("DTU telemetry update already in progress")
        async with self._update_lock:
            return await self._async_update_data_locked()

    async def _async_update_data_locked(self) -> DtuMeasurements:
        """Read the approved registers and decode only confirmed value types."""
        started = monotonic()
        now = datetime.now(UTC)
        batteries: tuple[BatteryResource, ...] = ()
        if self._solarflow_enabled:
            battery = self._solarflow_adapter.read_resource(now)
            self._log_battery_source_freshness(battery.source_freshness)
            batteries = (battery,)
        self.energy_manager.set_batteries(batteries)
        self._cycle_timings_ms = {
            "connection": self._modbus.connection_diagnostics().get(
                "last_connection_time_ms"
            ),
        }
        self._cycle_successes = 0
        self._transport_failed_this_cycle = False
        if self._is_due(self._last_general_info_read, GENERAL_INFO_SCAN_INTERVAL, now):
            phase_started = monotonic()
            serial = await self._async_refresh_telemetry(
                "serial_number", REG_DTU_SERIAL, REG_DTU_SERIAL_COUNT, decode_dtu_serial
            )
            meter = await self._async_refresh_telemetry(
                "meter_count", REG_METER_COUNT, REG_METER_COUNT_COUNT, decode_uint16
            )
            inverter_count = await self._async_refresh_telemetry(
                "inverter_count",
                REG_INVERTER_COUNT,
                REG_INVERTER_COUNT_COUNT,
                decode_uint16,
            )
            self._last_general_info_read = now
            self._cycle_timings_ms["dtu_information"] = (
                monotonic() - phase_started
            ) * 1000
        else:
            serial = self._telemetry_health["serial_number"].value
            meter = self._telemetry_health["meter_count"].value
            inverter_count = self._telemetry_health["inverter_count"].value

        # Fast sequential block: current power and DTU availability.
        phase_started = monotonic()
        active = await self._async_refresh_telemetry(
            "active_power_w",
            REG_TOTAL_ACTIVE_POWER,
            REG_TOTAL_ACTIVE_POWER_COUNT,
            lambda registers: decode_uint32(registers) * ACTIVE_POWER_SCALE,
        )
        reactive = await self._async_refresh_telemetry(
            "reactive_power_var",
            REG_TOTAL_REACTIVE_POWER,
            REG_TOTAL_REACTIVE_POWER_COUNT,
            lambda registers: decode_uint32(registers) * REACTIVE_POWER_SCALE,
        )
        self._cycle_timings_ms["power"] = (monotonic() - phase_started) * 1000

        if self._is_due(self._last_energy_read, ENERGY_SCAN_INTERVAL, now):
            phase_started = monotonic()
            total = await self._async_refresh_telemetry(
                "total_energy_wh", REG_TOTAL_ENERGY, REG_TOTAL_ENERGY_COUNT, decode_uint64
            )
            daily = await self._async_refresh_telemetry(
                "daily_energy_wh", REG_DAILY_ENERGY, REG_DAILY_ENERGY_COUNT, decode_uint64
            )
            self._last_energy_read = now
            self._cycle_timings_ms["energy"] = (monotonic() - phase_started) * 1000
        else:
            total = self._telemetry_health["total_energy_wh"].value
            daily = self._telemetry_health["daily_energy_wh"].value

        power_limit_values = await self._async_refresh_power_limits(now)
        if self._transport_failed_this_cycle and self._cycle_successes == 0:
            self._consecutive_transport_failures += 1
            if (
                self.data is None
                or self._consecutive_transport_failures
                >= GLOBAL_TRANSPORT_FAILURES_UNAVAILABLE
            ):
                self._cycle_timings_ms["total_cycle"] = (monotonic() - started) * 1000
                raise UpdateFailed(self._last_raw_error or "DTU communication failed")
            self._cycle_timings_ms["total_cycle"] = (monotonic() - started) * 1000
            return replace(
                self.data,
                connected=True,
                response_time_ms=self._modbus.connection_diagnostics().get(
                    "last_response_time_ms"
                ),
                last_error=self._last_raw_error or "DTU communication failed",
            )
        if self._cycle_successes == 0:
            error = self._modbus.connection_diagnostics()["last_error"]
            if self.data is None:
                self._cycle_timings_ms["total_cycle"] = (monotonic() - started) * 1000
                raise UpdateFailed(str(error or "DTU communication failed"))
            self._cycle_timings_ms["total_cycle"] = (monotonic() - started) * 1000
            return replace(
                self.data,
                response_time_ms=self._modbus.connection_diagnostics().get(
                    "last_response_time_ms"
                ),
                last_error=str(error or "DTU telemetry data unavailable"),
            )

        self._consecutive_transport_failures = 0

        result = DtuMeasurements(
            connected=True,
            serial_number=serial if isinstance(serial, str) else None,
            inverter_count=inverter_count if isinstance(inverter_count, int) else None,
            meter_count=meter if isinstance(meter, int) else None,
            active_power_w=active if isinstance(active, float) else None,
            reactive_power_var=reactive if isinstance(reactive, float) else None,
            daily_energy_wh=daily if isinstance(daily, int) else None,
            total_energy_wh=total if isinstance(total, int) else None,
            response_time_ms=self._modbus.connection_diagnostics().get(
                "last_response_time_ms"
            ),
            last_success=now,
            last_error=self._last_raw_error if self._transport_failed_this_cycle else None,
            **power_limit_values,
        )
        self._cycle_timings_ms["total_cycle"] = (monotonic() - started) * 1000
        return result

    def async_set_updated_data(self, data: DtuMeasurements) -> None:
        """Measure Home Assistant state publication independently from Modbus I/O."""
        started = monotonic()
        super().async_set_updated_data(data)
        self._cycle_timings_ms["home_assistant_publish"] = (
            monotonic() - started
        ) * 1000

    @staticmethod
    def _is_due(last_read: datetime | None, interval: timedelta, now: datetime) -> bool:
        """Return whether a low-priority register group is due for refresh."""
        return last_read is None or now - last_read >= interval

    async def _async_refresh_power_limits(self, now: datetime) -> dict[str, int | None]:
        """Read control limits slowly and permanent diagnostics more slowly."""
        if self._is_due(
            self._last_temporary_limit_read, TEMPORARY_LIMIT_SCAN_INTERVAL, now
        ):
            phase_started = monotonic()
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values():
                await self._async_refresh_power_limit(address)
            self._last_temporary_limit_read = now
            self._cycle_timings_ms["temporary_limits"] = (
                monotonic() - phase_started
            ) * 1000
        if (
            self._last_permanent_limit_read is None
            or now - self._last_permanent_limit_read >= PERMANENT_LIMIT_SCAN_INTERVAL
        ):
            phase_started = monotonic()
            for address in PORT_PERMANENT_POWER_LIMIT_REGISTERS.values():
                if now < self._permanent_limit_suppressed_until.get(address, now):
                    continue
                await self._async_refresh_power_limit(address)
                health = self._limit_health[address]
                if health.consecutive_failures >= 2:
                    self._permanent_limit_suppressed_until[address] = (
                        now + PERMANENT_LIMIT_FAILURE_BACKOFF
                    )
                    _LOGGER.debug(
                        "DTU permanent register 0x%04X suppressed for 30 minutes after %s failures",
                        address,
                        health.consecutive_failures,
                    )
            self._last_permanent_limit_read = now
            self._cycle_timings_ms["permanent_limits"] = (
                monotonic() - phase_started
            ) * 1000

        return {
            f"port_{port}_temporary_power_limit_percent": self._limit_health[
                address
            ].value
            for port, address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.items()
        } | {
            f"port_{port}_permanent_power_limit_percent": self._limit_health[
                address
            ].value
            for port, address in PORT_PERMANENT_POWER_LIMIT_REGISTERS.items()
        }

    @property
    def temporary_limits_ready(self) -> bool:
        """Return whether cached control limits remain valid during their grace period."""
        values = [
            self._limit_health[address].value
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
        ]
        return (
            all(
                self._limit_health[address].last_success is not None
                and (datetime.now(UTC) - self._limit_health[address].last_success).total_seconds()
                <= TEMPORARY_LIMIT_MAX_AGE_SECONDS
                for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
            )
            and all(value is not None for value in values)
            and len(set(values)) == 1
        )

    @property
    def temporary_limit_validation_mode(self) -> TemporaryLimitValidationMode:
        """Return the configured validation behavior for temporary limits."""
        return self._temporary_limit_validation_mode

    @property
    def compatibility_limit_available(self) -> bool:
        """Return whether Compatibility has a safe value confirmed by a 0x06 echo."""
        return self._last_confirmed_temporary_limit is not None

    @property
    def temporary_limits_synchronized(self) -> bool:
        """Return whether no partial common-limit command is known."""
        return self._temporary_limits_synchronized

    @property
    def last_manual_command_confirmed(self) -> datetime | None:
        """Return the time of the last successful common manual command."""
        return self._last_manual_command_confirmed

    @property
    def last_manual_command_error(self) -> str | None:
        """Return the latest explicit common manual command error."""
        return self._last_manual_command_error

    @property
    def last_confirmed_temporary_limit(self) -> int | None:
        """Return the locally retained all-port limit confirmed by Modbus writes."""
        return self._last_confirmed_temporary_limit

    @property
    def effective_temporary_limit(self) -> int | None:
        """Return the live coherent limit or the confirmed compatibility cache."""
        values = [
            self._limit_health[address].value
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
        ]
        if self.temporary_limits_fresh and all(
            value is not None for value in values
        ) and len(set(values)) == 1:
            return values[0] if isinstance(values[0], int) else None
        if self._temporary_limit_validation_mode is TemporaryLimitValidationMode.COMPATIBILITY:
            return self._last_confirmed_temporary_limit
        return None

    @property
    def temporary_limits_readable(self) -> bool:
        """Return whether all three limits have fresh, successful 0x03 reads."""
        return self.temporary_limits_fresh

    @property
    def temporary_limits_identical(self) -> bool:
        """Return whether the currently retained three values agree."""
        values = [
            self._limit_health[address].value
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
        ]
        return all(value is not None for value in values) and len(set(values)) == 1

    @property
    def temporary_limit_source(self) -> str:
        """Describe whether the active reference is read, confirmed, or absent."""
        if self.temporary_limits_fresh:
            return "modbus_readback"
        if (
            self._temporary_limit_validation_mode
            is TemporaryLimitValidationMode.COMPATIBILITY
            and self.compatibility_limit_available
        ):
            return self._last_confirmed_temporary_limit_source
        return "unknown"

    @property
    def temporary_limits_fresh(self) -> bool:
        """Return whether the three limits were read successfully in this cycle."""
        values = [
            self._limit_health[address].value
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
        ]
        return (
            all(
                self._limit_health[address].available
                for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
            )
            and all(value is not None for value in values)
            and len(set(values)) == 1
        )

    @property
    def temporary_limits_timestamp(self) -> datetime | None:
        """Return the oldest timestamp of the three control-critical limits."""
        timestamps = [
            self._limit_health[address].last_success
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
        ]
        if (
            self._temporary_limit_validation_mode
            is TemporaryLimitValidationMode.COMPATIBILITY
            and self._last_confirmed_temporary_limit is not None
            and self.data is not None
            and not self.temporary_limits_fresh
        ):
            # Compatibility deliberately uses the current DTU cycle timestamp:
            # the limit itself was confirmed by an earlier 0x06 response.
            return self.data.last_success
        if all(timestamps):
            return min(timestamps)
        return None

    @property
    def temporary_limits_confirmation_timestamp(self) -> datetime | None:
        """Return the oldest successful confirmation of the three port limits.

        A confirmation is either a valid ``0x03`` readback or the verified
        ``0x06`` echo retained by Compatibility mode.  This is deliberately
        separate from the coordinator-cycle timestamp so diagnostics can show
        the true age of the limit evidence without causing another read.
        """
        timestamps = [
            self._limit_health[address].last_success
            for address in PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values()
        ]
        return min(timestamps) if all(timestamps) else None

    def power_limit_health(self, address: int) -> dict[str, str | int | None | bool]:
        """Return diagnostics-safe state for a documented power-limit register."""
        health = self._limit_health[address]
        return {
            "value": health.value,
            "available": health.available,
            "last_success": health.last_success.isoformat() if health.last_success else None,
            "last_error": health.error,
            "consecutive_failures": health.consecutive_failures,
        }

    def measurement_health(self, field: str) -> dict[str, str | int | None | bool]:
        """Return freshness information for a standard telemetry measurement."""
        health = self._telemetry_health[field]
        return {
            "value": health.value,
            "available": health.available,
            "last_success": health.last_success.isoformat() if health.last_success else None,
            "last_error": health.error,
            "consecutive_failures": health.consecutive_failures,
        }

    def telemetry_timestamp(self, field: str) -> datetime | None:
        """Return the actual successful-read timestamp of one telemetry field."""
        return self._telemetry_health[field].last_success

    def connection_diagnostics(self) -> dict[str, int | str | None | bool]:
        """Return connection counters from the serialized Modbus client."""
        return {
            **self._modbus.connection_diagnostics(),
            "total_register_errors": self._total_register_errors,
            "last_raw_error": self._last_raw_error,
            "consecutive_transport_failures": self._consecutive_transport_failures,
        }

    @property
    def cycle_timings_ms(self) -> dict[str, float | None]:
        """Return individual Modbus and coordinator durations for diagnostics."""
        return dict(self._cycle_timings_ms)

    @property
    def manual_write_allowed(self) -> bool:
        """Return whether Manual mode owns the one common DTU command."""
        return (
            self.controller.mode is ControllerMode.DISABLED
            and self.data is not None
            and self.data.connected
        )

    @property
    def automatic_write_allowed(self) -> bool:
        """Return whether Production may issue one verified automatic command."""
        return (
            self.controller.mode is ControllerMode.PRODUCTION
            and self.data is not None
            and self.data.connected
            and self._temporary_limits_synchronized
            and (
                self.temporary_limits_fresh
                or (
                    self._temporary_limit_validation_mode
                    is TemporaryLimitValidationMode.COMPATIBILITY
                    and self.compatibility_limit_available
                )
            )
        )

    @property
    def production_startup_strategy(self) -> ProductionStartupStrategy:
        """Return the configured Production initialization strategy."""
        return self._production_startup_strategy

    @property
    def takeover_limit_percent(self) -> int:
        """Return the explicitly configured, safe takeover reference limit."""
        return self._takeover_limit_percent

    @property
    def auto_resume_production(self) -> bool:
        """Return whether an opted-in Production restart may take over again."""
        return self._auto_resume_production

    async def async_set_installed_nominal_power(self, value: float) -> None:
        """Persist a user-configured nominal PV power without DTU I/O."""
        self.controller.set_installed_nominal_power(value, source="entity")
        options = {**self.config_entry.options, CONF_INSTALLED_NOMINAL_POWER_W: int(value)}
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        self.async_update_listeners()

    async def async_set_controller_mode(self, mode: str) -> None:
        """Persist an explicit local mode selection without any Modbus I/O."""
        # Simulation is no longer a user-facing controller mode.  Preserve the
        # safe outcome for a legacy service/automation rather than restoring a
        # hidden virtual control path.
        if mode == ControllerMode.SIMULATION.value:
            mode = ControllerMode.DISABLED.value
        await self.controller.async_set_mode(mode)
        options = {**self.config_entry.options, CONF_CONTROLLER_MODE: mode}
        # The live controller has already applied this explicit mode change.
        # Avoid a needless reload that would interrupt an active scheduler.
        self._skip_next_options_reload = True
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        self.async_update_listeners()

    async def _async_store_confirmed_temporary_limit(
        self, value: int, source: str
    ) -> None:
        """Persist a value only after all requested 0x06 writes were acknowledged."""
        self._last_confirmed_temporary_limit = value
        self._last_confirmed_temporary_limit_source = source
        options = {
            **self.config_entry.options,
            CONF_LAST_CONFIRMED_TEMPORARY_LIMIT: value,
            CONF_LAST_CONFIRMED_TEMPORARY_LIMIT_SOURCE: source,
        }
        self._skip_next_options_reload = True
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)

    async def async_set_manual_temporary_power_limit(self, value: int) -> None:
        """Apply one explicit Manual-mode value to all three temporary ports."""
        if not self.manual_write_allowed:
            raise HomeAssistantError("Manual DTU control is available only in Manual mode")
        if not isinstance(value, int) or not 2 <= value <= 100:
            raise HomeAssistantError("DTU power limit must be between 2 and 100%")
        try:
            await self._async_write_all_temporary_power_limits(
                value,
                require_existing_limit=False,
                source="manual_command",
                allowed_mode=ControllerMode.DISABLED,
                require_readback=False,
            )
        except HomeAssistantError as err:
            self._last_manual_command_error = str(err)
            self._temporary_limits_synchronized = False
            self.controller.scheduler.pause()
            self.async_update_listeners()
            raise
        self._last_manual_command_confirmed = datetime.now(UTC)
        self._last_manual_command_error = None
        self.async_update_listeners()

    async def async_set_all_temporary_power_limits(self, value: int) -> None:
        """Apply one verified automatic temporary limit to all three ports.

        This is the only automatic-write entry point. It intentionally uses no
        retries, restoration write, global register, or permanent register.
        """
        await self._async_write_all_temporary_power_limits(
            value,
            require_existing_limit=True,
            source="automatic_correction",
            allowed_mode=ControllerMode.PRODUCTION,
            require_readback=(
                self._temporary_limit_validation_mode
                is TemporaryLimitValidationMode.STRICT
            ),
        )

    async def async_takeover_temporary_power_limits(self, value: int) -> None:
        """Establish a local reference from three verified 0x06 acknowledgements.

        This deliberately does not issue a 0x03 readback: it is intended only
        for DTUs where those documented temporary holding registers cannot be
        read reliably. It remains unavailable in Strict mode.
        """
        if self._temporary_limit_validation_mode is TemporaryLimitValidationMode.STRICT:
            raise HomeAssistantError("DTU takeover requires Compatibility mode")
        await self._async_write_all_temporary_power_limits(
            value,
            require_existing_limit=False,
            source="takeover_confirmed",
            allowed_mode=ControllerMode.PRODUCTION,
            require_readback=False,
        )

    async def _async_write_all_temporary_power_limits(
        self,
        value: int,
        *,
        require_existing_limit: bool,
        source: str,
        allowed_mode: ControllerMode,
        require_readback: bool,
    ) -> None:
        """Write one safe value to all temporary ports with no retry."""
        if not isinstance(value, int) or not 2 <= value <= 100:
            raise HomeAssistantError("DTU power limit must be between 2 and 100%")

        if self.controller.mode is not allowed_mode:
            raise HomeAssistantError("DTU write is not allowed in the current controller mode")
        if self.data is None or not self.data.connected:
            raise HomeAssistantError("DTU is not connected")
        if require_existing_limit and not self.automatic_write_allowed:
            raise HomeAssistantError(
                "DTU temporary power limits are stale or inconsistent"
            )

        ports_and_addresses = tuple(PORT_TEMPORARY_POWER_LIMIT_REGISTERS.items())
        trace_recorder = self.controller.trace_recorder
        trace_recorder.record_modbus_started()
        _LOGGER.info(
            "%s temporary DTU power-limit request: all ports, %s%%",
            source,
            value,
        )
        confirmed_ports: list[int] = []
        try:
            for port, address in ports_and_addresses:
                await self._modbus.async_write_temporary_power_limit(address, value)
                confirmed_ports.append(port)
                trace_recorder.record_port_result(
                    port=port, address=address, result="confirmed"
                )
            if require_readback:
                confirmed = {
                    address: decode_power_limit_percent(
                        [await self._modbus.async_read_power_limit_register(address)]
                    )
                    for _, address in ports_and_addresses
                }
            else:
                # async_write_temporary_power_limit has already checked the
                # 0x06 echo. Some DTUs cannot reliably re-read 0xD00x.
                confirmed = {address: value for _, address in ports_and_addresses}
        except (DtuConnectionError, RegisterDecodeError) as err:
            failed_ports = [
                port for port, _ in ports_and_addresses if port not in confirmed_ports
            ]
            for port, address in ports_and_addresses:
                if port in failed_ports:
                    trace_recorder.record_port_result(
                        port=port, address=address, result="failed", error=str(err)
                    )
            trace_recorder.finish_modbus(result="failed", error=str(err))
            self._temporary_limits_synchronized = False
            _LOGGER.error(
                "Common temporary DTU power-limit write failed; confirmed ports=%s, failed ports=%s: %s",
                confirmed_ports,
                failed_ports,
                err,
            )
            raise HomeAssistantError(
                "DTU temporary power-limit command failed for ports "
                f"{failed_ports}: {err}"
            ) from err

        if any(read_value != value for read_value in confirmed.values()):
            self._temporary_limits_synchronized = False
            trace_recorder.finish_modbus(result="readback_mismatch", error="readback mismatch")
            _LOGGER.warning(
                "Automatic temporary DTU power-limit verification failed: requested %s%%, read %s",
                value,
                confirmed,
            )
            raise HomeAssistantError("DTU temporary power-limit readback mismatch")

        trace_recorder.finish_modbus(result="confirmed")

        if self.data is not None:
            self.async_set_updated_data(
                replace(
                    self.data,
                    port_1_temporary_power_limit_percent=confirmed[
                        PORT_TEMPORARY_POWER_LIMIT_REGISTERS[1]
                    ],
                    port_2_temporary_power_limit_percent=confirmed[
                        PORT_TEMPORARY_POWER_LIMIT_REGISTERS[2]
                    ],
                    port_3_temporary_power_limit_percent=confirmed[
                        PORT_TEMPORARY_POWER_LIMIT_REGISTERS[3]
                    ],
                )
            )
        now = datetime.now(UTC)
        self._last_temporary_limit_read = now
        for _, address in ports_and_addresses:
            health = self._limit_health[address]
            health.value = value
            health.last_success = now
            # Strict mode has a successful 0x03 readback. Compatibility mode
            # has only the verified 0x06 echo: retain the value locally but
            # never describe it as a fresh register read.
            health.available = require_readback
            health.error = None
            health.last_failure_log_time = None
            health.consecutive_failures = 0
        self._temporary_limits_synchronized = True
        await self._async_store_confirmed_temporary_limit(value, source)
        _LOGGER.info(
            "%s temporary DTU power limit confirmed on all ports: %s%%", source, value
        )

    async def async_shutdown(self) -> None:
        """Close the Modbus client during integration unload."""
        self._shutdown = True
        await self.controller.async_stop()
        async with self._update_lock:
            await self._modbus.async_disconnect()
