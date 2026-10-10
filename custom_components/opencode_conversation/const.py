"""Constants for the OpenCode integration."""

import json
from pathlib import Path
from typing import Final

DOMAIN: Final = "opencode_conversation"

INTEGRATION_VERSION: Final = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]

BASE_URL: Final = "https://opencode.ai/zen/go/v1"

CONF_MODEL: Final = "model"
CONF_CUSTOM_MODEL: Final = "custom_model"
CONF_MAX_TOKENS: Final = "max_tokens"
CONF_API_FAMILY: Final = "api_family"

DEFAULT_MODEL: Final = "deepseek-v4.1-flash"
DEFAULT_MAX_TOKENS: Final = 1024
DEFAULT_CONVERSATION_NAME: Final = "OpenCode Assistant"
DEFAULT_AI_TASK_NAME: Final = "OpenCode AI Task"

# API wire families served by the OpenCode Go gateway.
FAMILY_AUTO: Final = "auto"
FAMILY_CHAT: Final = "chat"
FAMILY_MESSAGES: Final = "messages"
FAMILY_RESPONSES: Final = "responses"

FAMILY_OPTIONS: Final = (FAMILY_AUTO, FAMILY_CHAT, FAMILY_MESSAGES, FAMILY_RESPONSES)

# Certified model -> wire family mapping.
#
# Source: OpenCode Go docs endpoint table (https://opencode.ai/v2/docs/console/go),
# cross-checked against the live API on 2026-10-09 (see docs/research.md,
# "Live verification results"). Models not listed here are hidden from the
# default picker but can be used via the custom model field with an explicit
# API family override. Keep this map in sync with the docs table on releases.
CERTIFIED_MODELS: Final[dict[str, str]] = {
    # OpenAI Chat Completions family
    "deepseek-v4.1-flash": FAMILY_CHAT,
    "deepseek-v4-pro": FAMILY_CHAT,
    "deepseek-v4-flash": FAMILY_CHAT,
    "deepseek-v4-flash-vision-exp": FAMILY_CHAT,
    "glm-5.3-flash": FAMILY_CHAT,
    "glm-5.3": FAMILY_CHAT,
    "glm-5.2": FAMILY_CHAT,
    "glm-5.1": FAMILY_CHAT,
    "hy3": FAMILY_CHAT,
    "hy4-preview": FAMILY_CHAT,
    "kimi-k2.6": FAMILY_CHAT,
    "kimi-k2.7-code": FAMILY_CHAT,
    "kimi-k3": FAMILY_CHAT,
    "longcat-2.0": FAMILY_CHAT,
    "longcat-2.5-preview-free": FAMILY_CHAT,
    "mimo-v2.5": FAMILY_CHAT,
    "mimo-v2.5-pro": FAMILY_CHAT,
    "mimo-v2.6-flash": FAMILY_CHAT,
    "mimo-v2.6-pro": FAMILY_CHAT,
    "space-bunny": FAMILY_CHAT,
    "step-5-preview-free": FAMILY_CHAT,
    # Anthropic Messages family
    "claude-haiku-5-5": FAMILY_MESSAGES,
    "minimax-m2.5": FAMILY_MESSAGES,
    "minimax-m2.7": FAMILY_MESSAGES,
    "minimax-m3": FAMILY_MESSAGES,
    "qwen3.6-plus": FAMILY_MESSAGES,
    "qwen3.7-max": FAMILY_MESSAGES,
    "qwen3.7-plus": FAMILY_MESSAGES,
    "qwen3.8-flash": FAMILY_MESSAGES,
    "qwen3.8-max": FAMILY_MESSAGES,
    # OpenAI Responses family
    "gpt-5.6-luna": FAMILY_RESPONSES,
    "gpt-6-luna": FAMILY_RESPONSES,
    "grok-4.6": FAMILY_RESPONSES,
    "grok-4.7": FAMILY_RESPONSES,
    "muse-spark-1.2-contributor": FAMILY_RESPONSES,
    "muse-spark-1.3-contributor": FAMILY_RESPONSES,
}

# Data handling for models that keep prompts or may use them for training,
# taken from the OpenCode Go privacy table. Shown next to the model in the
# setup and options flows.
MODEL_PRIVACY_NOTES: Final[dict[str, str]] = {
    "grok-4.6": "prompts kept 30 days",
    "grok-4.7": "prompts kept 30 days",
    "gpt-5.6-luna": "prompts kept 30 days",
    "gpt-6-luna": "prompts kept 30 days",
    "claude-haiku-5-5": "prompts kept 30 days",
    "muse-spark-1.2-contributor": "may train on prompts, limited regions",
    "muse-spark-1.3-contributor": "may train on prompts, limited regions",
}


def family_for(model: str, override: str | None = None) -> str:
    """Return the API wire family for a model.

    The certified map wins; unknown models fall back to the explicitly
    configured family, or Chat Completions when set to auto.
    """
    if override and override != FAMILY_AUTO:
        return override
    return CERTIFIED_MODELS.get(model, FAMILY_CHAT)
