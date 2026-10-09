"""Tests for the OpenCode conversation entity."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.core import Context

from custom_components.opencode_conversation.api import (
    OpenCodeAuthError,
    OpenCodeError,
    OpenCodeModelUnavailable,
    OpenCodeRateLimited,
)
from custom_components.opencode_conversation.const import DOMAIN
from custom_components.opencode_conversation.entity import (
    _content_with_context,
    messages_from_content,
    responses_items_from_content,
)

from .helpers import FakeClient, create_entry

CHAT_EVENTS = [
    {"choices": [{"delta": {"role": "assistant", "content": "Hello"}}]},
    {
        "choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    },
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


def _conversation_entity(hass):
    """Return the loaded OpenCode conversation entity."""
    component = hass.data["entity_components"]["conversation"]
    return next(
        entity for entity in component.entities if "opencode" in entity.entity_id
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
    assert _conversation_entity(hass).supported_languages == "*"


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


MESSAGE_EVENTS = [
    [
        {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": " Claude"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]
]

MESSAGE_TOOL_EVENTS = [
    [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Checking"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "HassTurnOn",
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"name": "QA Test Light"}',
            },
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "content_block_start",
            "index": 2,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_2",
                "name": "HassTurnOn",
            },
        },
        {
            "type": "content_block_delta",
            "index": 2,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"name": "QA Test Light"}',
            },
        },
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ],
    [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Done"},
        },
        {"type": "content_block_stop", "index": 0},
    ],
]

RESPONSE_EVENTS = [
    [
        {
            "type": "response.output_item.added",
            "item": {"id": "msg_1", "type": "message", "status": "in_progress"},
        },
        {"type": "response.output_text.delta", "delta": "Hello"},
        {"type": "response.output_text.delta", "delta": " GPT"},
        {
            "type": "response.completed",
            "response": {"usage": {"input_tokens": 4, "output_tokens": 2}},
        },
    ]
]


async def test_messages_family_conversation(hass, aioclient_mock):
    """A Messages-family model talks through the adapter."""
    entry = await create_entry(hass, aioclient_mock, model="claude-haiku-5-5", llm_hass_api=[])
    fake = FakeClient(message_events=MESSAGE_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Hi")

    assert result.response.speech["plain"]["speech"] == "Hello Claude"
    assert fake.calls[0]["model"] == "claude-haiku-5-5"
    assert "OpenCode Go" in fake.calls[0]["system"]


async def test_messages_family_tool_loop(hass, aioclient_mock):
    """Tool calls from the Messages adapter are executed and fed back."""
    entry = await create_entry(hass, aioclient_mock, model="claude-haiku-5-5", llm_hass_api=["assist"])
    fake = FakeClient(message_events=MESSAGE_TOOL_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Turn on the QA Test Light")

    assert result.response.speech["plain"]["speech"] == "Done"
    assert len(fake.calls) == 2

    assistant_messages = [
        message
        for message in fake.calls[1]["messages"]
        if message["role"] == "assistant"
    ]
    blocks = assistant_messages[0]["content"]
    assert any(
        block.get("type") == "text" and block.get("text") == "Checking"
        for block in blocks
    )
    assert sum(1 for block in blocks if block.get("type") == "tool_use") == 2

    tool_results = [
        block
        for message in fake.calls[1]["messages"]
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 2
    assert tool_results[0]["tool_use_id"] == "toolu_1"


async def test_responses_family_conversation(hass, aioclient_mock):
    """A Responses-family model talks through the adapter."""
    entry = await create_entry(hass, aioclient_mock, model="gpt-6-luna", llm_hass_api=[])
    fake = FakeClient(response_events=RESPONSE_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Hi")

    assert result.response.speech["plain"]["speech"] == "Hello GPT"
    assert fake.calls[0]["model"] == "gpt-6-luna"
    first_item = fake.calls[0]["input"][0]
    assert first_item["role"] == "developer"
    assert "OpenCode Go" in first_item["content"]


async def test_model_unavailable_translated(hass, aioclient_mock):
    """An unavailable model maps to a translatable error."""
    await create_entry(hass, aioclient_mock, llm_hass_api=[])
    entity = _conversation_entity(hass)

    error = entity._async_api_error(
        OpenCodeModelUnavailable("gone"), "deepseek-v4.1-flash"
    )

    assert error.translation_key == "model_unavailable"
    assert error.translation_placeholders == {"model": "deepseek-v4.1-flash"}


async def test_rate_limit_translated(hass, aioclient_mock):
    """Rate limits map to translatable errors with retry information."""
    await create_entry(hass, aioclient_mock, llm_hass_api=[])
    entity = _conversation_entity(hass)

    error = entity._async_api_error(
        OpenCodeRateLimited("limit", retry_after=42), "glm-5.3"
    )
    assert error.translation_key == "rate_limit_retry"
    assert error.translation_placeholders == {"model": "glm-5.3", "seconds": "42"}

    error = entity._async_api_error(OpenCodeRateLimited("limit"), "glm-5.3")
    assert error.translation_key == "rate_limit"

    error = entity._async_api_error(OpenCodeError("boom"), "glm-5.3")
    assert error.translation_key == "api_error"


async def test_auth_error_starts_reauth(hass, aioclient_mock):
    """An auth error starts the reauthentication flow."""
    await create_entry(hass, aioclient_mock, llm_hass_api=[])
    entity = _conversation_entity(hass)

    error = entity._async_api_error(OpenCodeAuthError("bad key"), "glm-5.3")

    assert error.translation_key == "authentication_error"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"].get("source") == "reauth" for flow in flows)


CHAT_THINKING_EVENTS = [
    {"choices": [{"delta": {"role": "assistant", "reasoning_content": "hmm"}}]},
    {"choices": [{"delta": {"content": "Answer"}, "finish_reason": "stop"}]},
]

RESPONSE_TOOL_EVENTS = [
    [
        {
            "type": "response.output_item.added",
            "item": {"id": "rs_1", "type": "reasoning", "status": "in_progress"},
        },
        {
            "type": "response.output_item.done",
            "item": {"id": "rs_1", "type": "reasoning", "encrypted_content": "enc123"},
        },
        {
            "type": "response.output_item.added",
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_9",
                "name": "HassTurnOn",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "delta": '{"name": "QA Test Light"}',
        },
        {
            "type": "response.output_item.done",
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_9",
                "name": "HassTurnOn",
                "arguments": '{"name": "QA Test Light"}',
            },
        },
    ],
    [
        {
            "type": "response.output_item.added",
            "item": {"id": "msg_2", "type": "message", "status": "in_progress"},
        },
        {"type": "response.output_text.delta", "delta": "Done"},
        {
            "type": "response.completed",
            "response": {"usage": {"input_tokens": 1, "output_tokens": 1}},
        },
    ],
]


async def test_chat_reasoning_content(hass, aioclient_mock):
    """Reasoning content from the model is tolerated and text is returned."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    entry.runtime_data = FakeClient([CHAT_THINKING_EVENTS])

    result = await _converse(hass, "Hi")

    assert result.response.speech["plain"]["speech"] == "Answer"


