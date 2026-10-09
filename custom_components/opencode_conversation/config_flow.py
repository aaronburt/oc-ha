"""Config flow for OpenCode."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LLM_HASS_API,
    CONF_NAME,
    CONF_PROMPT,
)
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import OpenCodeAuthError, OpenCodeClient, OpenCodeError
from .const import (
    CERTIFIED_MODELS,
    CONF_API_FAMILY,
    CONF_CUSTOM_MODEL,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DOMAIN,
    FAMILY_AUTO,
    FAMILY_OPTIONS,
)

VolDictType = dict[probatio.Marker, Any]

_FAMILY_LABELS = {
    FAMILY_AUTO: "Automatic",
    "chat": "Chat Completions (OpenAI-compatible)",
    "messages": "Messages (Anthropic-compatible)",
    "responses": "Responses (OpenAI)",
}


def _model_options(models: list[str]) -> list[SelectOptionDict]:
    """Build model selector options."""
    return [SelectOptionDict(value=model, label=model) for model in models]


def _family_options() -> list[SelectOptionDict]:
    """Build API family selector options."""
    return [
        SelectOptionDict(value=value, label=_FAMILY_LABELS[value])
        for value in FAMILY_OPTIONS
    ]


def _api_key_schema() -> probatio.Schema:
    """Return the schema for an API key field."""
    return probatio.Schema(
        {
            probatio.Required(CONF_API_KEY): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


class OpenCodeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the OpenCode config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._api_key: str | None = None
        self._available_models: list[str] = sorted(CERTIFIED_MODELS)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            client = OpenCodeClient(self.hass, api_key)
            try:
                await client.async_validate_key()
            except OpenCodeAuthError:
                errors["base"] = "invalid_auth"
            except OpenCodeError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(sha256(api_key.encode()).hexdigest())
                self._abort_if_unique_id_configured()
                self._api_key = api_key
                try:
                    live = set(await client.async_list_models())
                    self._available_models = (
                        sorted(set(CERTIFIED_MODELS) & live)
                        or sorted(CERTIFIED_MODELS)
                    )
                except OpenCodeError:
                    self._available_models = sorted(CERTIFIED_MODELS)
                return await self.async_step_model()

        return self.async_show_form(
            step_id="user",
            data_schema=_api_key_schema(),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the model selection step."""
        assert self._api_key is not None
        if user_input is not None:
            model = user_input[CONF_MODEL]
            return self.async_create_entry(
                title="OpenCode",
                data={CONF_API_KEY: self._api_key},
                subentries=[
                    {
                        "subentry_type": "conversation",
                        "data": {
                            CONF_MODEL: model,
                            CONF_LLM_HASS_API: ["assist"],
                            CONF_PROMPT: "",
                            CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                            CONF_API_FAMILY: FAMILY_AUTO,
                        },
                        "title": DEFAULT_CONVERSATION_NAME,
                        "unique_id": None,
                    },
                    {
                        "subentry_type": "ai_task_data",
                        "data": {
                            CONF_MODEL: model,
                            CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                            CONF_API_FAMILY: FAMILY_AUTO,
                        },
                        "title": DEFAULT_AI_TASK_NAME,
                        "unique_id": None,
                    },
                ],
            )

        models = self._available_models
        if DEFAULT_MODEL not in models:
            models = [DEFAULT_MODEL, *models]

        return self.async_show_form(
            step_id="model",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(options=_model_options(models))
                    ),
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the reauth confirmation step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            client = OpenCodeClient(self.hass, api_key)
            try:
                await client.async_validate_key()
            except OpenCodeAuthError:
                errors["base"] = "invalid_auth"
            except OpenCodeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_api_key_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            client = OpenCodeClient(self.hass, api_key)
            try:
                await client.async_validate_key()
            except OpenCodeAuthError:
                errors["base"] = "invalid_auth"
            except OpenCodeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_api_key_schema(),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {
            "conversation": OpenCodeSubentryFlowHandler,
            "ai_task_data": OpenCodeSubentryFlowHandler,
        }


