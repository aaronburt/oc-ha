"""Shared fixtures and helpers for OpenCode tests."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.opencode_conversation.const import (
    DOMAIN,
)

BASE_URL = "https://opencode.ai/zen/go/v1"
USAGE_URL = f"{BASE_URL}/usage"
MODELS_URL = f"{BASE_URL}/models"
CHAT_URL = f"{BASE_URL}/chat/completions"


class FakeClient:
    """Fake OpenCode client returning scripted streaming events."""

    def __init__(
        self,
        chat_events: list[list[dict[str, Any]]] | None = None,
        message_events: list[list[dict[str, Any]]] | None = None,
        response_events: list[list[dict[str, Any]]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Initialize the fake client."""
        self.chat_events = list(chat_events or [])
        self.message_events = list(message_events or [])
        self.response_events = list(response_events or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def _scripted(self, events: list[list[dict[str, Any]]]):
        if self.error is not None:
            raise self.error
        scripted = events.pop(0) if events else []

        async def generator():
            for event in scripted:
                yield event

        return generator()

    def stream_chat_completions(self, body: dict[str, Any], session_id=None):
        """Return scripted chat completion events."""
        self.calls.append(body)
        return self._scripted(self.chat_events)

    def stream_messages(self, body: dict[str, Any], session_id=None):
        """Return scripted Anthropic Messages events."""
        self.calls.append(body)
        return self._scripted(self.message_events)

    def stream_responses(self, body: dict[str, Any], session_id=None):
        """Return scripted OpenAI Responses events."""
        self.calls.append(body)
        return self._scripted(self.response_events)

    async def async_list_models(self) -> list[str]:
        """Return a static model list."""
        if self.error is not None:
            raise self.error
        return ["deepseek-v4.1-flash", "glm-5.3"]

    async def async_get_usage(self) -> dict[str, Any]:
        """Return empty usage data."""
        if self.error is not None:
            raise self.error
        return {"usage": {}}


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
        json={
            "object": "list",
            "data": [
                {"id": "claude-haiku-5-5"},
                {"id": "deepseek-v4.1-flash"},
                {"id": "glm-5.3"},
                {"id": "gpt-6-luna"},
            ],
        },
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
