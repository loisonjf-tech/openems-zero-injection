"""Configuration flow for OpenEMS Zero Injection."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    CONF_GRID_POWER_ENTITY_ID,
    CONF_GRID_POWER_INVERTED,
    CONF_INSTALLED_NOMINAL_POWER_W,
    CONF_AUTO_RESUME_PRODUCTION,
    CONF_PRODUCTION_STARTUP_STRATEGY,
    CONF_TAKEOVER_LIMIT_PERCENT,
    CONF_TEMPORARY_LIMIT_VALIDATION_MODE,
    DEFAULT_DTU_PORT,
    DEFAULT_GRID_POWER_ENTITY_ID,
    DEFAULT_GRID_POWER_INVERTED,
    DEFAULT_INSTALLED_NOMINAL_POWER_W,
    DEFAULT_AUTO_RESUME_PRODUCTION,
    DEFAULT_PRODUCTION_STARTUP_STRATEGY,
    DEFAULT_TEMPORARY_LIMIT_VALIDATION_MODE,
    DEFAULT_TAKEOVER_LIMIT_PERCENT,
    MAX_INSTALLED_NOMINAL_POWER_W,
    MIN_INSTALLED_NOMINAL_POWER_W,
    DOMAIN,
)
from .modbus import DtuConnectionError, DtuProSModbusClient


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpenEMSOptionsFlow:
        """Provide the Build004 local grid-sensor selection."""
        return OpenEMSOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the DTU connection and create a configuration entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_DTU_HOST].strip()
            user_input[CONF_DTU_HOST] = host
            try:
                await self._async_test_connection(user_input)
            except DtuConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    f"{host}:{user_input[CONF_DTU_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"DTU Pro-S ({host})", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DTU_HOST): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_DTU_PORT, default=DEFAULT_DTU_PORT): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_test_connection(self, user_input: dict[str, Any]) -> None:
        """Verify the supplied DTU endpoint with the shared Modbus client."""
        client = DtuProSModbusClient(
            user_input[CONF_DTU_HOST], user_input[CONF_DTU_PORT]
        )
        try:
            await client.async_check_connectivity()
        finally:
            await client.async_disconnect()


class OpenEMSOptionsFlow(config_entries.OptionsFlow):
    """Configure local acquisition without storing any cloud credentials."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_GRID_POWER_ENTITY_ID,
                        default=options.get(
                            CONF_GRID_POWER_ENTITY_ID, DEFAULT_GRID_POWER_ENTITY_ID
                        ),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required(
                        CONF_GRID_POWER_INVERTED,
                        default=options.get(
                            CONF_GRID_POWER_INVERTED,
                            DEFAULT_GRID_POWER_INVERTED,
                        ),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_INSTALLED_NOMINAL_POWER_W,
                        default=options.get(
                            CONF_INSTALLED_NOMINAL_POWER_W,
                            DEFAULT_INSTALLED_NOMINAL_POWER_W,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_INSTALLED_NOMINAL_POWER_W,
                            max=MAX_INSTALLED_NOMINAL_POWER_W,
                        ),
                    ),
                    vol.Required(
                        CONF_TEMPORARY_LIMIT_VALIDATION_MODE,
                        default=options.get(
                            CONF_TEMPORARY_LIMIT_VALIDATION_MODE,
                            DEFAULT_TEMPORARY_LIMIT_VALIDATION_MODE,
                        ),
                    ): vol.In(
                        {
                            "compatibility": "Mode compatibilité",
                            "strict": "Mode strict",
                        }
                    ),
                    vol.Required(
                        CONF_PRODUCTION_STARTUP_STRATEGY,
                        default=options.get(
                            CONF_PRODUCTION_STARTUP_STRATEGY,
                            DEFAULT_PRODUCTION_STARTUP_STRATEGY,
                        ),
                    ): vol.In(
                        {
                            "safe": "Mode sécurisé",
                            "takeover": "Prise de contrôle",
                        }
                    ),
                    vol.Required(
                        CONF_TAKEOVER_LIMIT_PERCENT,
                        default=options.get(
                            CONF_TAKEOVER_LIMIT_PERCENT,
                            DEFAULT_TAKEOVER_LIMIT_PERCENT,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=2, max=100)),
                    vol.Required(
                        CONF_AUTO_RESUME_PRODUCTION,
                        default=options.get(
                            CONF_AUTO_RESUME_PRODUCTION,
                            DEFAULT_AUTO_RESUME_PRODUCTION,
                        ),
                    ): selector.BooleanSelector(),
                }
            ),
        )
