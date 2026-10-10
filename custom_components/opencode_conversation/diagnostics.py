"""Diagnostics support for the OpenCode integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_PROMPT
from homeassistant.core import HomeAssistant

from .api import OpenCodeClient, OpenCodeError
from .const import CERTIFIED_MODELS, INTEGRATION_VERSION

REDACTED = "**REDACTED**"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for an OpenCode config entry."""
    client: OpenCodeClient = entry.runtime_data

    diagnostics: dict[str, Any] = {
        "integration_version": INTEGRATION_VERSION,
        "entry": {
            "title": entry.title,
            "data": {
                key: REDACTED if key == CONF_API_KEY else value
                for key, value in entry.data.items()
            },
            "subentries": [
                {
                    "subentry_type": subentry.subentry_type,
                    "title": subentry.title,
                    "data": {
                        key: REDACTED if key == CONF_PROMPT else value
                        for key, value in subentry.data.items()
                    },
                }
                for subentry in entry.subentries.values()
            ],
        },
        "certified_models": dict(sorted(CERTIFIED_MODELS.items())),
    }

    try:
        diagnostics["available_models"] = await client.async_list_models()
        diagnostics["usage"] = await client.async_get_usage()
    except OpenCodeError as err:
        diagnostics["api_error"] = str(err)

    return diagnostics
