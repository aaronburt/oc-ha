"""Tests for the OpenCode API client."""

from __future__ import annotations

import logging

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.opencode_conversation.api import (
    OpenCodeAuthError,
    OpenCodeClient,
    OpenCodeConnectionError,
    OpenCodeError,
    OpenCodeModelUnavailable,
    OpenCodeProtocolError,
    OpenCodeRateLimited,
    OpenCodeTransientError,
)

from .helpers import BASE_URL, USAGE_URL


async def test_validate_key_ok(hass, aioclient_mock):
    """A valid key passes validation."""
    aioclient_mock.get(USAGE_URL, json={"usage": {}})
    client = OpenCodeClient(hass, "test-key")
    await client.async_validate_key()
    assert aioclient_mock.call_count == 1


async def test_validate_key_invalid(hass, aioclient_mock):
    """An invalid key raises OpenCodeAuthError."""
    aioclient_mock.get(
        USAGE_URL,
        status=401,
        json={"type": "error", "error": {"type": "AuthError", "message": "Unauthorized"}},
    )
    client = OpenCodeClient(hass, "bad-key")
    with pytest.raises(OpenCodeAuthError):
        await client.async_validate_key()


async def test_rate_limited(hass, aioclient_mock):
    """A 429 raises OpenCodeRateLimited with retry information."""
    aioclient_mock.get(
        USAGE_URL,
        status=429,
        json={"error": {"message": "limit reached"}},
        headers={"retry-after": "42"},
    )
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeRateLimited) as err:
        await client.async_validate_key()
    assert err.value.retry_after == 42.0


async def test_model_unavailable(hass, aioclient_mock):
    """An unavailable model raises OpenCodeModelUnavailable."""
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        status=400,
        json={
            "error": {
                "type": "server_error",
                "message": "Upstream request failed: Model is unavailable.",
            }
        },
    )
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeModelUnavailable):
        async for _event in client.stream_chat_completions({"model": "gone"}):
            pass


async def test_protocol_mismatch(hass, aioclient_mock):
    """A protocol mismatch raises OpenCodeProtocolError."""
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        status=400,
        json={
            "type": "error",
            "error": {
                "type": "ModelProtocolUnsupported",
                "message": "Model does not support this protocol.",
            },
        },
    )
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeProtocolError):
        async for _event in client.stream_chat_completions({"model": "claude-haiku-5-5"}):
            pass


async def test_list_models_sorted(hass, aioclient_mock):
    """Models are returned as a sorted list of IDs."""
    aioclient_mock.get(
        f"{BASE_URL}/models",
        json={"object": "list", "data": [{"id": "glm-5.3"}, {"id": "deepseek-v4.1-flash"}]},
    )
    client = OpenCodeClient(hass, "key")
    assert await client.async_list_models() == [
        "deepseek-v4.1-flash",
        "glm-5.3",
    ]


async def test_identity_headers(hass):
    """Every client carries a user agent and a session ID."""
    client = OpenCodeClient(hass, "key")
    headers = client._base_headers
    assert headers["user-agent"].startswith("oc-ha/")
    assert headers["x-opencode-session"]


async def test_auth_headers_per_family(hass):
    """Messages uses x-api-key, other families use Bearer auth."""
    client = OpenCodeClient(hass, "key")
    assert client._auth_headers("messages") == {"x-api-key": "key"}
    assert client._auth_headers("chat") == {"authorization": "Bearer key"}
    assert client._auth_headers("responses") == {"authorization": "Bearer key"}


async def test_streaming_chat_events(hass, aioclient_mock):
    """SSE events are decoded and [DONE] terminates the stream."""
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        text='data: {"choices": [{"delta": {"content": "Hi"}}]}\n\ndata: [DONE]\n\n',
        headers={"Content-Type": "text/event-stream"},
    )
    client = OpenCodeClient(hass, "key")
    events = [
        event
        async for event in client.stream_chat_completions({"model": "test-model"})
    ]
    assert events == [{"choices": [{"delta": {"content": "Hi"}}]}]


async def test_server_error_maps_to_error(hass, aioclient_mock):
    """A plain 5xx maps to the generic error with the status attached."""
    aioclient_mock.get(
        USAGE_URL, status=500, json={"error": {"message": "server exploded"}}
    )
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeError) as err:
        await client.async_validate_key()
    assert err.value.status == 500


async def test_error_without_json_body(hass, aioclient_mock):
    """A non-JSON error body still maps to an error."""
    aioclient_mock.get(USAGE_URL, status=500, text="oops")
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeError) as err:
        await client.async_validate_key()
    assert err.value.status == 500