async def test_responses_family_tool_loop(hass, aioclient_mock):
    """Responses tool calls and reasoning items are replayed correctly."""
    entry = await create_entry(hass, aioclient_mock, model="gpt-6-luna", llm_hass_api=["assist"])
    fake = FakeClient(response_events=RESPONSE_TOOL_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Turn on the QA Test Light")

    assert result.response.speech["plain"]["speech"] == "Done"
    assert len(fake.calls) == 2
    second_input = fake.calls[1]["input"]
    assert any(
        item.get("type") == "reasoning" and item.get("encrypted_content") == "enc123"
        for item in second_input
    )
    assert any(
        item.get("type") == "function_call" and item.get("call_id") == "call_9"
        for item in second_input
    )
    assert any(
        item.get("type") == "function_call_output" and item.get("call_id") == "call_9"
        for item in second_input
    )


MESSAGE_ERROR_EVENTS = [[{"type": "error", "error": {"message": "upstream kaboom"}}]]

RESPONSE_FAILED_EVENTS = [
    [{"type": "response.failed", "response": {"error": {"message": "bad"}}}]
]


async def test_invalid_llm_api_configuration(hass, aioclient_mock):
    """An unknown LLM API selection produces a conversation error."""
    entry = await create_entry(hass, aioclient_mock)
    subentry = next(
        sub
        for sub in entry.subentries.values()
        if sub.subentry_type == "conversation"
    )
    data = dict(subentry.data)
    data["llm_hass_api"] = ["does-not-exist"]
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()

    result = await _converse(hass, "Hi")

    assert result.response.error_code is not None


async def test_messages_error_event(hass, aioclient_mock):
    """An error event from the Messages stream becomes an error result."""
    entry = await create_entry(
        hass, aioclient_mock, model="claude-haiku-5-5", llm_hass_api=[]
    )
    entry.runtime_data = FakeClient(message_events=MESSAGE_ERROR_EVENTS)

    result = await _converse(hass, "Hi")

    assert result.response.error_code is not None


async def test_responses_failed_event(hass, aioclient_mock):
    """A failed Responses stream becomes an error result."""
    entry = await create_entry(hass, aioclient_mock, model="gpt-6-luna", llm_hass_api=[])
    entry.runtime_data = FakeClient(response_events=RESPONSE_FAILED_EVENTS)

    result = await _converse(hass, "Hi")

    assert result.response.error_code is not None


EMPTY_CHAT_EVENTS = [
    {"choices": [{"delta": {"role": "assistant"}}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
]

TOOL_EMPTY_ARGS_EVENTS = [
    [
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_empty",
                                "function": {"name": "HassTurnOn"},
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ],
    [
        {"choices": [{"delta": {"role": "assistant", "content": "ok"}}]},
        {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]},
    ],
]

TOOL_BAD_ARGS_EVENTS = [
    [
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_bad",
                                "function": {
                                    "name": "HassTurnOn",
                                    "arguments": "not-json",
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
        {"choices": [{"delta": {"role": "assistant", "content": "ok"}}]},
        {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]},
    ],
]


async def test_empty_assistant_message(hass, aioclient_mock):
    """An empty assistant message yields Home Assistant's fallback speech."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=[])
    entry.runtime_data = FakeClient([EMPTY_CHAT_EVENTS])

    result = await _converse(hass, "Hi")

    assert result.response.speech["plain"]["speech"] == "Unable to get response"


async def test_tool_call_with_empty_arguments(hass, aioclient_mock):
    """A tool call without arguments is executed with empty args."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=["assist"])
    fake = FakeClient(chat_events=TOOL_EMPTY_ARGS_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Go")

    assert result.response.speech["plain"]["speech"] == "ok!"
    assert len(fake.calls) == 2


async def test_tool_call_with_invalid_arguments(hass, aioclient_mock):
    """Invalid tool arguments fall back to an empty args dict."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=["assist"])
    fake = FakeClient(chat_events=TOOL_BAD_ARGS_EVENTS)
    entry.runtime_data = fake

    result = await _converse(hass, "Go")

    assert result.response.speech["plain"]["speech"] == "ok!"
    assert len(fake.calls) == 2


async def test_tool_loop_iteration_limit(hass, aioclient_mock):
    """The tool loop stops at the iteration limit."""
    entry = await create_entry(hass, aioclient_mock, llm_hass_api=["assist"])
    fake = FakeClient(
        chat_events=[list(TOOL_BAD_ARGS_EVENTS[0]) for _ in range(10)]
    )
    entry.runtime_data = fake

    await _converse(hass, "Loop")

    assert len(fake.calls) == 10
