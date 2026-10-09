"""Base LLM entity for OpenCode: chat log conversion, streaming and tool loop."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Final

import probatio
from homeassistant.components import conversation
from homeassistant.components.conversation import ChatLog
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps
from homeassistant.util import slugify
from homeassistant.util.ulid import ulid_now

from .api import (
    OpenCodeAuthError,
    OpenCodeError,
    OpenCodeModelUnavailable,
    OpenCodeProtocolError,
    OpenCodeRateLimited,
    OpenCodeTransientError,
)
from .const import (
    CONF_API_FAMILY,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DOMAIN,
    FAMILY_CHAT,
    FAMILY_MESSAGES,
    FAMILY_RESPONSES,
    family_for,
)

if TYPE_CHECKING:
    from . import OpenCodeConfigEntry

_LOGGER = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS: Final = 10


def _format_tool_schema(
    tool: llm.Tool, custom_serializer: Any | None
) -> dict[str, Any]:
    """Convert a tool's parameters into JSON schema."""
    schema = probatio.to_openapi(
        tool.parameters,
        custom_serializer=custom_serializer or llm.selector_serializer,
        openapi_version="3.1.0",
    )
    schema.pop("$schema", None)
    return schema


def _format_tools_chat(tools: Iterable[llm.Tool], custom_serializer: Any | None) -> list[dict[str, Any]]:
    """Format tools for the Chat Completions API."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": _format_tool_schema(tool, custom_serializer),
            },
        }
        for tool in tools
    ]


def _format_tools_messages(tools: Iterable[llm.Tool], custom_serializer: Any | None) -> list[dict[str, Any]]:
    """Format tools for the Anthropic Messages API."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": _format_tool_schema(tool, custom_serializer),
        }
        for tool in tools
    ]


def _format_tools_responses(tools: Iterable[llm.Tool], custom_serializer: Any | None) -> list[dict[str, Any]]:
    """Format tools for the OpenAI Responses API."""
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": _format_tool_schema(tool, custom_serializer),
        }
        for tool in tools
    ]


def _format_structured_output(
    schema: probatio.Schema, llm_api: llm.APIInstance | None
) -> dict[str, Any]:
    """Convert a probatio schema into the JSON schema used for structured output."""
    result = probatio.to_openapi(
        schema,
        custom_serializer=(
            llm_api.custom_serializer if llm_api else llm.selector_serializer
        ),
        openapi_version="3.1.0",
    )
    result.pop("$schema", None)
    if "type" not in result:
        result["type"] = "object"
    return result


def _structured_prompt(structure_name: str | None, schema: dict[str, Any]) -> str:
    """Build a prompt instruction for models without native JSON schema output."""
    name = structure_name or "response"
    return (
        f"Respond with a single JSON object named {slugify(name)} that matches "
        f"this JSON schema, and nothing else:\n{json.dumps(schema)}"
    )


def _parse_tool_args(raw: str) -> dict[str, Any]:
    """Parse tool call arguments returned by a model."""
    if not raw:
        return {}
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        _LOGGER.warning("OpenCode returned invalid tool arguments")
        _LOGGER.debug("Invalid tool arguments: %s", raw)
        return {}
    return result if isinstance(result, dict) else {}


