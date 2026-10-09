"""Async API client for the OpenCode Go gateway."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Final, NoReturn

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.ulid import ulid_now

from .const import BASE_URL, FAMILY_CHAT, FAMILY_MESSAGES, FAMILY_RESPONSES, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT: Final = 60
STREAM_TIMEOUT: Final = 600


class OpenCodeError(Exception):
    """Base class for OpenCode API errors."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Initialize the error."""
        super().__init__(message)
        self.status = status


class OpenCodeAuthError(OpenCodeError):
    """Authentication with the OpenCode API failed."""


class OpenCodeConnectionError(OpenCodeError):
    """Unable to reach the OpenCode API."""


class OpenCodeModelUnavailable(OpenCodeError):
    """The requested model is no longer available."""


class OpenCodeProtocolError(OpenCodeError):
    """The requested model does not support the configured API family."""


class OpenCodeTransientError(OpenCodeError):
    """A transient upstream error that is worth retrying."""


class OpenCodeRateLimited(OpenCodeError):
    """The account or model usage limit was reached."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Initialize the error."""
        super().__init__(message, status)
        self.retry_after = retry_after


class OpenCodeClient:
    """Minimal async client for the OpenCode Go gateway.

    All requests carry the client identity headers OpenCode requires:
    a dedicated user agent and a stable ``x-opencode-session`` value.
    The OpenCode gateway rejects inference requests without a session header.
    """

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Initialize the client."""
        self._hass = hass
        self._api_key = api_key
        self._session = async_get_clientsession(hass)
        self._session_id = ulid_now()

    @property
    def _base_headers(self) -> dict[str, str]:
        """Return the identity headers sent with every request."""
        return {
            "user-agent": f"oc-ha/{INTEGRATION_VERSION}",
            "x-opencode-session": self._session_id,
        }

    def _auth_headers(self, family: str) -> dict[str, str]:
        """Return the authentication headers for an API family."""
        if family == FAMILY_MESSAGES:
            return {"x-api-key": self._api_key}
        return {"authorization": f"Bearer {self._api_key}"}

    async def _async_raise_for_status(self, resp: aiohttp.ClientResponse) -> NoReturn:
        """Translate an error response into a typed exception."""
        raw = await resp.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        _LOGGER.debug(
            "OpenCode error response (%s): %s", resp.status, raw[:500]
        )

        error = body.get("error")
        if isinstance(error, dict):
            error_type = str(error.get("type", ""))
            message = str(error.get("message", "Unknown error"))
        elif isinstance(error, str):
            error_type = ""
            message = error
        else:
            error_type = ""
            reason = getattr(resp, "reason", None) or "Unknown error"
            message = str(
                body.get("message")
                or raw.decode("utf-8", "replace")[:200]
                or reason
            )

        status = resp.status
        if status in (401, 403):
            raise OpenCodeAuthError(message, status)
        if status == 429:
            retry_after = resp.headers.get("retry-after")
            raise OpenCodeRateLimited(
                message, status, float(retry_after) if retry_after else None
            )
        if "ModelProtocolUnsupported" in error_type or "does not support this protocol" in message:
            raise OpenCodeProtocolError(message, status)
        if "unavailable" in message.lower():
            raise OpenCodeModelUnavailable(message, status)
        if status == 400 and error is None:
            # Upstream occasionally returns a bare 400 without an error payload
            # (observed with structured output); treat it as transient.
            raise OpenCodeTransientError(message, status)
        raise OpenCodeError(message, status)

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        family: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a non-streaming JSON request."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method,
                    BASE_URL + path,
                    headers={**self._base_headers, **self._auth_headers(family)},
                    json=json_body,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    await self._async_raise_for_status(resp)
        except TimeoutError as err:
            raise OpenCodeConnectionError("Timed out talking to OpenCode") from err
        except aiohttp.ClientError as err:
            raise OpenCodeConnectionError(f"Error talking to OpenCode: {err}") from err
        raise OpenCodeConnectionError("Unknown error talking to OpenCode")

    async def _async_stream(
        self,
        path: str,
        *,
        family: str,
        body: dict[str, Any],
        session_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Perform a streaming request and yield decoded SSE JSON events."""
        headers = {
            **self._base_headers,
            **self._auth_headers(family),
            "accept": "text/event-stream",
            "x-opencode-session": session_id or self._session_id,
        }
        request_body = {**body, "stream": True}
        try:
            async with asyncio.timeout(STREAM_TIMEOUT):
                async with self._session.post(
                    BASE_URL + path, headers=headers, json=request_body
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.debug(
                            "OpenCode request failed (%s): %s",
                            resp.status,
                            json.dumps(request_body)[:2000],
                        )
                        await self._async_raise_for_status(resp)
                    async for raw_line in resp.content:
                        line = raw_line.strip()
                        if not line.startswith(b"data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == b"[DONE]":
                            break
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            yield event
        except TimeoutError as err:
            raise OpenCodeConnectionError("OpenCode response timed out") from err
        except aiohttp.ClientError as err:
            raise OpenCodeConnectionError(f"Error talking to OpenCode: {err}") from err

    # Public API

    async def async_get_usage(self) -> dict[str, Any]:
        """Return the current Go plan usage windows."""
        return await self._async_request("GET", "/usage", family=FAMILY_CHAT)

    async def async_validate_key(self) -> None:
        """Validate the API key by requesting the usage endpoint."""
        await self.async_get_usage()

    async def async_list_models(self) -> list[str]:
        """Return the model IDs available to this subscription."""
        data = await self._async_request("GET", "/models", family=FAMILY_CHAT)
        return sorted(
            model["id"]
            for model in data.get("data", [])
            if isinstance(model, dict) and model.get("id")
        )

    def stream_chat_completions(
        self, body: dict[str, Any], session_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a Chat Completions request."""
        return self._async_stream(
            "/chat/completions", family=FAMILY_CHAT, body=body, session_id=session_id
        )

    def stream_messages(
        self, body: dict[str, Any], session_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream an Anthropic Messages request."""
        return self._async_stream(
            "/messages", family=FAMILY_MESSAGES, body=body, session_id=session_id
        )

    def stream_responses(
        self, body: dict[str, Any], session_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream an OpenAI Responses request."""
        return self._async_stream(
            "/responses", family=FAMILY_RESPONSES, body=body, session_id=session_id
        )
