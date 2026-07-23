"""Config flow for the NETGEAR WAX210 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .api import WAX210AuthError, WAX210Client, WAX210ConnectionError
from .const import (
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
})


async def _validate_login(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Actually attempt a login; raises WAX210AuthError/WAX210ConnectionError on failure."""
    client = WAX210Client(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    await hass.async_add_executor_job(client.login)


class WAX210ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NETGEAR WAX210."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            try:
                await _validate_login(self.hass, user_input)
            except WAX210AuthError:
                errors["base"] = "invalid_auth"
            except WAX210ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating WAX210 login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"WAX210 ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "WAX210OptionsFlow":
        return WAX210OptionsFlow()


class WAX210OptionsFlow(config_entries.OptionsFlow):
    """
    Options: currently just the poll interval.

    Deliberately no __init__ here: current HA versions make
    OptionsFlow.config_entry a read-only property that HA itself sets
    after instantiation -- manually assigning self.config_entry in
    __init__ (the old pattern) now raises AttributeError, which is what
    was causing the "Config flow could not be loaded" 500 error.
    self.config_entry is simply available already in the step methods
    below without ever being set here.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        schema = vol.Schema({
            vol.Optional("scan_interval", default=current): vol.All(int, vol.Range(min=10)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
