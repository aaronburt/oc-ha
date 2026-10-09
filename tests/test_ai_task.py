"""Tests for the OpenCode AI Task entity."""

from __future__ import annotations

import probatio
import pytest
from homeassistant.components import ai_task, conversation
from homeassistant.exceptions import HomeAssistantError

from .helpers import FakeClient, create_entry

STRUCTURED_EVENTS = [
    {
        "choices": [
            {
                "delta": {"role": "assistant", "content": '{"ok": true}'},
                "finish_reason": "stop",
            }
        ]
    }
]


async def test_ai_task_structured_output(hass, aioclient_mock):
    """A structured AI task returns parsed data."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    fake = FakeClient([STRUCTURED_EVENTS])
    entry.runtime_data = fake

    entity = _get_ai_task_entity(hass)
    task = ai_task.GenDataTask(
        name="test_task",
        instructions="Return ok",
        structure=probatio.Schema({probatio.Required("ok"): bool}),
    )
    chat_log = conversation.ChatLog(hass, "test-conversation")
    chat_log.async_add_user_content(conversation.UserContent(content="Return ok"))

    result = await entity._async_generate_data(task, chat_log)

    assert result.data == {"ok": True}
    assert len(fake.calls) == 1
    assert "response_format" in fake.calls[0]


async def test_ai_task_plain_text(hass, aioclient_mock):
    """An unstructured AI task returns plain text."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    fake = FakeClient(
        [
            [
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "All quiet."},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ]
        ]
    )
    entry.runtime_data = fake

    entity = _get_ai_task_entity(hass)
    task = ai_task.GenDataTask(name="summary", instructions="Summarize")
    chat_log = conversation.ChatLog(hass, "test-conversation")
    chat_log.async_add_user_content(conversation.UserContent(content="Summarize"))

    result = await entity._async_generate_data(task, chat_log)

    assert result.data == "All quiet."
    assert "response_format" not in fake.calls[0]


def _get_ai_task_entity(hass):
    """Return the loaded OpenCode AI task entity."""
    component = hass.data["entity_components"]["ai_task"]
    return next(iter(component.entities))


async def test_ai_task_invalid_structured_response(hass, aioclient_mock):
    """Unparseable structured output raises a translatable error."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    fake = FakeClient(
        [
            [
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "not json"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ]
        ]
    )
    entry.runtime_data = fake

    entity = _get_ai_task_entity(hass)
    task = ai_task.GenDataTask(
        name="bad_task",
        instructions="Return ok",
        structure=probatio.Schema({probatio.Required("ok"): bool}),
    )
    chat_log = conversation.ChatLog(hass, "test-conversation")
    chat_log.async_add_user_content(conversation.UserContent(content="Return ok"))

    with pytest.raises(HomeAssistantError) as err:
        await entity._async_generate_data(task, chat_log)

    assert err.value.translation_key == "invalid_structured_response"


async def test_ai_task_structured_messages_family(hass, aioclient_mock):
    """Structured output on the Messages family uses prompt-guided JSON."""
    entry = await create_entry(
        hass, aioclient_mock, model="claude-haiku-5-5", llm_hass_api=[]
    )
    fake = FakeClient(
        message_events=[
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": '{"ok": true}'},
                },
                {"type": "content_block_stop", "index": 0},
            ]
        ]
    )
    entry.runtime_data = fake

    entity = _get_ai_task_entity(hass)
    task = ai_task.GenDataTask(
        name="test_task",
        instructions="Return ok",
        structure=probatio.Schema({probatio.Required("ok"): bool}),
    )
    chat_log = conversation.ChatLog(hass, "test-conversation")
    chat_log.async_add_user_content(conversation.UserContent(content="Return ok"))

    result = await entity._async_generate_data(task, chat_log)

    assert result.data == {"ok": True}
    assert "JSON schema" in fake.calls[0]["system"]
