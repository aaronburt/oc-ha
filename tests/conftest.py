"""Test configuration for OpenCode tests."""

import sys

import pytest
from homeassistant.setup import async_setup_component

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    # Home Assistant's test tooling blocks socket creation, but Windows
    # asyncio needs a loopback socketpair to construct its event loop.
    # Disable the blocking only on Windows; Linux CI stays strict.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in tests."""
    yield


@pytest.fixture(autouse=True)
async def setup_homeassistant(hass):
    """Set up the homeassistant component, required by conversation."""
    assert await async_setup_component(hass, "homeassistant", {})
