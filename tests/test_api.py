"""Tests for the OpenCode API client."""

from __future__ import annotations

import pytest

from custom_components.opencode_conversation.api import (
    OpenCodeAuthError,
    OpenCodeClient,
    OpenCodeModelUnavailable,
    OpenCodeProtocolError,
    OpenCodeRateLimited,
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