class OpenCodeSubentryFlowHandler(ConfigSubentryFlow):
    """Flow for managing OpenCode conversation and AI task subentries."""

    options: dict[str, Any]

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == SOURCE_USER

    @property
    def _default_title(self) -> str:
        """Return the default title for this subentry type."""
        if self._subentry_type == "ai_task_data":
            return DEFAULT_AI_TASK_NAME
        return DEFAULT_CONVERSATION_NAME

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a subentry."""
        if self._subentry_type == "ai_task_data":
            self.options = {
                CONF_MODEL: DEFAULT_MODEL,
                CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                CONF_API_FAMILY: FAMILY_AUTO,
            }
        else:
            self.options = {
                CONF_MODEL: DEFAULT_MODEL,
                CONF_LLM_HASS_API: ["assist"],
                CONF_PROMPT: "",
                CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                CONF_API_FAMILY: FAMILY_AUTO,
            }
        return await self.async_step_init()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a subentry."""
        self.options = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_init()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage the subentry options."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        options = self.options

        if user_input is not None:
            data = dict(user_input)
            name = data.pop(CONF_NAME, None)
            custom_model = str(data.pop(CONF_CUSTOM_MODEL, "") or "").strip()
            if custom_model:
                data[CONF_MODEL] = custom_model
            if self._subentry_type == "conversation":
                if not data.get(CONF_LLM_HASS_API):
                    data.pop(CONF_LLM_HASS_API, None)
            else:
                data.pop(CONF_LLM_HASS_API, None)
                data.pop(CONF_PROMPT, None)
            if self._is_new:
                return self.async_create_entry(
                    title=name or self._default_title,
                    data=data,
                )
            return self.async_update_and_abort(
                entry, self._get_reconfigure_subentry(), data=data
            )

        models = await self._async_available_models(entry)

        step_schema: VolDictType = {}
        if self._is_new:
            step_schema[probatio.Required(CONF_NAME, default=self._default_title)] = (
                TextSelector()
            )
        step_schema[
            probatio.Required(CONF_MODEL, default=options.get(CONF_MODEL, DEFAULT_MODEL))
        ] = SelectSelector(SelectSelectorConfig(options=_model_options(models)))
        step_schema[
            probatio.Optional(CONF_CUSTOM_MODEL, default="")
        ] = TextSelector()
        if self._subentry_type == "conversation":
            hass_apis = [
                SelectOptionDict(label=api.name, value=api.id)
                for api in llm.async_get_apis(self.hass)
            ]
            step_schema[
                probatio.Optional(
                    CONF_LLM_HASS_API, default=options.get(CONF_LLM_HASS_API, ["assist"])
                )
            ] = SelectSelector(
                SelectSelectorConfig(options=hass_apis, multiple=True)
            )
            step_schema[
                probatio.Optional(CONF_PROMPT, default=options.get(CONF_PROMPT, ""))
            ] = TextSelector(TextSelectorConfig(multiline=True))
        step_schema[
            probatio.Required(
                CONF_MAX_TOKENS, default=options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
            )
        ] = NumberSelector(
            NumberSelectorConfig(min=16, max=32768, mode=NumberSelectorMode.BOX)
        )
        step_schema[
            probatio.Optional(
                CONF_API_FAMILY, default=options.get(CONF_API_FAMILY, FAMILY_AUTO)
            )
        ] = SelectSelector(SelectSelectorConfig(options=_family_options()))

        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(step_schema),
        )

    async def _async_available_models(self, entry: ConfigEntry) -> list[str]:
        """Return selectable models for this entry."""
        models = set(CERTIFIED_MODELS)
        try:
            client: OpenCodeClient = entry.runtime_data
            models &= set(await client.async_list_models())
        except OpenCodeError:
            pass
        if current := self.options.get(CONF_MODEL):
            models.add(current)
        if DEFAULT_MODEL not in models:
            models.add(DEFAULT_MODEL)
        return sorted(models)
