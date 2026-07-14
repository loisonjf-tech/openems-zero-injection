"""Tests for the OpenEMS Zero Injection configuration flow."""

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.openems_zero_injection.const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    DEFAULT_DTU_PORT,
    DOMAIN,
)
from custom_components.openems_zero_injection.modbus import DtuConnectionError


async def test_user_flow_creates_config_entry_after_connection_check(hass) -> None:
    """The UI flow validates the DTU before storing its connection settings."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.openems_zero_injection.config_flow.DtuProSModbusClient"
    ) as client_class:
        client = client_class.return_value
        client.async_check_connectivity = AsyncMock(return_value=True)
        client.async_disconnect = AsyncMock()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: DEFAULT_DTU_PORT},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "DTU Pro-S (192.0.2.10)"
    assert result["data"] == {
        CONF_DTU_HOST: "192.0.2.10",
        CONF_DTU_PORT: DEFAULT_DTU_PORT,
    }
    client.async_check_connectivity.assert_awaited_once()
    client.async_disconnect.assert_awaited_once()


async def test_user_flow_reports_cannot_connect(hass) -> None:
    """The UI flow reports a DTU connectivity failure without creating an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    with patch(
        "custom_components.openems_zero_injection.config_flow.DtuProSModbusClient"
    ) as client_class:
        client = client_class.return_value
        client.async_check_connectivity = AsyncMock(
            side_effect=DtuConnectionError("Connection failed")
        )
        client.async_disconnect = AsyncMock()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: DEFAULT_DTU_PORT},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    client.async_disconnect.assert_awaited_once()


async def test_user_flow_recovers_after_cannot_connect(hass) -> None:
    """A retry after a connection failure can create the configuration entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    with patch(
        "custom_components.openems_zero_injection.config_flow.DtuProSModbusClient"
    ) as client_class:
        client = client_class.return_value
        client.async_check_connectivity = AsyncMock(
            side_effect=[DtuConnectionError("Connection failed"), True]
        )
        client.async_disconnect = AsyncMock()

        failed_result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: DEFAULT_DTU_PORT},
        )
        recovered_result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: DEFAULT_DTU_PORT},
        )

    assert failed_result["type"] is FlowResultType.FORM
    assert failed_result["errors"] == {"base": "cannot_connect"}
    assert recovered_result["type"] is FlowResultType.CREATE_ENTRY
    assert recovered_result["title"] == "DTU Pro-S (192.0.2.10)"
    assert client.async_disconnect.await_count == 2


async def test_user_flow_prevents_duplicate_dtu(hass) -> None:
    """The same DTU endpoint cannot be configured twice."""
    with patch(
        "custom_components.openems_zero_injection.config_flow.DtuProSModbusClient"
    ) as client_class:
        client = client_class.return_value
        client.async_check_connectivity = AsyncMock(return_value=True)
        client.async_disconnect = AsyncMock()

        first = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        await hass.config_entries.flow.async_configure(
            first["flow_id"], {CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
        )

        second = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            second["flow_id"], {CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