def _usage_stats(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Normalize token usage across the three API families."""
    if not usage:
        return {}
    stats: dict[str, int] = {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if isinstance(input_tokens, int):
        stats["input_tokens"] = input_tokens
    if isinstance(output_tokens, int):
        stats["output_tokens"] = output_tokens
    return stats


def _reasoning_item(native: Any) -> dict[str, Any] | None:
    """Build a replayable reasoning item from cached provider-native content."""
    if (
        isinstance(native, Mapping)
        and native.get("type") == "reasoning"
        and native.get("encrypted_content")
    ):
        return {
            "type": "reasoning",
            "id": native.get("id", ""),
            "encrypted_content": native["encrypted_content"],
            "summary": [],
        }
    return None


def _system_context(model: str, has_tools: bool) -> str:
    """Return a short context line giving the model base environment awareness."""
    context = (
        f"You are running through OpenCode Go as model {model}. "
        "Your environment is Home Assistant."
    )
    if has_tools:
        context += " Use the provided tools to control it instead of guessing."
    return context


def _content_with_context(
    contents: Iterable[conversation.Content], context: str
) -> list[conversation.Content]:
    """Append the context line to the system message, adding one if missing."""
    result = list(contents)
    for index, content in enumerate(result):
        if content.role == "system":
            text = content.content or ""
            result[index] = conversation.SystemContent(
                content=f"{text}\n{context}" if text else context
            )
            return result
    result.insert(0, conversation.SystemContent(content=context))
    return result


def chat_messages_from_content(
    contents: Iterable[conversation.Content],
) -> list[dict[str, Any]]:
    """Convert chat log content into Chat Completions messages."""
    messages: list[dict[str, Any]] = []
    for content in contents:
        if isinstance(content, conversation.ToolResultContent):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": content.tool_call_id,
                    "content": json_dumps(
                        {"data": content.result.data, "error": content.result.error}
                    ),
                }
            )
            continue
        if isinstance(content, conversation.AssistantContent):
            message: dict[str, Any] = {
                "role": "assistant",
                "content": content.content or "",
            }
            if content.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.tool_name,
                            "arguments": json_dumps(tool_call.tool_args),
                        },
                    }
                    for tool_call in content.tool_calls
                ]
            if content.content or content.tool_calls:
                messages.append(message)
            continue
        if content.content:
            messages.append({"role": content.role, "content": content.content})
    return messages


def messages_from_content(
    contents: Iterable[conversation.Content],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert chat log content into Anthropic Messages system and messages."""
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []

    def append_blocks(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if (
            messages
            and messages[-1]["role"] == role
            and isinstance(messages[-1]["content"], list)
        ):
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": blocks})

    for content in contents:
        if isinstance(content, conversation.ToolResultContent):
            append_blocks(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": content.tool_call_id,
                        "content": json_dumps(
                            {"data": content.result.data, "error": content.result.error}
                        ),
                    }
                ],
            )
            continue
        if content.role == "system":
            system_parts.append(content.content or "")
            continue
        if isinstance(content, conversation.AssistantContent):
            blocks: list[dict[str, Any]] = []
            if content.content:
                blocks.append({"type": "text", "text": content.content})
            for tool_call in content.tool_calls or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.tool_name,
                        "input": tool_call.tool_args,
                    }
                )
            append_blocks("assistant", blocks)
            continue
        if content.content:
            append_blocks(content.role, [{"type": "text", "text": content.content}])

    system = "\n".join(part for part in system_parts if part)
    return (system or None), messages


def responses_items_from_content(
    contents: Iterable[conversation.Content],
) -> list[dict[str, Any]]:
    """Convert chat log content into OpenAI Responses input items."""
    items: list[dict[str, Any]] = []
    for content in contents:
        if isinstance(content, conversation.ToolResultContent):
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": content.tool_call_id,
                    "output": json_dumps(
                        {"data": content.result.data, "error": content.result.error}
                    ),
                }
            )
            continue
        if isinstance(content, conversation.AssistantContent):
            if reasoning := _reasoning_item(content.native):
                items.append(reasoning)
            if content.content:
                items.append(
                    {"type": "message", "role": "assistant", "content": content.content}
                )
            for tool_call in content.tool_calls or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.tool_name,
                        "arguments": json_dumps(tool_call.tool_args),
                    }
                )
            continue
        if content.content:
            role = "developer" if content.role == "system" else content.role
            items.append({"type": "message", "role": role, "content": content.content})
    return items


