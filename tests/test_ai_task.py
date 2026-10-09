"""Tests for the OpenCode AI Task entity."""

from __future__ import annotations

import probatio
from homeassistant.components import ai_task, conversation

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
