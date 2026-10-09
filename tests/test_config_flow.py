"""Tests for the OpenCode config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.opencode_conversation.api import (
    OpenCodeAuthError,
    OpenCodeClient,
    OpenCodeConnectionError,
    OpenCodeError,
)
from custom_components.opencode_conversation.const import DOMAIN

from .helpers import MODELS_URL, USAGE_URL, FakeClient, create_entry


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
    assert "llm_hass_api" not in subentries["conversation"].data
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


async def test_add_conversation_subentry(hass, aioclient_mock):
    """A second conversation agent can be added as a subentry."""
    entry = await create_entry(hass, aioclient_mock)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Second Agent",
            "model": "glm-5.3",
            "custom_model": "",
            "api_family": "auto",
            "llm_hass_api": ["assist"],
            "prompt": "",
            "max_tokens": 512,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert len(entry.subentries) == 3
    added = next(
        subentry
        for subentry in entry.subentries.values()
        if subentry.title == "Second Agent"
    )
    assert added.data["model"] == "glm-5.3"
    assert added.data["max_tokens"] == 512


async def test_reconfigure_conversation_subentry(hass, aioclient_mock):
    """An existing conversation agent can be reconfigured."""
    entry = await create_entry(hass, aioclient_mock)
    subentry = next(
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == "conversation"
    )

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": subentry.subentry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "model": "glm-5.3",
            "custom_model": "",
            "api_family": "auto",
            "llm_hass_api": ["assist"],
            "prompt": "Be brief.",
            "max_tokens": 256,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    updated = entry.subentries[subentry.subentry_id]
    assert updated.data["model"] == "glm-5.3"
    assert updated.data["prompt"] == "Be brief."
    assert updated.data["max_tokens"] == 256


async def test_reauth_flow(hass, aioclient_mock):
    """Reauthentication updates the API key without a new entry."""
    entry = await create_entry(hass, aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["api_key"] == "new-key"


async def test_reconfigure_flow(hass, aioclient_mock):
    """The reconfigure flow updates the API key in place."""
    entry = await create_entry(hass, aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "rotated-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["api_key"] == "rotated-key"


async def test_setup_auth_failure_starts_reauth(hass, aioclient_mock):
    """A rejected key during setup marks the entry and starts reauth."""
    entry = await create_entry(hass, aioclient_mock)

    with patch.object(
        OpenCodeClient,
        "async_validate_key",
        side_effect=OpenCodeAuthError("rejected"),
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(
        flow["context"].get("source") == config_entries.SOURCE_REAUTH
        for flow in flows
    )


async def test_setup_connection_failure_retries(hass, aioclient_mock):
    """A connection error during setup schedules a retry."""
    entry = await create_entry(hass, aioclient_mock)

    with patch.object(
        OpenCodeClient,
        "async_validate_key",
        side_effect=OpenCodeConnectionError("down"),
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_user_flow_model_list_fetch_fails(hass, aioclient_mock):
    """A failed model fetch falls back to the certified model list."""
    aioclient_mock.get(USAGE_URL, json={"usage": {}})
    aioclient_mock.get(MODELS_URL, status=500, json={})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "test-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model"


async def test_reauth_invalid_key(hass, aioclient_mock):
    """An invalid key during reauth shows an error."""
    entry = await create_entry(hass, aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
    )
    with patch.object(
        OpenCodeClient,
        "async_validate_key",
        side_effect=OpenCodeAuthError("nope"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "bad"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_cannot_connect(hass, aioclient_mock):
    """A connection error during reconfigure shows an error."""
    entry = await create_entry(hass, aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    with patch.object(
        OpenCodeClient,
        "async_validate_key",
        side_effect=OpenCodeConnectionError("down"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "new"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_add_ai_task_subentry(hass, aioclient_mock):
    """An AI task entity can be added as a subentry."""
    entry = await create_entry(hass, aioclient_mock)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "ai_task_data"),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Extra Task",
            "model": "glm-5.3",
            "custom_model": "",
            "api_family": "auto",
            "max_tokens": 128,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    added = next(
        subentry
        for subentry in entry.subentries.values()
        if subentry.title == "Extra Task"
    )
    assert added.subentry_type == "ai_task_data"
    assert added.data["model"] == "glm-5.3"


async def test_add_subentry_with_custom_model(hass, aioclient_mock):
    """A custom model ID and API family override are stored as given."""
    entry = await create_entry(hass, aioclient_mock)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Custom Agent",
            "model": "deepseek-v4.1-flash",
            "custom_model": "new-model-x",
            "api_family": "chat",
            "llm_hass_api": [],
            "prompt": "",
            "max_tokens": 256,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    added = next(
        subentry
        for subentry in entry.subentries.values()
        if subentry.title == "Custom Agent"
    )
    assert added.data["model"] == "new-model-x"
    assert added.data["api_family"] == "chat"
    assert "llm_hass_api" not in added.data


async def test_subentry_flow_requires_loaded_entry(hass, aioclient_mock):
    """Subentry flows abort when the entry is not loaded."""
    entry = await create_entry(hass, aioclient_mock)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


async def test_model_step_adds_default_when_missing(hass, aioclient_mock):
    """The default model stays selectable even if absent from the live list."""
    aioclient_mock.get(USAGE_URL, json={"usage": {}})
    aioclient_mock.get(
        MODELS_URL, json={"object": "list", "data": [{"id": "glm-5.3"}]}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "test-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model": "deepseek-v4.1-flash"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reauth_cannot_connect(hass, aioclient_mock):
    """A connection error during reauth shows an error."""
    entry = await create_entry(hass, aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
    )
    with patch.object(
        OpenCodeClient,
        "async_validate_key",
        side_effect=OpenCodeConnectionError("down"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "new"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_invalid_key(hass, aioclient_mock):
    """An invalid key during reconfigure shows an error."""
    entry = await create_entry(hass, aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    with patch.object(
        OpenCodeClient,
        "async_validate_key",
        side_effect=OpenCodeAuthError("nope"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "bad"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_subentry_models_fetch_failure_falls_back(hass, aioclient_mock):
    """Subentry flows fall back to the certified list when fetching fails."""
    entry = await create_entry(hass, aioclient_mock)
    entry.runtime_data = FakeClient(error=OpenCodeError("down"))

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