class OpenCodeBaseLLMEntity(Entity):
    """Shared engine for OpenCode conversation and AI task entities."""

    _attr_has_entity_name = True
    _attr_name: str | None = None

    def __init__(self, entry: OpenCodeConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._fallback_session_id = ulid_now()
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="OpenCode",
            model=subentry.data.get(CONF_MODEL, DEFAULT_MODEL),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def client(self) -> Any:
        """Return the API client stored on the config entry."""
        return self.entry.runtime_data

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return self.entry.state is ConfigEntryState.LOADED

    def _async_api_error(self, err: OpenCodeError, model: str) -> HomeAssistantError:
        """Translate an API error into a user facing error."""
        if isinstance(err, OpenCodeAuthError):
            self.entry.async_start_reauth(self.hass)
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="authentication_error",
            )
        if isinstance(err, OpenCodeRateLimited):
            if err.retry_after:
                return HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rate_limit_retry",
                    translation_placeholders={
                        "model": model,
                        "seconds": str(int(err.retry_after)),
                    },
                )
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="rate_limit",
                translation_placeholders={"model": model},
            )
        if isinstance(err, OpenCodeProtocolError):
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="protocol_unsupported",
                translation_placeholders={"model": model},
            )
        if isinstance(err, OpenCodeModelUnavailable):
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="model_unavailable",
                translation_placeholders={"model": model},
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"error": str(err)},
        )

    async def _async_handle_chat_log(
        self,
        chat_log: ChatLog,
        *,
        structure: probatio.Schema | None = None,
        structure_name: str | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        """Generate a reply for the chat log, running the tool loop."""
        options = self.subentry.data
        model = options.get(CONF_MODEL, DEFAULT_MODEL)
        family = family_for(model, options.get(CONF_API_FAMILY))
        max_tokens = options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        session_id = chat_log.conversation_id or self._fallback_session_id
        context = _system_context(model, chat_log.llm_api is not None)
        json_instruction = (
            _structured_prompt(
                structure_name, _format_structured_output(structure, chat_log.llm_api)
            )
            if structure and structure_name
            else None
        )
        native_retries = 0
        force_json_prompt = False

        for _iteration in range(max_iterations):
            usage_out: dict[str, Any] = {}
            request_structure = None if force_json_prompt else structure
            request_context = (
                f"{context}\n{json_instruction}"
                if force_json_prompt and json_instruction
                else context
            )
            try:
                if family == FAMILY_MESSAGES:
                    generator = self._async_stream_messages(
                        model, chat_log, max_tokens, session_id, usage_out,
                        request_structure, structure_name, request_context,
                    )
                elif family == FAMILY_RESPONSES:
                    generator = self._async_stream_responses(
                        model, chat_log, max_tokens, session_id, usage_out,
                        request_structure, structure_name, request_context,
                    )
                else:
                    generator = self._async_stream_chat(
                        model, chat_log, max_tokens, session_id, usage_out,
                        request_structure, structure_name, request_context,
                    )
                async for _content in chat_log.async_add_delta_content_stream(
                    self.entity_id, generator
                ):
                    pass
            except OpenCodeTransientError as err:
                if json_instruction and family == FAMILY_CHAT:
                    if native_retries < 1 and not force_json_prompt:
                        native_retries += 1
                        _LOGGER.warning(
                            "OpenCode returned a transient structured-output "
                            "error; retrying the request"
                        )
                        continue
                    if not force_json_prompt:
                        force_json_prompt = True
                        _LOGGER.warning(
                            "OpenCode structured output keeps failing; falling "
                            "back to prompt-guided JSON"
                        )
                        continue
                raise self._async_api_error(err, model) from err
            except OpenCodeError as err:
                raise self._async_api_error(err, model) from err

            if stats := _usage_stats(usage_out):
                chat_log.async_trace({"stats": stats})

            if not chat_log.unresponded_tool_results:
                break
        else:
            _LOGGER.warning(
                "OpenCode tool loop reached the iteration limit of %s", max_iterations
            )

    async def _async_stream_chat(
        self,
        model: str,
        chat_log: ChatLog,
        max_tokens: int,
        session_id: str,
        usage_out: dict[str, Any],
        structure: probatio.Schema | None,
        structure_name: str | None,
        context: str,
    ) -> AsyncIterator[conversation.AssistantContentDeltaDict]:
        """Stream a Chat Completions response as HA deltas."""
        llm_api = chat_log.llm_api
        body: dict[str, Any] = {
            "model": model,
            "messages": chat_messages_from_content(
                _content_with_context(chat_log.content, context)
            ),
            "stream_options": {"include_usage": True},
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if llm_api and llm_api.tools:
            body["tools"] = _format_tools_chat(llm_api.tools, llm_api.custom_serializer)
        if structure and structure_name:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": slugify(structure_name),
                    "strict": False,
                    "schema": _format_structured_output(structure, llm_api),
                },
            }

        role_sent = False
        pending_tools: dict[int, dict[str, str]] = {}
        async for event in self.client.stream_chat_completions(
            body, session_id=session_id
        ):
            if error := event.get("error"):
                message = error.get("message") if isinstance(error, dict) else error
                raise OpenCodeError(str(message or "OpenCode streaming error"))
            choices = event.get("choices") or []
            if not choices:
                if usage := event.get("usage"):
                    usage_out.update(usage)
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            if not role_sent and (delta or choice.get("finish_reason")):
                yield {"role": "assistant"}
                role_sent = True
            if content := delta.get("content"):
                yield {"content": content}
            if thinking := delta.get("reasoning_content"):
                yield {"thinking_content": thinking}
            for tool_call in delta.get("tool_calls") or []:
                index = tool_call.get("index", 0)
                entry = pending_tools.setdefault(
                    index, {"id": "", "name": "", "arguments": ""}
                )
                if tool_call.get("id"):
                    entry["id"] = tool_call["id"]
                function = tool_call.get("function") or {}
                if function.get("name"):
                    entry["name"] += function["name"]
                if function.get("arguments"):
                    entry["arguments"] += function["arguments"]
            if choice.get("finish_reason"):
                for _index, entry in sorted(pending_tools.items()):
                    if entry["name"]:
                        yield {
                            "tool_calls": [
                                llm.ToolInput(
                                    id=entry["id"] or entry["name"],
                                    tool_name=entry["name"],
                                    tool_args=_parse_tool_args(entry["arguments"]),
                                )
                            ]
                        }
                pending_tools.clear()
                if usage := event.get("usage"):
                    usage_out.update(usage)

    async def _async_stream_messages(
        self,
        model: str,
        chat_log: ChatLog,
        max_tokens: int,
        session_id: str,
        usage_out: dict[str, Any],
        structure: probatio.Schema | None,
        structure_name: str | None,
        context: str,
    ) -> AsyncIterator[conversation.AssistantContentDeltaDict]:
        """Stream an Anthropic Messages response as HA deltas."""
        llm_api = chat_log.llm_api
        system, messages = messages_from_content(
            _content_with_context(chat_log.content, context)
        )
        if structure and structure_name:
            instruction = _structured_prompt(
                structure_name, _format_structured_output(structure, llm_api)
            )
            system = f"{system}\n{instruction}" if system else instruction

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
        }
        if system:
            body["system"] = system
        if llm_api and llm_api.tools:
            body["tools"] = _format_tools_messages(
                llm_api.tools, llm_api.custom_serializer
            )

        role_sent = False
        pending_tools: dict[int, dict[str, str]] = {}
        async for event in self.client.stream_messages(body, session_id=session_id):
            event_type = event.get("type")
            if event_type == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") in ("text", "thinking", "tool_use") and not role_sent:
                    yield {"role": "assistant"}
                    role_sent = True
                if block.get("type") == "tool_use":
                    pending_tools[event.get("index", 0)] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": "",
                    }
            elif event_type == "content_block_delta":
                delta = event.get("delta") or {}
                delta_type = delta.get("type")
                if delta_type in ("text_delta", "thinking_delta") and not role_sent:
                    yield {"role": "assistant"}
                    role_sent = True
                if delta_type == "text_delta":
                    yield {"content": delta.get("text", "")}
                elif delta_type == "thinking_delta":
                    yield {"thinking_content": delta.get("thinking", "")}
                elif delta_type == "input_json_delta":
                    index = event.get("index", 0)
                    if index in pending_tools:
                        pending_tools[index]["arguments"] += delta.get("partial_json", "")
            elif event_type == "content_block_stop":
                entry = pending_tools.pop(event.get("index", 0), None)
                if entry and entry["name"]:
                    yield {
                        "tool_calls": [
                            llm.ToolInput(
                                id=entry["id"] or entry["name"],
                                tool_name=entry["name"],
                                tool_args=_parse_tool_args(entry["arguments"]),
                            )
                        ]
                    }
            elif event_type == "message_start":
                if usage := (event.get("message") or {}).get("usage"):
                    usage_out.update(usage)
            elif event_type == "message_delta":
                if usage := event.get("usage"):
                    usage_out.update(usage)
            elif event_type == "error":
                error = event.get("error") or {}
                raise OpenCodeError(error.get("message", "OpenCode streaming error"))

    async def _async_stream_responses(
        self,
        model: str,
        chat_log: ChatLog,
        max_tokens: int,
        session_id: str,
        usage_out: dict[str, Any],
        structure: probatio.Schema | None,
        structure_name: str | None,
        context: str,
    ) -> AsyncIterator[conversation.AssistantContentDeltaDict]:
        """Stream an OpenAI Responses response as HA deltas."""
        llm_api = chat_log.llm_api
        body: dict[str, Any] = {
            "model": model,
            "input": responses_items_from_content(
                _content_with_context(chat_log.content, context)
            ),
            "store": False,
        }
        if max_tokens:
            body["max_output_tokens"] = max_tokens
        if llm_api and llm_api.tools:
            body["tools"] = _format_tools_responses(
                llm_api.tools, llm_api.custom_serializer
            )
        if structure and structure_name:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": slugify(structure_name),
                    "schema": _format_structured_output(structure, llm_api),
                    "strict": False,
                }
            }

        role_sent = False
        native_sent = False
        pending_tools: dict[str, dict[str, str]] = {}
        async for event in self.client.stream_responses(body, session_id=session_id):
            event_type = event.get("type")
            if event_type == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    pending_tools[item.get("id", "")] = {
                        "id": item.get("call_id", ""),
                        "name": item.get("name", ""),
                        "arguments": "",
                    }
                elif item.get("type") in ("message", "reasoning") and not role_sent:
                    yield {"role": "assistant"}
                    role_sent = True
            elif event_type == "response.output_text.delta":
                if not role_sent:
                    yield {"role": "assistant"}
                    role_sent = True
                yield {"content": event.get("delta", "")}
            elif event_type == "response.function_call_arguments.delta":
                item_id = event.get("item_id", "")
                if item_id in pending_tools:
                    pending_tools[item_id]["arguments"] += event.get("delta", "")
            elif event_type == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    entry = pending_tools.pop(item.get("id", ""), None)
                    if entry is None:
                        entry = {
                            "id": item.get("call_id", ""),
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", ""),
                        }
                    elif not entry["arguments"] and item.get("arguments"):
                        entry["arguments"] = item["arguments"]
                    if not role_sent:
                        yield {"role": "assistant"}
                        role_sent = True
                    yield {
                        "tool_calls": [
                            llm.ToolInput(
                                id=entry["id"] or entry["name"],
                                tool_name=entry["name"],
                                tool_args=_parse_tool_args(entry["arguments"]),
                            )
                        ]
                    }
                elif (
                    item.get("type") == "reasoning"
                    and item.get("encrypted_content")
                    and not native_sent
                ):
                    native_sent = True
                    yield {
                        "native": {
                            "type": "reasoning",
                            "id": item.get("id", ""),
                            "encrypted_content": item["encrypted_content"],
                            "summary": [],
                        }
                    }
            elif event_type == "response.completed":
                response = event.get("response") or {}
                if usage := response.get("usage"):
                    usage_out.update(usage)
            elif event_type in ("response.failed", "response.incomplete"):
                response = event.get("response") or {}
                error = response.get("error") or {}
                details = response.get("incomplete_details") or {}
                reason = (
                    error.get("message")
                    or details.get("reason")
                    or "OpenCode response failed"
                )
                raise OpenCodeError(str(reason))
