"""Tests for OpenCode constants."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.opencode_conversation.const import (
    CERTIFIED_MODELS,
    FAMILY_AUTO,
    FAMILY_CHAT,
    FAMILY_MESSAGES,
    FAMILY_RESPONSES,
    INTEGRATION_VERSION,
    MODEL_PRIVACY_NOTES,
    family_for,
)


def test_family_for_uses_certified_map():
    """Certified models resolve to their documented API family."""
    assert family_for("claude-haiku-5-5") == FAMILY_MESSAGES
    assert family_for("gpt-6-luna") == FAMILY_RESPONSES
    assert family_for("deepseek-v4.1-flash") == FAMILY_CHAT


def test_privacy_notes_only_for_certified_models():
    """Every model with a privacy note is one the integration offers."""
    assert set(MODEL_PRIVACY_NOTES) <= set(CERTIFIED_MODELS)


def test_integration_version_matches_manifest():
    """The integration version is read from the manifest."""
    manifest_path = (
        Path(__file__).parent.parent
        / "custom_components"
        / "opencode_conversation"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == INTEGRATION_VERSION


def test_family_for_fallbacks():
    """Unknown models fall back to the override or chat completions."""
    assert family_for("unknown-model") == FAMILY_CHAT
    assert family_for("unknown-model", FAMILY_AUTO) == FAMILY_CHAT
    assert family_for("unknown-model", FAMILY_MESSAGES) == FAMILY_MESSAGES