async def test_streaming_ignores_non_data_lines(hass, aioclient_mock):
    """Comments, events and broken JSON in the SSE stream are skipped."""
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        text=': comment\nevent: ping\ndata: not-json\ndata: {"a": 1}\n\n',
        headers={"Content-Type": "text/event-stream"},
    )
    client = OpenCodeClient(hass, "key")
    events = [
        event
        async for event in client.stream_chat_completions({"model": "test-model"})
    ]
    assert events == [{"a": 1}]


async def test_error_body_with_string_error(hass, aioclient_mock):
    """A string error field is used as the error message."""
    aioclient_mock.get(USAGE_URL, status=400, json={"error": "plain failure"})
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeError) as err:
        await client.async_validate_key()
    assert str(err.value) == "plain failure"


async def test_malformed_400_is_transient(hass, aioclient_mock):
    """A bare 400 without an error payload is treated as transient."""
    aioclient_mock.get(
        USAGE_URL, status=400, json={"model": "deepseek-v4.1-flash"}
    )
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeTransientError):
        await client.async_validate_key()


async def test_connection_error(hass, aioclient_mock):
    """A transport error maps to OpenCodeConnectionError."""
    aioclient_mock.get(USAGE_URL, exc=aiohttp.ClientError("boom"))
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeConnectionError):
        await client.async_validate_key()


async def test_stream_messages_and_responses(hass, aioclient_mock):
    """The Messages and Responses streaming methods decode SSE events."""
    aioclient_mock.post(
        f"{BASE_URL}/messages",
        text='data: {"type": "message_stop"}\n\n',
        headers={"Content-Type": "text/event-stream"},
    )
    aioclient_mock.post(
        f"{BASE_URL}/responses",
        text='data: {"type": "response.completed"}\n\n',
        headers={"Content-Type": "text/event-stream"},
    )
    client = OpenCodeClient(hass, "key")

    messages_events = [event async for event in client.stream_messages({"model": "m"})]
    responses_events = [
        event async for event in client.stream_responses({"model": "m"})
    ]

    assert messages_events == [{"type": "message_stop"}]
    assert responses_events == [{"type": "response.completed"}]


async def test_failed_stream_does_not_log_prompt(hass, aioclient_mock, caplog):
    """A failed stream raises without logging the request body, even at debug."""
    caplog.set_level(logging.DEBUG)
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        status=500,
        json={"error": {"message": "server exploded"}},
    )
    client = OpenCodeClient(hass, "key")
    body = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "secret kitchen plan"}],
    }
    with pytest.raises(OpenCodeError):
        async for _event in client.stream_chat_completions(body):
            pass
    assert "secret kitchen plan" not in caplog.text


def _flaky_get(scripted):
    """Return a mock side effect that plays scripted responses in order."""

    async def side_effect(method, url, data):
        kwargs = queue.pop(0) if queue else {"json": {"usage": {}}}
        return AiohttpClientMockResponse(method, url, **kwargs)

    queue = list(scripted)
    return side_effect


async def test_get_retries_transient_failure(hass, aioclient_mock):
    """A failed GET is retried and can still succeed."""
    aioclient_mock.get(
        USAGE_URL,
        side_effect=_flaky_get(
            [
                {"status": 500, "json": {"error": {"message": "boom"}}},
                {"json": {"usage": {}}},
            ]
        ),
    )
    client = OpenCodeClient(hass, "key")

    assert await client.async_get_usage() == {"usage": {}}
    assert aioclient_mock.call_count == 2


async def test_get_retry_is_bounded(hass, aioclient_mock):
    """A GET that keeps failing stops after the retry budget."""
    aioclient_mock.get(USAGE_URL, status=500, json={"error": {"message": "boom"}})
    client = OpenCodeClient(hass, "key")

    with pytest.raises(OpenCodeError) as err:
        await client.async_get_usage()

    assert err.value.status == 500
    assert aioclient_mock.call_count == 3


async def test_post_is_not_retried(hass, aioclient_mock):
    """Streaming POSTs are not retried."""
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        status=500,
        json={"error": {"message": "boom"}},
    )
    client = OpenCodeClient(hass, "key")

    with pytest.raises(OpenCodeError):
        async for _event in client.stream_chat_completions({"model": "test-model"}):
            pass

    assert aioclient_mock.call_count == 1


async def test_stream_connection_error(hass, aioclient_mock):
    """A transport error during streaming maps to OpenCodeConnectionError."""
    aioclient_mock.post(
        f"{BASE_URL}/chat/completions",
        exc=aiohttp.ClientError("boom"),
        headers={"Content-Type": "text/event-stream"},
    )
    client = OpenCodeClient(hass, "key")
    with pytest.raises(OpenCodeConnectionError):
        async for _event in client.stream_chat_completions({"model": "m"}):
            pass
