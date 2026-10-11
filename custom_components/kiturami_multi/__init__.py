"""Kiturami IoT Multi Manager integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KrbAPI, KrbAuthError, KrbClient, KrbError
from .const import PLATFORMS

type KituramiConfigEntry = ConfigEntry[KrbAPI]


async def async_setup_entry(hass: HomeAssistant, entry: KituramiConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    client = KrbClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        async_get_clientsession(hass),
    )
    try:
        await client.async_login()
    except KrbAuthError as ex:
        raise ConfigEntryAuthFailed(f"귀뚜라미 멀티 매니저 인증 실패: {ex}") from ex
    except KrbError as ex:
        raise ConfigEntryNotReady(f"귀뚜라미 멀티 매니저 로그인 실패: {ex}") from ex

    entry.runtime_data = KrbAPI(client)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KituramiConfigEntry) -> bool:
    """Unload the integration."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
