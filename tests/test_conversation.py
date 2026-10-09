"""Tests for the OpenCode conversation entity."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.core import Context

from custom_components.opencode_conversation.entity import (
    _content_with_context,
    messages_from_content,
    responses_items_from_content,
)

from .helpers import FakeClient, create_entry

CHAT_EVENTS = [
    {"choices": [{"delta": {"role": "assistant", "content": "Hello"}}]},
    {"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]},
    {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
]

TOOL_EVENTS = [
    [
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "HassTurnOn",
                                    "arguments": '{"name": "Test Light"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ],
    [
        {"choices": [{"delta": {"role": "assistant", "content": "Done"}}]},
        {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]},
    ],
]


async def _converse(hass, text: str) -> conversation.ConversationResult:
    """Send a request to the OpenCode conversation agent."""
    agent_id = next(
        entity_id
        for entity_id in hass.states.async_entity_ids("conversation")
        if "opencode" in entity_id
    )
    return await conversation.async_converse(
        hass, text, None, Context(), "en", agent_id=agent_id
    )


async def test_simple_conversation(hass, aioclient_mock):
    """The agent returns the streamed assistant message."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    fake = FakeClient([CHAT_EVENTS])
    entry.runtime_data = fake

    result = await _converse(hass, "Hi")

    assert result.response.speech["plain"]["speech"] == "Hello world"
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "deepseek-v4.1-flash"
    assert fake.calls[0]["messages"][-1]["content"] == "Hi"

    system_message = fake.calls[0]["messages"][0]
    assert system_message["role"] == "system"
    assert "OpenCode Go" in system_message["content"]
    assert "deepseek-v4.1-flash" in system_message["content"]
    assert "Home Assistant" in system_message["content"]


async def test_tool_call_round_trip(hass, aioclient_mock):
    """Tool calls are executed and the results are sent back to the model."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=["assist"])
    fake = FakeClient(TOOL_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Turn on the test light")

    assert result.response.speech["plain"]["speech"] == "Done!"
    assert len(fake.calls) == 2

    second_call_messages = fake.calls[1]["messages"]
    assert any(
        message.get("role") == "assistant" and message.get("tool_calls")
        for message in second_call_messages
    )
    tool_results = [
        message for message in second_call_messages if message.get("role") == "tool"
    ]
    assert len(tool_results) == 1
    assert tool_results[0]["tool_call_id"] == "call_1"


async def test_context_does_not_override_custom_prompt(hass, aioclient_mock):
    """A custom instructions field is kept and the context line is appended."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    subentry = next(
        sub
        for sub in entry.subentries.values()
        if sub.subentry_type == "conversation"
    )
    data = dict(subentry.data)
    data["prompt"] = "Always answer like a pirate."
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()

    fake = FakeClient([CHAT_EVENTS])
    entry.runtime_data = fake

    await _converse(hass, "Hi")

    system_content = fake.calls[0]["messages"][0]["content"]
    assert "pirate" in system_content
    assert "OpenCode Go" in system_content


def test_context_injected_into_messages_family():
    """The context line is appended to the Messages system prompt."""
    content = [
        conversation.SystemContent(content="Base"),
        conversation.UserContent(content="Hi"),
    ]
    system, messages = messages_from_content(_content_with_context(content, "CTX"))
    assert system == "Base\nCTX"
    assert messages == [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]


def test_context_injected_into_responses_family():
    """The context line is appended to the Responses developer message."""
    content = [conversation.SystemContent(content="Base")]
    items = responses_items_from_content(_content_with_context(content, "CTX"))
    assert items == [{"type": "message", "role": "developer", "content": "Base\nCTX"}]


def test_context_added_when_no_system_message():
    """A system message is created when the chat log has none."""
    items = responses_items_from_content(
        _content_with_context([conversation.UserContent(content="Hi")], "CTX")
    )
    assert items[0] == {"type": "message", "role": "developer", "content": "CTX"}
    assert items[1] == {"type": "message", "role": "user", "content": "Hi"}
