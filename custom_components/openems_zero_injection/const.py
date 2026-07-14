"""Constants for OpenEMS Zero Injection."""

from datetime import timedelta

DOMAIN = "openems_zero_injection"
NAME = "OpenEMS Zero Injection"
VERSION = "0.1.0"

CONF_DTU_HOST = "dtu_host"
CONF_DTU_PORT = "dtu_port"

DEFAULT_DTU_PORT = 502
PLATFORMS = ("sensor",)
SCAN_INTERVAL = timedelta(seconds=30)
