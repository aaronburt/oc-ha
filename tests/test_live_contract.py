"""Opt-in live contract checks against the OpenCode Go API.

These tests talk to the real gateway and only run when ``OPENCODE_API_KEY``
is set in the environment, so CI skips them by default. Run them before a
release to confirm the certified model map still matches the live list:

    OPENCODE_API_KEY=... pytest tests/test_live_contract.py
"""

from __future__ import annotations

import os

import pytest
from homeassistant.core import HomeAssistant

from custom_components.opencode_conversation.api import OpenCodeClient
from custom_components.opencode_conversation.const import CERTIFIED_MODELS

pytestmark = [
    pytest.mark.enable_socket,
    pytest.mark.skipif(
        not os.environ.get("OPENCODE_API_KEY"),
        reason="set OPENCODE_API_KEY to run live contract checks",
    ),
]


async def test_live_models_are_certified(hass: HomeAssistant) -> None:
    """Every model the gateway offers is present in CERTIFIED_MODELS."""
    client = OpenCodeClient(hass, os.environ["OPENCODE_API_KEY"])

    live = await client.async_list_models()

    unknown = sorted(set(live) - set(CERTIFIED_MODELS))
    assert not unknown, f"models missing from CERTIFIED_MODELS: {unknown}"
