"""The OpenCode integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import OpenCodeAuthError, OpenCodeClient, OpenCodeError

PLATFORMS = (Platform.CONVERSATION, Platform.AI_TASK)

type OpenCodeConfigEntry = ConfigEntry[OpenCodeClient]


async def async_update_options(hass: HomeAssistant, entry: OpenCodeConfigEntry) -> None:
    """Reload the entry when its configuration changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: OpenCodeConfigEntry) -> bool:
    """Set up OpenCode from a config entry."""
    client = OpenCodeClient(hass, entry.data[CONF_API_KEY])

    try:
        await client.async_validate_key()
    except OpenCodeAuthError as err:
        raise ConfigEntryAuthFailed("Invalid OpenCode API key") from err
    except OpenCodeError as err:
        raise ConfigEntryNotReady("Unable to connect to OpenCode") from err

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenCodeConfigEntry) -> bool:
    """Unload an OpenCode config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
