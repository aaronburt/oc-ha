"""Shared fixtures and helpers for OpenCode tests."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.opencode_conversation.const import (
    CONF_API_FAMILY,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    DOMAIN,
    FAMILY_AUTO,
)

BASE_URL = "https://opencode.ai/zen/go/v1"
USAGE_URL = f"{BASE_URL}/usage"
MODELS_URL = f"{BASE_URL}/models"
CHAT_URL = f"{BASE_URL}/chat/completions"


class FakeClient:
    """Fake OpenCode client returning scripted streaming events."""

    def __init__(self, chat_events: list[list[dict[str, Any]]]) -> None:
        """Initialize the fake client."""
        self.chat_events = chat_events
        self.calls: list[dict[str, Any]] = []

    def stream_chat_completions(self, body: dict[str, Any], session_id=None):
        """Return scripted chat completion events."""
        self.calls.append(body)
        events = self.chat_events.pop(0) if self.chat_events else []

        async def generator():
            for event in events:
                yield event

        return generator()

    async def async_list_models(self) -> list[str]:
        """Return a static model list."""
        return ["deepseek-v4.1-flash", "glm-5.3"]


async def create_entry(
    hass: HomeAssistant,
    aioclient_mock,
    *,
    model: str = "deepseek-v4.1-flash",
    llm_hass_api: list[str] | None = None,
):
    """Create and set up an OpenCode config entry through the config flow."""
    aioclient_mock.get(USAGE_URL, json={"usage": {}})
    aioclient_mock.get(
        MODELS_URL,
        json={"object": "list", "data": [{"id": "deepseek-v4.1-flash"}, {"id": "glm-5.3"}]},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "test-key"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model": model}
    )

    entry = hass.config_entries.async_entries(DOMAIN)[0]

    if llm_hass_api is not None:
        conversation_subentry = next(
            subentry
            for subentry in entry.subentries.values()
            if subentry.subentry_type == "conversation"
        )
        data = dict(conversation_subentry.data)
        data["llm_hass_api"] = llm_hass_api
        hass.config_entries.async_update_subentry(
            entry, conversation_subentry, data=data
        )

    await hass.async_block_till_done()
    if entry.state is config_entries.ConfigEntryState.LOADED:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def default_subentry_data(model: str = "deepseek-v4.1-flash") -> dict[str, Any]:
    """Return default conversation subentry data."""
    return {
        CONF_MODEL: model,
        CONF_MAX_TOKENS: 1024,
        CONF_API_FAMILY: FAMILY_AUTO,
    }
