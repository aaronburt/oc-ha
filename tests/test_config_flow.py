"""Tests for the OpenCode config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.opencode_conversation.const import DOMAIN

from .helpers import MODELS_URL, USAGE_URL, create_entry


async def test_user_flow_creates_entry_with_subentries(hass, aioclient_mock):
    """The user flow creates an entry with default subentries."""
    aioclient_mock.get(USAGE_URL, json={"usage": {}})
    aioclient_mock.get(
        MODELS_URL,
        json={"object": "list", "data": [{"id": "deepseek-v4.1-flash"}, {"id": "glm-5.3"}]},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "test-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model": "glm-5.3"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["api_key"] == "test-key"

    subentries = {s.subentry_type: s for s in entry.subentries.values()}
    assert set(subentries) == {"conversation", "ai_task_data"}
    assert subentries["conversation"].data["model"] == "glm-5.3"
    assert subentries["conversation"].data["llm_hass_api"] == ["assist"]
    assert subentries["ai_task_data"].data["model"] == "glm-5.3"


async def test_user_flow_invalid_key(hass, aioclient_mock):
    """An invalid key shows an error."""
    aioclient_mock.get(
        USAGE_URL,
        status=401,
        json={"type": "error", "error": {"type": "AuthError", "message": "Unauthorized"}},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "bad-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_key_aborts(hass, aioclient_mock):
    """The same API key cannot be configured twice."""
    await create_entry(hass, aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "test-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_setup_and_unload(hass, aioclient_mock):
    """The entry sets up conversation and AI task entities and unloads cleanly."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])

    conversation_entities = [
        entity_id
        for entity_id in hass.states.async_entity_ids("conversation")
        if "opencode" in entity_id
    ]
    ai_task_entities = [
        entity_id
        for entity_id in hass.states.async_entity_ids("ai_task")
        if "opencode" in entity_id
    ]
    assert len(conversation_entities) == 1
    assert len(ai_task_entities) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is config_entries.ConfigEntryState.NOT_LOADED
    state = hass.states.get("conversation.opencode_assistant")
    assert state is not None
    assert state.state == "unavailable"
