"""Constants for OpenEMS Zero Injection."""

from datetime import timedelta
from enum import StrEnum

DOMAIN = "openems_zero_injection"
NAME = "OpenEMS Zero Injection"
VERSION = "0.4.0-alpha.1"

CONF_DTU_HOST = "dtu_host"
CONF_DTU_PORT = "dtu_port"
CONF_GRID_POWER_ENTITY_ID = "grid_power_entity_id"
CONF_GRID_POWER_INVERTED = "grid_power_inverted"
CONF_INSTALLED_NOMINAL_POWER_W = "installed_nominal_power_w"
CONF_CONTROLLER_MODE = "controller_mode"

DEFAULT_DTU_PORT = 502
DEFAULT_DEVICE_ID = 1
MODBUS_TIMEOUT_SECONDS = 5
MODBUS_RECONNECT_BACKOFF_MAX_SECONDS = 30
PLATFORMS = ("sensor", "number", "switch", "select")
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
