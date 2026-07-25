"""Constants for OpenEMS Zero Injection."""

from datetime import timedelta
from enum import StrEnum

DOMAIN = "openems_zero_injection"
NAME = "OpenEMS Zero Injection"
VERSION = "0.7.0-alpha.2"

CONF_DTU_HOST = "dtu_host"
CONF_DTU_PORT = "dtu_port"
CONF_GRID_POWER_ENTITY_ID = "grid_power_entity_id"
CONF_GRID_POWER_INVERTED = "grid_power_inverted"
CONF_INSTALLED_NOMINAL_POWER_W = "installed_nominal_power_w"
CONF_CONTROLLER_MODE = "controller_mode"
CONF_TEMPORARY_LIMIT_VALIDATION_MODE = "temporary_limit_validation_mode"
CONF_LAST_CONFIRMED_TEMPORARY_LIMIT = "last_confirmed_temporary_limit"
CONF_LAST_CONFIRMED_TEMPORARY_LIMIT_SOURCE = "last_confirmed_temporary_limit_source"
CONF_PRODUCTION_STARTUP_STRATEGY = "production_startup_strategy"
CONF_TAKEOVER_LIMIT_PERCENT = "takeover_limit_percent"
CONF_AUTO_RESUME_PRODUCTION = "auto_resume_production"
CONF_SOLARFLOW_SOC_ENTITY_ID = "solarflow_soc_entity_id"
CONF_SOLARFLOW_POWER_ENTITY_ID = "solarflow_power_entity_id"
CONF_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID = "solarflow_grid_input_power_entity_id"
CONF_SOLARFLOW_CHARGE_LIMIT_ENTITY_ID = "solarflow_charge_limit_entity_id"
CONF_SOLARFLOW_POWER_SIGN = "solarflow_power_sign"
CONF_SOLARFLOW_CHARGE_LIMIT_VERIFIED = "solarflow_charge_limit_verified"
CONF_BATTERY_DATA_MAX_AGE_SECONDS = "battery_data_max_age_seconds"
CONF_SOLARFLOW_ENABLED = "solarflow_enabled"
CONF_BATTERY_PRIORITY_MODE = "battery_priority_mode"
CONF_BATTERY_PRIORITY_MARGIN_W = "battery_priority_margin_w"
CONF_BATTERY_PRIORITY_CHARGE_THRESHOLD_W = "battery_priority_charge_threshold_w"
CONF_BATTERY_PRIORITY_CONFIRMATION_SAMPLES = "battery_priority_confirmation_samples"

DEFAULT_DTU_PORT = 502
DEFAULT_DEVICE_ID = 1
MODBUS_TIMEOUT_SECONDS = 5
MODBUS_RECONNECT_BACKOFF_MAX_SECONDS = 30
PLATFORMS = ("sensor", "number", "select")
SCAN_INTERVAL = timedelta(seconds=10)
ENERGY_SCAN_INTERVAL = timedelta(seconds=30)
TEMPORARY_LIMIT_SCAN_INTERVAL = timedelta(seconds=30)
GENERAL_INFO_SCAN_INTERVAL = timedelta(minutes=5)
PERMANENT_LIMIT_SCAN_INTERVAL = timedelta(minutes=5)
PERMANENT_LIMIT_FAILURE_BACKOFF = timedelta(minutes=30)
POWER_LIMIT_FAILURE_LOG_INTERVAL_SECONDS = 300

