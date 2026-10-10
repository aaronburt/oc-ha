"""Tests for OpenCode diagnostics."""

from __future__ import annotations

from custom_components.opencode_conversation.api import OpenCodeError
from custom_components.opencode_conversation.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import FakeClient, create_entry


async def test_diagnostics_redacts_api_key(hass, aioclient_mock):
    """Diagnostics redact the API key and include models and usage."""
    entry = await create_entry(hass, aioclient_mock)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["data"]["api_key"] == "**REDACTED**"
    assert diagnostics["available_models"] == [
        "claude-haiku-5-5",
        "deepseek-v4.1-flash",
        "glm-5.3",
        "gpt-6-luna",
    ]
    assert diagnostics["usage"] == {"usage": {}}
    assert diagnostics["certified_models"]["claude-haiku-5-5"] == "messages"
    assert diagnostics["integration_version"]


async def test_diagnostics_api_error(hass, aioclient_mock):
    """Diagnostics report API errors without failing."""
    entry = await create_entry(hass, aioclient_mock)
    entry.runtime_data = FakeClient(error=OpenCodeError("boom"))

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["api_error"] == "boom"


async def test_diagnostics_redacts_subentry_prompt(hass, aioclient_mock):
    """Diagnostics redact subentry prompt text."""
    entry = await create_entry(hass, aioclient_mock)
    subentry = next(
        sub
        for sub in entry.subentries.values()
        if sub.subentry_type == "conversation"
    )
    data = dict(subentry.data)
    data["prompt"] = "secret household instructions"
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    conversation = next(
        item
        for item in diagnostics["entry"]["subentries"]
        if item["subentry_type"] == "conversation"
    )
    assert conversation["data"]["prompt"] == "**REDACTED**"
