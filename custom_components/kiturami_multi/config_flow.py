"""Config flow for Kiturami IoT Multi Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from aiohttp import ClientSession
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KrbAuthError, KrbClient, KrbError
from .const import DOMAIN, TITLE

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SCAN_INTERVAL, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
    }
)


async def async_validate_login(
    username: str, password: str, session: ClientSession
) -> dict[str, str]:
    client = KrbClient(username, password, session)
    try:
        await client.async_login()
        devices = await client.async_get_room_devices()
    except KrbAuthError:
        return {"base": "invalid_auth"}
    except KrbError:
        return {"base": "cannot_connect"}
    if not devices:
        return {"base": "no_rooms"}
    return {}


class KituramiMultiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a Multi Manager account."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = await async_validate_login(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            async_get_clientsession(self.hass),
        )
        if errors:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        await self.async_set_unique_id(f"{DOMAIN}_multi_{user_input[CONF_USERNAME]}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"{TITLE} 멀티 ({user_input[CONF_USERNAME]})", data=user_input
        )
