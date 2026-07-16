"""Shared pytest configuration for the custom integration tests."""

from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading this repository's custom integration in every test."""
    yield


@pytest.fixture(autouse=True)
def mock_coordinator_dtu_client():
    """Prevent integration setup from attempting a real DTU connection."""
    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client_class.return_value.async_check_connectivity = AsyncMock(return_value=True)
        client_class.return_value.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client_class.return_value.async_read_power_limit_register = AsyncMock(
            return_value=0
        )
        client_class.return_value.async_write_temporary_power_limit = AsyncMock()
        client_class.return_value.async_disconnect = AsyncMock()
        yield
