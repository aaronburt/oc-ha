# OpenCode Go × Home Assistant — Integration Research

> **Status: research only — no code written yet (per instruction).**
> Date: 2026-10-09 · Target stack: Home Assistant Core 2026.10 (current), OpenCode Go API (V2 docs)
> Goal: a HACS-distributable custom integration that lets a user paste an OpenCode Go API key and use Go models as Assist conversation agents / AI Task entities, the same way `ollama`, `openai_conversation`, or `google_generative_ai_conversation` are used.

---

## TL;DR — the three questions answered

| # | Question | Answer |
|---|----------|--------|
| 1 | **What does Home Assistant require?** | A UI-configured (config flow) custom component with a `manifest.json`, an async config entry, a `ConversationEntity` registered via `conversation.async_set_agent`, `ConversationEntityFeature.CONTROL` + LLM tools for Assist control, an `ai_task.AITaskEntity` for AI Tasks, `probatio` schemas (HA ≥ 2026.9), entity unique IDs, reauth, unload, tests, and brand assets. Full checklist in [§1](#1-home-assistant-integration-requirements-compliance--contract). |
| 2 | **Which API family should we use?** | **No single family covers all Go models.** OpenAI **Chat Completions** covers the most Go models (~16+ documented, all the open-weight coding models), maps 1:1 onto HA's `ChatLog`, and is the simplest to implement — so it is the right **first** target. Claude Haiku 5.5, MiniMax and Qwen are **Anthropic Messages**; GPT, Grok and Muse Spark are **OpenAI Responses**. Gemini is **not offered on Go** (Console/Zen only). Recommended: multi-family adapter, Chat Completions first. Full comparison in [§2](#2-endpoint-choice-openai-vs-anthropic-vs-gemini-vs-responses). |
| 3 | **Can we pull the model list?** | **Yes** — `GET https://opencode.ai/zen/go/v1/models` returns a live OpenAI-style list (verified, **no auth needed**). **But** it gives only `id`/`created`/`owned_by`: no API-family, capability, pricing or context metadata. So: dynamic list for *availability*, plus a small embedded *certified family map* (from OpenCode docs + verified sources) with a user override for unknown/new IDs. Full strategy in [§3](#3-model-discovery). |

**One important caveat up front (policy, not code):** OpenCode's Go docs state the subscription is _"designed for OpenCode and other coding agents that produce similar types of requests"_ and that _"traffic is monitored for abuse"_. A Home Assistant assistant is not a coding agent. This does not appear to be an outright prohibition (the docs also say Go works with other clients, and publish the generic OpenAI-compatible endpoints), but the integration must identify itself truthfully, use stable session IDs, and document the intended-use caveat. See [§2.7](#27-policy--compliance-considerations-read-this).

---

## Live verification results (2026-10-09)

All V1–V8 checks from the implementation plan were run against the live Go API with a real subscription key. **This section supersedes the earlier VERIFY markers wherever it conflicts.**

### Confirmed facts

| Check | Result |
|---|---|
| V1 models list | `GET /zen/go/v1/models` **with auth** returns 38 models; the public call returns 45. The authed list is the models actually available to the key (public-only extras: `glm-5`, `grok-4.5`, `hy3-preview`, `kimi-k2.5`, `mimo-v2-omni`, `mimo-v2-pro`, `qwen3.5-plus`). No richer metadata either way — the certified family map is still required. |
| V2 usage | `GET /zen/go/v1/usage` works with `Authorization: Bearer`; shape `{"usage":{"rolling":{"status","percent","resetsAt"},"weekly":{...},"monthly":{...}}}`. Confirmed as the key-validation endpoint. |
| V3 messages auth | `x-api-key` required; `Authorization: Bearer` is rejected (401 `Missing API key`). `anthropic-version` header is **optional** (request succeeds without it). `max_tokens` is **required** (400 upstream `max_tokens: Field required`). |
| V4 responses | `store: false` accepted → stateless mode works. |
| V5 tools | Chat Completions function calling works (`finish_reason: "tool_calls"`, arguments as a JSON string). |
| V6 structured output | `response_format: {"type":"json_schema","json_schema":{...,"strict":true}}` works on `deepseek-v4.1-flash` (returned exactly `{"ok":true}`). |
| V7 errors | Bad key → 401 `{"type":"error","error":{"type":"AuthError","message":"Unauthorized"}}`. Unknown model → 400 `{"error":{"type":"server_error","message":"Upstream request failed: Model is unavailable."}}`. 429 shape not exercised (plan limits not exhausted). |
| **Session header** | `x-opencode-session` is **mandatory on inference requests**: omitting it returns 400 `MissingSessionID` ("Request is missing x-opencode-session and cannot be routed efficiently"). The docs say "should"; reality is "must". Send a stable per-conversation ID on every inference request. |

### Cross-protocol routing (unexpected nuance)

Sending a model to a non-canonical protocol is enforced per model with a distinct, safe-to-surface error (`ModelProtocolUnsupported`):

| Probe | Result |
|---|---|
| `claude-haiku-5-5` → `/chat/completions` | 400 `ModelProtocolUnsupported` ("Model does not support this protocol.") |
| `gpt-6-luna` → `/chat/completions` | 400 `ModelProtocolUnsupported` |
| `qwen3.8-flash` → `/responses` | 400 `ModelProtocolUnsupported` |
| `minimax-m3` → `/chat/completions` | **200** — docs route is Messages, chat also works but thinking arrives inline as `<think>…</think>` text |
| `deepseek-v4.1-flash` → `/messages` | **200** — returns an Anthropic-style `thinking` block |
| `deepseek-v4.1-flash` → `/responses` | **200** |

Conclusion: the docs endpoint table is the **canonical, best-quality** route per model. Some models additionally accept other protocols, but non-canonical routes change how reasoning is surfaced (inline text vs structured fields). Keep the certified map as the router.

### Other observations

- Chat Completions on `deepseek-v4.1-flash` exposes `reasoning_content` alongside `content` → map to HA `thinking_content` where useful.
- `gpt-6-luna`/`deepseek` Responses calls include `prompt_cache_retention: "24h"` and `parallel_tool_calls: true` — noted for diagnostics, no action required.
- Error taxonomy to implement: 401 `AuthError` (→ reauth), 400 `MissingSessionID` (client bug — never expected in production), 400 `ModelProtocolUnsupported` (family map/override issue), 400 `Model is unavailable` (removed model), 400 `max_tokens: Field required` (messages family).

---

## 1. Home Assistant integration requirements (compliance & contract)

### 1.1 What "adding a model like Ollama/Gemini/OpenAI" actually means

In HA terms, an LLM provider integration optionally provides up to four entity platforms:

| Platform | Purpose | Needed for us? |
|----------|---------|----------------|
| `conversation` | The assistant: chat in the dashboard, voice pipelines ("Assist"), automations via `conversation.process`. | **Yes — core deliverable** |
| `ai_task` | Structured "AI Task" generation (generate data / JSON from instructions, e.g. camera snapshot analysis). Added in HA 2025.7. | **Yes — high value, near-free once the LLM loop exists** |
| `stt` | Speech-to-text. | No — Go offers no STT endpoint |
| `tts` | Text-to-speech. | No — Go offers no TTS endpoint |

The built-in `conversation` integration owns the Assist pipeline and looks up the *conversation agent* by its entity ID. A conversation agent becomes selectable in **Settings → Voice assistants** once its config entry registers an agent.

The core `openai_conversation` integration is the canonical reference (it now supports conversation + AI task + STT + TTS in one entry). We read its current source as the template; see [Appendix C](#appendix-c--sources).

### 1.2 Distribution model: custom component (HACS) vs Core

| | Custom component (HACS) | Core integration |
|---|---|---|
| Review | None by HA team (HACS validates structure only) | Full code review, quality scale gates |
| Manifest | `version` **required** (SemVer/CalVer) | `version` must be omitted |
| Docs | README in repo | `home-assistant.io/integrations/<domain>` |
| Install | HACS / manual copy to `config/custom_components/` | Ships with HA |
| Requirements | Must not add deps already in Core `requirements.txt`; may pin extra deps | Must use pinned deps |

**Recommendation:** build as a custom component, structured so it *could* be upstreamed later (mirror core naming/patterns). That is exactly how `openai_conversation` is written today and how most community LLM integrations ship.

HACS structural requirements (from HACS "Publish → Integrations"):
- exactly **one** integration directory: `custom_components/<domain>/…` — all runtime files inside it;
- `manifest.json` must define `domain`, `name`, `version`, `documentation`, `issue_tracker`, `codeowners`;
- a **brand directory** with `icon.png` in the repo (`custom_components/<domain>/brand/icon.png`);
- GitHub releases preferred but optional; repo must be a valid HACS repository (or added as custom repo).

### 1.3 Proposed `manifest.json`

```json
{
  "domain": "opencode_conversation",
  "name": "OpenCode",
  "version": "0.1.0",
  "config_flow": true,
  "dependencies": ["conversation"],
  "after_dependencies": ["assist_pipeline", "intent"],
  "codeowners": ["@aaronburt"],
  "documentation": "https://github.com/aaronburt/oc-ha",
  "issue_tracker": "https://github.com/aaronburt/oc-ha/issues",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "quality_scale": "bronze",
  "requirements": []
}
```

Notes:
- `integration_type: service` — same as `openai_conversation` (it provides one service per config entry, not a hub).
- `iot_class: cloud_polling` — we talk to a cloud API; we do not poll on a schedule, but this is the accepted class for cloud LLM services (OpenAI uses it).
- `dependencies: ["conversation"]` is **required** so the conversation component is loaded; `after_dependencies` matches core OpenAI.
- `requirements: []` — **recommended**: implement the HTTP client with `aiohttp` (already bundled with HA). This avoids pip installs in HAOS containers and gives us full control over required headers (`user-agent`, `x-opencode-session`). If we ever want the official `openai` SDK (like core OpenAI does), it must be pinned, but it is heavier and still doesn't help with `messages`/`responses` routing.
- Domain naming candidates: `opencode_conversation` (recommended, mirrors `openai_conversation`), `opencode`, `opencode_go`. Must be unique in the HA instance, lowercase, immutable after release.

### 1.4 Config flow & config entry lifecycle (Bronze requirement: UI setup)

Required/recommended pieces, per the official config-flow docs:

1. **`config_flow.py`** with `class OpenCodeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)`.
2. **User step**: ask for the **API key** (`TextSelector` with `type: password`), then **validate** it (Bronze rule `test-before-configure`). Suggested validation call: `GET /zen/go/v1/usage` with the key (401/403 on bad key) rather than a paid chat request. *VERIFY with a real key; fallback is a 1-token chat request to a free model.*
3. **Unique ID**: `sha256(api_key).hexdigest()` — stable, non-reversible, satisfies `unique-config-entry` (prevents adding the same subscription twice). Do **not** reset the unique ID during reauth when the key rotates.
4. **Options flow** (`OptionsFlowWithConfigEntry` or equivalent) for everything user-editable: model, LLM HASS API selection, prompt, max tokens, temperature, "model family" override. Per docs, `ConfigEntry.data` holds credentials (`api_key`), `ConfigEntry.options` holds preferences.
5. **Reauth step** (`async_step_reauth` / `async_step_reauth_confirm`): trigger on 401/403 from the API; required for Silver.
6. **Reconfigure step** (optional, Gold): change non-auth settings without re-adding the entry.
7. **Runtime data**: `entry.runtime_data = OpenCodeClient(...)` with a typed alias `type OpenCodeConfigEntry = ConfigEntry[OpenCodeClient]` — Bronze rule `runtime-data`.
8. **Setup failure handling**: raise `ConfigEntryAuthFailed` on 401 (starts reauth), `ConfigEntryNotReady` on timeouts/5xx (HA retries with backoff).
9. **Unload support**: `async_unload_entry` forward/unload platforms (Silver rule).
10. **Translations**: `strings.json` + `translations/en.json`; all form fields need labels and `data_description` (Bronze rule calls this out explicitly).
11. **`async_setup`** with `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)` (defensive copy of the core pattern).
12. `quality_scale.yaml` tracking file (see [§1.8](#18-quality-scale-mapping)).

### 1.5 Conversation platform contract

From the developer docs and the current core OpenAI implementation:

```python
class OpenCodeConversationEntity(
    conversation.ConversationEntity,
    conversation.AbstractConversationAgent,
    OpenCodeBaseLLMEntity,
):
    _attr_supports_streaming = True          # enables Assist voice/TTS sentence streaming
    # _attr_supported_features = ConversationEntityFeature.CONTROL  (only when an LLM API is configured)
    supported_languages = MATCH_ALL           # return "*"; Go models are multilingual
```

Mandatory wiring:
- **Registration**: `conversation.async_set_agent(hass, entry, self)` in `async_added_to_hass`; `conversation.async_unset_agent(hass, entry)` in `async_will_remove_from_hass` (Bronze `entity-event-setup`).
- **Entity identity**: `_attr_has_entity_name = True`, `_attr_unique_id = entry.entry_id` (or a subentry ID if we adopt the subentry pattern), `DeviceInfo(entry_type=DeviceEntryType.SERVICE, identifiers={(DOMAIN, entry_id)}, manufacturer="OpenCode", model=<configured model>)` — creates the service "device" in the registry (Gold `devices`).
- **`_async_handle_message(user_input, chat_log)`**:
  1. `await chat_log.async_provide_llm_data(user_input.as_llm_context(DOMAIN), options.get(CONF_LLM_HASS_API), options.get(CONF_PROMPT), user_input.extra_system_prompt)` — wraps in `try/except conversation.ConverseError` and returns `err.as_conversation_result()`.
  2. Run the LLM/tool loop against Go.
  3. Return `conversation.async_get_result_from_chat_log(user_input, chat_log)` (current core pattern; builds the `ConversationResult`, speech, and `continue_conversation` from the chat log).
- **`ConversationEntityFeature.CONTROL`** signals the agent can control HA; only set it when an LLM API is selected (matches core OpenAI).

Optional: `async_prepare(language)` for warm-up — not needed.

**Modern vs simple structure:** current core OpenAI uses **config subentries** (one entry = API key; child subentries per conversation/ai-task/STT/TTS "service"). For a custom component v1 we can use a single entry + options flow (like the older core pattern and most community integrations). The subentry pattern is the future-proof one if upstreaming is ever intended. **Decision needed.**

### 1.6 LLM tools contract ("interact like the other assist models")

This is what makes the agent *control* the home. Per the official LLM API docs and `homeassistant/helpers/llm.py`:

- The selected API(s) come from `llm.async_get_apis(hass)` and are stored under `CONF_LLM_HASS_API` (`"assist"` is the built-in Assist API, which exposes intents like `HassTurnOn`, `HassLightSet`, etc.).
- After `async_provide_llm_data`, `chat_log.llm_api` is an `APIInstance` with:
  - `tools: list[llm.Tool]` — each has `name`, `title`, `description`, `parameters` (a `probatio.Schema`), `annotations` (read_only/destructive/…), `integration`;
  - `api_prompt: str` — instructions for the model (already handled by `async_provide_llm_data`/chat log content);
  - `custom_serializer` — convert selectors to JSON schema (`llm.selector_serializer`).
- Convert each tool to the wire format with `probatio.to_openapi(tool.parameters, custom_serializer=chat_log.llm_api.custom_serializer, openapi_version="3.1.0")`. Core OpenAI strips `oneOf`/`anyOf`/`allOf`/`enum`/`not` for strictness; we should do the same fallback.
- **Tool loop**: after each model response, `chat_log.unresponded_tool_results` tells us whether tools must be executed. `chat_log.async_add_delta_content_stream(agent_id, generator)` executes HA tools and yields the results as `ToolResultContent`; we then send the updated conversation back to the model. Core caps at `MAX_TOOL_ITERATIONS = 10`; AI Task uses 1000. We must cap too.
- Tool call/result mapping (from core entity.py and the dev docs example):
  - model asks for tool → emit `{"tool_calls": [llm.ToolInput(id=..., tool_name=..., tool_args={...})]}`;
  - HA runs it and yields `{"role": "tool_result", "tool_call_id": ..., "tool_name": ..., "result": llm.ToolResult(data={...}, error=False)}`;
  - next request includes the assistant tool call + tool result in the model's native format.
- **Streaming deltas** accepted by `async_add_delta_content_stream`: dicts with any of `role`, `content`, `thinking_content`, `tool_calls`, `native` (for provider-native payloads); plus tool-result dicts. Core OpenAI's `_transform_stream` is a full worked example of mapping SSE events → these dicts.
- Optional `chat_log.async_trace({"stats": {"input_tokens": ..., "output_tokens": ...}})` to surface token usage in HA traces.

**Reality check per model:** tool-calling support is not advertised by Go's models endpoint. The Go models are coding-agent models and all validated clients (Codex/Claude Code-shaped) use tools, so tools are expected to work across the three families — but we should degrade gracefully (surface a clear error; allow the user to disable `CONTROL` per entry) and verify per family with a live key.

### 1.7 AI Task platform contract

From the AI Task developer docs and core OpenAI `ai_task.py`:

- `class OpenCodeAITaskEntity(ai_task.AITaskEntity, OpenCodeBaseLLMEntity)`.
- Features: `AITaskEntityFeature.GENERATE_DATA | AITaskEntityFeature.SUPPORT_ATTACHMENTS`. **Skip `GENERATE_IMAGE`** — the Go catalog has no image-generation models (the deepseek "vision" model is image *input*, not generation).
- `_async_generate_data(task: GenDataTask, chat_log) -> GenDataTaskResult`:
  - run the same LLM/tool loop (with a much higher iteration cap, e.g. 1000, like core);
  - if `task.structure` (a `probatio.Schema` of selectors) is set → request **structured output** in the model's native JSON-schema dialect and parse it with `json_loads`; else return the text;
  - return `GenDataTaskResult(conversation_id=chat_log.conversation_id, data=...)`.
- This gives "Generate data" AI Tasks in automations (the 2025.7+ feature), and makes our provider show up wherever HA lists AI Task entities.

*Structured output caveat:* JSON-schema/structured mode support varies by family (OpenAI chat completions `response_format.json_schema`, Responses `text.format`, Anthropic has no native JSON-schema mode — prompt-guided JSON). Plan: try native structured output where guaranteed; otherwise prompt the model with the schema and parse/validate, raising a translatable `HomeAssistantError` on failure (core does the same).

### 1.8 Quality scale mapping

New integrations must reach **Bronze**. Mapping of the Bronze checklist to this integration:

| Bronze rule | Status / how |
|---|---|
| `action-setup` | **Exempt** — we register no service actions |
| `appropriate-polling` | **Exempt** — no polling loops (an optional usage sensor would poll; not v1) |
| `brands` | `custom_components/opencode_conversation/brand/icon.png` (local brand images allowed since HA 2026.3) |
| `common-modules` | single shared LLM client + base entity |
| `config-flow` | user step, options, reauth; `data_description` on all fields |
| `config-flow-test-coverage` | pytest via PHACC, full coverage of `config_flow.py` |
| `dependency-transparency` | no external pip deps; `aiohttp` from HA |
| `docs-*` | README covers install/removal/high-level description; core-style docs if upstreamed |
| `entity-event-setup` | set/unset agent in lifecycle methods |
| `entity-unique-id` | entry ID / subentry ID |
| `has-entity-name` | `_attr_has_entity_name = True` |
| `runtime-data` | typed `entry.runtime_data` |
| `test-before-configure` | validate key in config flow |
| `test-before-setup` | validate in `async_setup_entry`; `ConfigEntryNotReady`/`ConfigEntryAuthFailed` |
| `unique-config-entry` | hashed-key unique ID |

Silver stretch (recommended sooner rather than later): `config-entry-unloading` (done from day 1), `reauthentication-flow`, `log-when-unavailable`, `entity-unavailable`, `parallel-updates` (=0 for conversation/ai_task), 95% test coverage.
Gold stretch: devices (done), `diagnostics` (redact key), `reconfiguration-flow`, richer docs. `discovery*`/`stale-devices`/`entity-category` etc. are exempt (service integration, same exemptions core OpenAI declares in its `quality_scale.yaml`).

### 1.9 Testing, lint & CI

- **pytest-homeassistant-custom-component (PHACC)** — the standard test harness for custom integrations; pins a matching HA version. Test: config flow (happy path, invalid key, duplicate, reauth), setup/unload, conversation with mocked HTTP (aiohttp `mocked` fixtures), tool call loop, AI task structured output, error mapping (401/429/5xx).
- **HACS validation**: `hacs/action` GitHub Action (`category: integration`) + `home-assistant/actions/hassfest` (manifest validation works for custom repos).
- **Lint**: HA uses `ruff` (config from `homeassistant` package conventions); `mypy` for strict typing is a Platinum target — nice to have.

### 1.10 Branding

- Since HA 2026.3, custom integrations can bundle `brand/icon.png` (and `logo.png`) locally; HACS requires at least `icon.png`.
- Sizes: follow HA brand guidelines (`icon.png` square, `logo.png` landscape; see brands repo). Generate from the OpenCode mark, respecting its licensing/trademark usage.

### 1.11 Version & compatibility targets

- **probatio, not voluptuous**: HA 2026.9+ validates with `probatio` (drop-in API); importing `voluptuous` is *banned* in integrations since 2026.10. New code must `import probatio`.
- `_attr_supports_streaming`, `async_add_delta_content_stream`, `user_input.extra_system_prompt`, `conversation.async_get_result_from_chat_log`, and the LLM tool model are all present in current HA (2026.10). These were introduced across 2025.7–2026.x, so pin `homeassistant >= 2026.10` in `hacs.json`.
- Python: dev with Python 3.13/3.14 era toolchain (HA CI tracks 3.13/3.14).
- `hacs.json` minimal: `{ "name": "OpenCode", "homeassistant": "2026.10.0" }`.

---

## 2. Endpoint choice: OpenAI vs Anthropic vs Gemini vs Responses

### 2.1 First, don't confuse the two OpenCode products

| | **OpenCode Go** (the subscription, the user's key) | **OpenCode Console / Zen** (pay-as-you-go) |
|---|---|---|
| Base URL | `https://opencode.ai/zen/go/v1` | `https://opencode.ai/zen/v1` |
| Auth | Go subscription API key | Console API key (service accounts for automation) |
| API families | Chat Completions, Anthropic Messages, OpenAI Responses | Chat Completions, Anthropic Messages, Responses, **Gemini**, SystemOne (Jev) |
| Models endpoint | `GET /zen/go/v1/models` | `GET /zen/v1/models` |
| Usage endpoint | `GET /zen/go/v1/usage` (used by community tooling) | Console billing APIs |
| Models | Curated fixed set (see §2.3) | Much larger catalog incl. GPT-5.x, Claude Opus, Gemini, Mistral, free models |

The Go docs' "Endpoints" table is the authoritative source for Go wire families. The Console docs show the same pattern for Zen. Community tooling (e.g. `opencode-go-proxy`) treats the two as separate providers; a Go key is provisioned for the Go gateway. **Our integration targets the Go endpoints** because that is what "OpenCode Go subscription" means. A later phase could add Zen/Console as a second "provider mode" in the same integration (configurable base URL + key), which would also unlock Gemini routes — but that changes billing/consent semantics and should be explicit.

### 2.2 The three Go families (verified)

| Family | Endpoint | Auth header(s) | Wire format |
|---|---|---|---|
| OpenAI Chat Completions | `POST /zen/go/v1/chat/completions` | `Authorization: Bearer <key>` | `messages[]`, `tools[]` (function), `tool_calls`, `response_format`, SSE `stream: true` |
| Anthropic Messages | `POST /zen/go/v1/messages` | `x-api-key: <key>` + `anthropic-version: 2023-06-01`* | separate `system`, `max_tokens` **required**, content blocks, `tools[].input_schema`, SSE event types |
| OpenAI Responses | `POST /zen/go/v1/responses` | `Authorization: Bearer <key>` | `input[]`/`output[]` items, `function_call` items, `text.format`, rich SSE events, optional stateful `store` |

\* The `anthropic-version` value is taken from community proxy source; **VERIFY against a live request at implementation time** (standard value is `2023-06-01`).

This auth split is the single most important implementation detail and is **not clearly documented** in the Go docs table — we verified it in the source of `kartikkabadi/opencode-go-proxy` (`go_upstream.py`), which exercises the real endpoints:

```python
# chat/completions
auth_headers={"authorization": f"Bearer {api_key}"}
# messages
auth_headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
```

### 2.3 Model coverage per family (Go)

**Certified families** (OpenCode Go docs endpoint table + verified legacy IDs from the proxy's `go_models.py`; full table in [Appendix B](#appendix-b--certified-go-model--family-map)):

- **OpenAI Responses (6):** `grok-4.7`, `grok-4.6`, `gpt-6-luna`, `gpt-5.6-luna`, `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor` (legacy: `grok-4.5`)
- **OpenAI Chat Completions (~18):** all `glm-*`, `kimi-k3`/`kimi-k2.7-code`/`kimi-k2.6`, `longcat-2.0`, all `deepseek-v4*`, `mimo-v2.5*`, `hy4-preview`, `hy3`, free previews (`longcat-2.5-preview-free`, `step-5-preview-free`), legacy `glm-5`, `kimi-k2.5`, `qwen3.5-plus`
- **Anthropic Messages (8):** `claude-haiku-5-5`, `minimax-m3`, `minimax-m2.7`, `minimax-m2.5`, `qwen3.8-max`, `qwen3.8-flash`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-plus`

Takeaway: the **majority of Go models speak Chat Completions**, but several of the most attractive HA models (cheap GPT-6 Luna, Claude Haiku 5.5) require Responses/Messages.

### 2.4 Comparison for a Home Assistant conversation agent

| Criterion | Chat Completions | Anthropic Messages | OpenAI Responses | Gemini |
|---|---|---|---|---|
| Go model coverage | **Highest** (~18) | 8 | 6 | **0 (not on Go)** |
| Mapping to HA `ChatLog` | 1:1 (roles, tool_calls, results) | Medium (system split, blocks, `max_tokens`) | Medium (input/output items, event parsing) | n/a |
| Tool calling | Yes (function tools) | Yes (`input_schema`) | Yes (function items) | n/a |
| Streaming | Simple SSE `choices[].delta` | Event-typed SSE | Event-typed SSE (many event types) | n/a |
| Structured output | `response_format: json_schema` | prompt-guided (no JSON-schema mode) | `text.format` | n/a |
| Auth | Bearer | `x-api-key` + version | Bearer | n/a |
| HA core reference | Historical + current LiteLLM patterns | `anthropic` integration | **`openai_conversation` (current, complete)** | `google_generative_ai_conversation` |
| Effort | **Low** | Medium | Medium-High | n/a |
| AI SDK designation on Go | `@ai-sdk/openai-compatible` | `@ai-sdk/anthropic` | `@ai-sdk/openai` | `@ai-sdk/google` (Zen only) |

### 2.5 Recommendation

1. **Phase 1 — OpenAI Chat Completions only.** Biggest model coverage, cleanest mapping, simplest streaming, Bearer auth, `json_schema` structured output for AI Tasks, and dozens of interoperable clients to sanity-check against. A working HA integration on this family alone is genuinely useful (DeepSeek V4, GLM 5.2/5.3, Kimi, MiniMax M2.7 on chat? — no, MiniMax is messages; still ~18 models).
2. **Phase 2 — family router.** Introduce an internal `api_family` decision per model (certified map + user override + safe default), add Anthropic Messages and OpenAI Responses adapters. Then Claude Haiku 5.5 / GPT-6 Luna / Grok become selectable. Reuse the exact serialization/streaming patterns from core `anthropic` and `openai_conversation` integrations.
3. **Do not choose Gemini for this project.** It is not served on the Go gateway at all. (Zen/Console support it; only relevant if we later add a Console provider mode.)

**Why not "just use OpenAI Responses because HA core OpenAI does?"** Core OpenAI targets it because OpenAI's newest models require it. On Go, the Responses family covers only GPT/Grok/Muse — choosing it alone would exclude most of the catalog. Chat Completions is the better *single* target; Responses is the better *second/third* adapter.

### 2.6 Required client identity headers (Go compliance)

OpenCode asks clients to (verified against the live API — the session header is enforced):
1. send typical coding-agent traffic — _(policy caveat below)_;
2. **identify with their own user agent** (not a generic SDK/library UA);
3. **send a stable `x-opencode-session` per conversation** — mandatory: inference requests without it are rejected with 400 `MissingSessionID`. OpenCode uses it for routing optimization and prompt caching.

Implementation:
- `user-agent: oc-ha/<integration-version>` on every request (`aiohttp` default UA must be overridden).
- `x-opencode-session: <stable id>` — derive from HA's `chat_log.conversation_id` (or a ULID stored on the entity per conversation) so multi-turn chats keep one session value. The community proxy derives a UUID from a hash of the first conversation item when no session is supplied; we can just use HA's conversation ID directly.
- Chat Completions requests should set `stream_options: {"include_usage": true}` so token accounting arrives in the stream (this also helps prompt-cache reporting).

### 2.7 Policy / compliance considerations (read this)

- Go docs: *"OpenCode Go is designed for OpenCode and other coding agents that produce similar types of requests. Traffic is monitored for abuse that degrades the experience for other users."* A smart-home assistant is **not** a coding-agent workload. Practically: keep request sizes modest, set a truthful UA, use one stable session per conversation, don't hammer the API, and document in the README that users are using their own subscription in a way that is adjacent to (not endorsed by) OpenCode's stated purpose.
- Also stated: Go/Go Plus are for single-member workspaces; no pooling/sharing. The integration must not facilitate shared keys (it doesn't — one key per config entry, unique ID per key).
- If OpenCode later blocks assistant-style traffic, the clean fallback is the **Console/Zen pay-as-you-go** endpoints (`https://opencode.ai/zen/v1`), which are sold as a general gateway — worth designing the client with a configurable base URL so switching is a config change, not a rewrite.
- Privacy: most Go models are 0-day retention, no training; **exceptions**: Grok/GPT (30-day retention), Claude (30-day), Muse Spark Contributor (trains on prompts, region-limited). Surface the per-model privacy class in README/config help — HA users are eating dinner conversations through this.
- HA custom integrations are not audited by Home Assistant; README must say so.

### 2.8 Errors, limits, usage

- Go limits are dollar-based per model: **5-hour = 20%**, weekly = 50%, monthly = 100% of each model's monthly limit ($15–$60 on Go, higher on Go Plus). Exceeding a model's limit yields 429; free preview models stay available.
- Trailing usage: `GET https://opencode.ai/zen/go/v1/usage` (auth required; shape per community tooling: rolling/weekly/monthly windows). Could power an optional HA diagnostic sensor in a later phase.
- Recommended HA error mapping:
  | HTTP | Meaning | HA behavior |
  |---|---|---|
  | 401/403 | bad/revoked key | `ConfigEntryAuthFailed` → reauth flow |
  | 429 | model/plan limit or abuse throttle | `HomeAssistantError("OpenCode usage limit reached for this model…")`; consider optional auto-fallback to a free/cheap configured model |
  | 400/404 model | model not served on that family / removed | actionable error naming the model + family; trigger model-list refresh |
  | 5xx / timeout | upstream trouble | `ConfigEntryNotReady` in setup; `HomeAssistantError`/log-once at runtime |

### 2.9 Wire examples

Chat Completions (most models):
```http
POST https://opencode.ai/zen/go/v1/chat/completions
Authorization: Bearer <key>
Content-Type: application/json
x-opencode-session: 01J...
user-agent: oc-ha/0.1.0

{ "model": "deepseek-v4.1-flash",
  "messages": [ {"role": "system", "content": "..."},
                {"role": "user", "content": "Turn on the kitchen lights"} ],
  "tools": [ { "type": "function",
               "function": { "name": "HassTurnOn",
                             "description": "...",
                             "parameters": { "type": "object", "properties": { ... } } } } ],
  "stream": true, "stream_options": { "include_usage": true } }
```

Anthropic Messages (Claude/Qwen/MiniMax):
```http
POST https://opencode.ai/zen/go/v1/messages
x-api-key: <key>
anthropic-version: 2023-06-01
Content-Type: application/json

{ "model": "claude-haiku-5-5", "max_tokens": 1024,
  "system": "...",
  "messages": [ {"role": "user", "content": "Turn on the kitchen lights"} ],
  "tools": [ { "name": "HassTurnOn", "description": "...", "input_schema": { ... } } ] }
```

OpenAI Responses (GPT/Grok/Muse):
```http
POST https://opencode.ai/zen/go/v1/responses
Authorization: Bearer <key>

{ "model": "gpt-6-luna",
  "input": [ {"role": "system", "content": "..."}, {"role": "user", "content": "..."} ],
  "tools": [ { "type": "function", "name": "HassTurnOn", "parameters": { ... } } ],
  "stream": true }
```

---

## 3. Model discovery

### 3.1 What the API gives us (verified live, 2026-10-09)

```http
GET https://opencode.ai/zen/go/v1/models     # no Authorization header required
200 OK
{"object":"list","data":[{"id":"minimax-m3","object":"model","created":1791559385,"owned_by":"opencode"}, ...]}
```

- **45 model IDs** currently returned (full capture in [Appendix A](#appendix-a--live-go-model-list-2026-10-09)).
- Fields: `id`, `object`, `created` (identical timestamp for every model — useless for sorting/recency), `owned_by` (`opencode`).
- The **free/pay-as-you-go Console catalog** is a different endpoint: `GET https://opencode.ai/zen/v1/models` (also unauthenticated; broader list, different products/models).

### 3.2 Limitations that shape the design

1. **No API-family metadata.** The endpoint cannot tell us whether `minimax-m3` must go to `/messages` or `/chat/completions`. Routing requires an embedded map ([§3.3](#33-family-resolution-strategy)).
2. **No capabilities.** No tool-calling flag, no vision flag, no context size, no pricing/limits.
3. **Superset of docs.** The live list contains models beyond the docs endpoint table (e.g. `qwen3.7-max`, `kimi-k2.5`, `glm-5`, `grok-4.5`, `hy3-preview`, `omen-alpha`, `deepseek-flash`, `mimo-v2-pro`, `mimo-v2-omni`) — some are legacy or uncertified. Conversely, docs sometimes describe models with friendlier names than IDs.
4. **Family is product-specific.** e.g. `qwen3.5-plus` is Chat Completions on Go (per verified legacy mapping) but Messages on Zen (per Console table); `minimax-m3` is Messages on Go, Chat Completions on Zen. **Do not share prefix heuristics across products.**

### 3.3 Family resolution strategy

Layered, in priority order:

1. **Certified map** embedded in `const.py` (generated from [Appendix B](#appendix-b--certified-go-model--family-map)) → exact family per known ID.
2. **User override** in the options flow: if a model is missing/mis-mapped, the user can pick the family explicitly (advanced field). This is the escape hatch for new/legacy IDs.
3. **Unknown ID policy (recommended):** hide uncertified models from the picker by default; offer a "show all models from the live list" advanced toggle where uncertified IDs default to Chat Completions and surface a clear 400 error (with hint to set the family) if wrong.
4. Prefix heuristics are **not** used as a silent default in v1 (too risky per point 4 above); they can assist ordering/labels at most.

The community proxy chose a deliberately stricter variant — "an unknown ID is not guessed into the wrong protocol" — and only exposes documented/verified IDs. That's the safest posture.

### 3.4 Capabilities we must infer or defer

- **Tool calling:** assumed for all families (validated clients use tools), degrade gracefully if a model rejects tools.
- **Vision/attachments:** only `deepseek-v4-flash-vision-exp` is called out as vision on Go. v1: no attachment support needed; add `SUPPORT_ATTACHMENTS` later if vision models prove reliable.
- **Image generation:** none on Go → no `GENERATE_IMAGE`.
- **Context windows / token pricing:** not exposed. Ship known values from docs in a static table for UI hints only (e.g. max_tokens default 1024–4096); never rely on them for logic.
- **Structured output:** per-family behavior ([§2.4](#24-comparison-for-a-home-assistant-conversation-agent)); prompt-based fallback.

### 3.5 Refresh & key validation strategy

- **Key validation** (config flow + setup): prefer `GET /zen/go/v1/usage` with the key (auth-gated, free) over a paid chat call. *VERIFY shape/behavior live.* Fallback: minimal chat request to a free model (`longcat-2.5-preview-free`) with `max_tokens: 1`.
- **Model list**: fetch during config flow (short timeout) to populate the model selector; store the selection in options; offer a **"refresh models"** action in the options flow that re-fetches and re-renders. Cache the list in the entry (options or runtime data) — no background polling (keeps Bronze `appropriate-polling` exempt and avoids noise).
- **Drift handling**: if a request fails with `400/model not found`, trigger a refresh and show an actionable error; the certified map only needs updating on integration releases (with a note in the README that Go's list changes).

### 3.6 Open questions from research (RESOLVED — see "Live verification results" above)

| # | Question | Why it matters | How to verify |
|---|---|---|---|
| 1 | Does an authenticated `/zen/go/v1/models` return richer fields than the public call? | Could make the certified map unnecessary | `curl -H "Authorization: Bearer $KEY" .../models` and diff |
| 2 | Exact `anthropic-version` value accepted by `/messages`; does it also accept `Authorization: Bearer`? | Required for the Messages adapter | Single request, inspect 400 text |
| 3 | Does `/responses` accept `store: false` (stateless)? Does it return reasoning items? | Streaming translation complexity | Test request |
| 4 | Which models honor `response_format: json_schema`? | AI Task structured output quality | Test per family |
| 5 | Tool-calling behavior per family (esp. `mimo-*`, `hy3`, free previews) | `CONTROL` availability | Scripted tool call |
| 6 | `/zen/go/v1/usage` shape and quota headers on 200/429 (`x-ratelimit-*` / `anthropic-ratelimit-*`) | Optional usage sensors; better errors | Test request |
| 7 | Rate-limit status code and body for plan exhaustion | Error mapping | Exhaust a model limit (or read headers under load) |

---

## 4. Proposed architecture (for implementation later — no code yet)

### 4.1 Repository layout

```
oc-ha/
├── custom_components/
│   └── opencode_conversation/
│       ├── __init__.py          # setup/unload, client in runtime_data
│       ├── manifest.json
│       ├── const.py             # domain, defaults, certified model→family map
│       ├── api.py               # aiohttp client: models(), chat(), messages(), responses(), usage()
│       ├── entity.py            # base entity: chat-log <-> wire conversion, tool loop, streaming
│       ├── conversation.py      # ConversationEntity
│       ├── ai_task.py           # AITaskEntity (GENERATE_DATA | SUPPORT_ATTACHMENTS)
│       ├── config_flow.py       # user / options / reauth (+ reconfigure later)
│       ├── strings.json
│       ├── translations/en.json
│       ├── quality_scale.yaml
│       └── brand/icon.png
├── tests/                       # PHACC tests
├── docs/research.md             # this file
├── hacs.json
└── README.md
```

### 4.2 Module responsibilities

- **`api.py`** — one small async client (`aiohttp.ClientSession` injected from HA, e.g. `async_get_clientsession(hass)`), base URL `https://opencode.ai/zen/go/v1`, timeouts, retries for idempotent GETs, error translation to typed exceptions (`OpenCodeAuthError`, `OpenCodeRateLimited`, `OpenCodeModelNotFound`). Always sends `user-agent` and `x-opencode-session`. Family-specific methods:
  - `list_models()`, `get_usage()`
  - `chat_completions(model, messages, tools, stream, ...)`
  - `messages(model, system, messages, tools, ...)`
  - `responses(model, input_items, tools, ...)`
- **`entity.py`** — the shared engine (mirrors core OpenAI `entity.py`):
  - convert `chat_log.content` → family-native request (system prompt, history, tool calls/results);
  - convert family-native deltas/events → `AssistantContentDeltaDict`/tool-result dicts;
  - the tool iteration loop; token tracing; JSON structured-output request/parse.
- **`conversation.py` / `ai_task.py`** — thin platform classes wiring the engine to HA (as in [§1.5](#15-conversation-platform-contract)/[§1.7](#17-ai-task-platform-contract)).

### 4.3 Config & options design

- `entry.data`: `{ "api_key": "..." }` (validated, unique-ID = sha256(key)).
- `entry.options`:
  - `model` (SelectSelector populated from live list ∩ certified map, with override);
  - `api_family` (auto from map | explicit override);
  - `llm_hass_api` (multi-select of `llm.async_get_apis()`; default `["assist"]`);
  - `prompt` (TextSelector, multi-line; prepended system prompt);
  - `max_tokens` (NumberSelector; model-family default);
  - `temperature` (optional, only where supported by the family/model).
- Options flow includes **"Refresh model list"** and clear help text per field (`data_description`).

### 4.4 Conversation data flow (Phase 1, chat completions)

```
User (Assist/chat) → ConversationEntity._async_handle_message
  └─ chat_log.async_provide_llm_data(as_llm_context, llm_api, prompt, extra_system_prompt)
  └─ loop (max 10):
       api.chat_completions(model, chat_log.content→messages, tools=llm_api.tools→functions, stream=True)
       ├─ SSE deltas → chat_log.async_add_delta_content_stream(agent_id, gen)
       │    (text deltas, tool_call deltas; HA executes HA tools, yields tool results)
       └─ append converted content; repeat while chat_log.unresponded_tool_results
  └─ return conversation.async_get_result_from_chat_log(user_input, chat_log)
```

### 4.5 AI Task data flow

```
Automation → ai_task.generate_data → OpenCodeAITaskEntity._async_generate_data(task, chat_log)
  └─ same engine loop, max 1000 iterations
  └─ task.structure ? request json_schema output & parse : return text
  └─ GenDataTaskResult(conversation_id, data)
```

### 4.6 Phasing

| Phase | Scope | Notes |
|---|---|---|
| 0 | Repo scaffold, manifest, HACS files, brand icon, README skeleton | No runtime logic yet |
| 1 | Chat Completions conversation + AI Task (non-streaming first) | Proves key, model list, tool loop |
| 2 | SSE streaming deltas + token tracing + polished errors | Voice/TTS streaming quality |
| 3 | Messages + Responses adapters behind family router | Full Go catalog |
| 4 | HACS polish: diagnostics, optional usage sensor, reconfigure flow, translations | Silver/Gold stretch |

### 4.7 Decisions needed before implementation

1. **Domain name** (`opencode_conversation` recommended) and repo/branding ownership.
2. **Structure**: single config entry + options (simpler v1) vs subentries (core-style, future-proof)? Recommendation: single entry for v1; refactor to subentries only if upstreaming becomes a goal.
3. **Scope of Phase 1**: Chat Completions only (recommended) vs all three families from the start.
4. **Go-only or Go + Console/Zen provider mode** (affects ToS posture and unlocks Gemini).
5. **Default model** shipped in the integration (suggestion: `deepseek-v4.1-flash` — cheap, fast, chat family; or `glm-5.3-flash`).
6. **Repo public now** (needed for HACS `documentation`/`issue_tracker` URLs) or local-only until MVP?

---

## Appendix A — Live Go model list (2026-10-09)

Raw capture of `GET https://opencode.ai/zen/go/v1/models` (unauthenticated):

```json
{"object":"list","data":[
 {"id":"minimax-m3","owned_by":"opencode"},{"id":"minimax-m2.7"},{"id":"minimax-m2.5"},
 {"id":"kimi-k3"},{"id":"kimi-k2.7-code"},{"id":"kimi-k2.6"},{"id":"longcat-2.0"},
 {"id":"kimi-k2.5"},{"id":"glm-5.2"},{"id":"glm-5.3-flash"},{"id":"glm-5.3"},
 {"id":"glm-5.1"},{"id":"glm-5"},{"id":"deepseek-v4-pro"},{"id":"deepseek-v4-flash"},
 {"id":"deepseek-flash"},{"id":"deepseek-v4.1-flash"},{"id":"deepseek-v4-flash-vision-exp"},
 {"id":"qwen3.7-max"},{"id":"qwen3.8-max"},{"id":"qwen3.8-flash"},{"id":"qwen3.7-plus"},
 {"id":"qwen3.6-plus"},{"id":"qwen3.5-plus"},{"id":"mimo-v2-pro"},{"id":"mimo-v2-omni"},
 {"id":"mimo-v2.6-pro"},{"id":"mimo-v2.6-flash"},{"id":"longcat-2.5-preview-free"},
 {"id":"step-5-preview-free"},{"id":"mimo-v2.5-pro"},{"id":"mimo-v2.5"},{"id":"hy4-preview"},
 {"id":"hy3"},{"id":"hy3-preview"},{"id":"claude-haiku-5-5"},{"id":"gpt-5.6-luna"},
 {"id":"grok-4.5"},{"id":"grok-4.7"},{"id":"grok-4.6"},{"id":"muse-spark-1.3-contributor"},
 {"id":"muse-spark-1.2-contributor"},{"id":"omen-alpha"},{"id":"gpt-6-luna"},
 {"id":"space-bunny"}
]}
```

(`created` and full `object` fields omitted above for brevity; all `created` values identical.) 45 IDs — a superset of the documented endpoint table. Uncatalogued IDs (`deepseek-flash`, `mimo-v2-pro`, `mimo-v2-omni`, `hy3-preview`, `omen-alpha`, …) must not be guessed into a wire family.

## Appendix B — Certified Go model → family map

Source of truth: OpenCode Go docs endpoint table (2026-10-09) + verified legacy map in `opencode-go-proxy/go_models.py`.

| Family | Models |
|---|---|
| `responses` | `grok-4.7`, `grok-4.6`, `gpt-6-luna`, `gpt-5.6-luna`, `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor` · legacy verified: `grok-4.5` |
| `chat/completions` | `glm-5.3-flash`, `glm-5.3`, `glm-5.2`, `glm-5.1`, `kimi-k3`, `kimi-k2.7-code`, `kimi-k2.6`, `longcat-2.0`, `longcat-2.5-preview-free`, `step-5-preview-free`, `deepseek-v4.1-flash`, `deepseek-v4-pro`, `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`, `mimo-v2.6-flash`, `mimo-v2.6-pro`, `mimo-v2.5`, `mimo-v2.5-pro`, `hy4-preview`, `hy3`, `space-bunny` · legacy verified: `glm-5`, `kimi-k2.5`, `qwen3.5-plus` |
| `messages` | `claude-haiku-5-5`, `minimax-m3`, `minimax-m2.7`, `minimax-m2.5`, `qwen3.8-max`, `qwen3.8-flash`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-plus` |
| **unmapped (live only)** | `deepseek-flash`, `mimo-v2-pro`, `mimo-v2-omni`, `hy3-preview`, `omen-alpha` (and any future additions — user override required) |

## Appendix C — Sources

**OpenCode**
- OpenCode V2 docs hub + index: https://opencode.ai/v2/docs/ and https://opencode.ai/v2/llms.txt
- Go subscription guide + endpoints + limits + privacy: https://opencode.ai/v2/docs/console/go/
- Console models (Zen) endpoint table & pricing (contrast): https://opencode.ai/v2/docs/console/models/
- Console inference API (OpenAI/Anthropic/Gemini-compatible, service accounts): https://opencode.ai/v2/docs/console/api/inference/
- Live Go model list: https://opencode.ai/zen/go/v1/models (fetched 2026-10-09, no auth)
- Live Zen model list: https://opencode.ai/zen/v1/models (contrast; includes Gemini/free models)
- Community protocol reference `opencode-go-proxy` (verified family map & auth headers): https://github.com/kartikkabadi/opencode-go-proxy — `src/opencode_go_proxy/go_models.py`, `go_upstream.py`, `opencode_session.py`, `upstream_headers.py`

**Home Assistant**
- Integration manifest: https://developers.home-assistant.io/docs/creating_integration_manifest/
- Config flow: https://developers.home-assistant.io/docs/config_entries_config_flow_handler/
- Integration quality scale + checklist: https://developers.home-assistant.io/docs/core/integration-quality-scale/ and /checklist
- Conversation entity: https://developers.home-assistant.io/docs/core/entity/conversation/
- AI Task entity: https://developers.home-assistant.io/docs/core/entity/ai-task/
- LLM API (tools/prompt/options flow): https://developers.home-assistant.io/docs/core/llm/
- Probatio (validation engine since 2026.9): https://developers.home-assistant.io/blog/2026/09/30/probatio-validation-engine/
- Local brand images for custom integrations (HA 2026.3+): https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/
- Core `openai_conversation` reference implementation (manifest, `__init__.py`, `conversation.py`, `ai_task.py`, `entity.py`, `quality_scale.yaml`): https://github.com/home-assistant/core/tree/dev/homeassistant/components/openai_conversation
- HA `llm` helper source (Tool/APIInstance/selector serialization): https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/llm.py
- HA 2026.10 release: https://www.home-assistant.io/blog/2026/10/07/release-202610/

**Distribution**
- HACS publishing requirements (repo structure, manifest keys, brand assets): https://www.hacs.xyz/docs/publish/integration/