DEFAULT_GRID_POWER_ENTITY_ID = "sensor.te31njn2n150704_l3_p"
DEFAULT_GRID_POWER_INVERTED = False
DEFAULT_TARGET_GRID_POWER_W = -40
DEFAULT_DEADBAND_W = 30
DEFAULT_STABILIZATION_DELAY_SECONDS = 12
DEFAULT_INSTALLED_NOMINAL_POWER_W = 3000
MIN_INSTALLED_NOMINAL_POWER_W = 100
MAX_INSTALLED_NOMINAL_POWER_W = 50_000
INSTALLED_NOMINAL_POWER_STEP_W = 10
DEFAULT_MAXIMUM_STEP_PERCENT = 5
DEFAULT_PREDICTIVE_ERROR_THRESHOLD_W = 250
DEFAULT_FINE_CORRECTION_STEP_PERCENT = 2
DEFAULT_TEMPORARY_LIMIT_VALIDATION_MODE = "compatibility"
DEFAULT_PRODUCTION_STARTUP_STRATEGY = "safe"
DEFAULT_TAKEOVER_LIMIT_PERCENT = 100
DEFAULT_AUTO_RESUME_PRODUCTION = False
DEFAULT_SOLARFLOW_SOC_ENTITY_ID = "sensor.solarflow_800_plus_electric_level"
DEFAULT_SOLARFLOW_POWER_ENTITY_ID = "sensor.solarflow_800_plus_bat_in_out"
DEFAULT_SOLARFLOW_GRID_INPUT_POWER_ENTITY_ID = "sensor.solarflow_800_plus_grid_input_power"
DEFAULT_SOLARFLOW_CHARGE_LIMIT_ENTITY_ID = "sensor.solarflow_800_plus_charge_max_limit"
DEFAULT_SOLARFLOW_POWER_SIGN = "positive_discharging"
DEFAULT_SOLARFLOW_CHARGE_LIMIT_VERIFIED = False
DEFAULT_BATTERY_DATA_MAX_AGE_SECONDS = 120
DEFAULT_SOLARFLOW_ENABLED = False
DEFAULT_BATTERY_PRIORITY_MODE = "disabled"
DEFAULT_BATTERY_PRIORITY_MARGIN_W = 25
DEFAULT_BATTERY_PRIORITY_CHARGE_THRESHOLD_W = 50
DEFAULT_BATTERY_PRIORITY_CONFIRMATION_SAMPLES = 3
MIN_BATTERY_PRIORITY_MARGIN_W = 0
MAX_BATTERY_PRIORITY_MARGIN_W = 100
MIN_BATTERY_PRIORITY_CHARGE_THRESHOLD_W = 1
MAX_BATTERY_PRIORITY_CHARGE_THRESHOLD_W = 1_000
MIN_BATTERY_PRIORITY_CONFIRMATION_SAMPLES = 1
MAX_BATTERY_PRIORITY_CONFIRMATION_SAMPLES = 10
GRID_POWER_MIN_W = -20_000
GRID_POWER_MAX_W = 20_000
CONTROLLER_INTERVAL = timedelta(seconds=3)
VALID_GRID_MEASUREMENTS_REQUIRED = 3
GRID_MEASUREMENT_MAX_AGE_SECONDS = 10
DTU_MEASUREMENT_MAX_AGE_SECONDS = 25
TEMPORARY_LIMIT_MAX_AGE_SECONDS = 65
GLOBAL_TRANSPORT_FAILURES_UNAVAILABLE = 3
MEASUREMENT_SYNC_MAX_DIFFERENCE_SECONDS = 25
# A controller decision is only useful after an observable physical change.
# Smaller fluctuations are normal measurement noise and must not create a new
# decision/history entry or cause Home Assistant state churn.
SIGNIFICANT_POWER_CHANGE_W = 30
SIMULATION_DIAGNOSTIC_REFRESH_SECONDS = 300


class ControllerMode(StrEnum):
    """Explicit controller modes; the integration starts disabled."""

    DISABLED = "Disabled"
    SIMULATION = "Simulation"
    PRODUCTION = "Production"


class SchedulerState(StrEnum):
    """States exposed by the safety scheduler."""

    IDLE = "Idle"
    WAITING = "Waiting"
    WRITING = "Writing"
    VERIFYING = "Verifying"
    ERROR = "Error"
    PAUSED = "Paused"


class TemporaryLimitValidationMode(StrEnum):
    """How Production validates temporary DTU power-limit registers."""

    STRICT = "strict"
    COMPATIBILITY = "compatibility"


class ProductionStartupStrategy(StrEnum):
    """How Production establishes a first trustworthy limit reference."""

    SAFE = "safe"
    TAKEOVER = "takeover"
