# OpenCode → Home Assistant — Implementation Plan

> Companion to [`research.md`](./research.md). Decisions locked via grilling 2026-10-09 (D1–D12 in M0).
> Tasks are ordered by dependency: each milestone assumes the previous one is complete. Checkboxes are the working progress list.

---

## Milestone overview

| # | Milestone | Outcome (definition of done) | Depends on |
|---|-----------|------------------------------|------------|
| M0 | Decisions & environment | All open decisions answered; dev HA + Go key ready; API facts verified | — |
| M1 | Repo & project scaffold | HACS-valid repo skeleton, CI checks running, empty integration loads in HA | M0 |
| M2 | OpenCode API client | Python client for Chat Completions + models/usage, fully unit-tested against mocked HTTP | M1 |
| M3 | Config flow & entry lifecycle | User can add integration with key; subentry/reauth flows work; entities appear in HA | M2 |
| M4 | Conversation agent (non-streaming + tools) | Assist can chat and control the home via tools | M3 |
| M5 | AI Task entity | `ai_task.generate_data` works in automations incl. structured output | M4 |
| M6 | Streaming | Token-by-token deltas; `_attr_supports_streaming`; voice pipeline quality | M4 |
| M7 | Multi-family adapters | Claude/Qwen/MiniMax (Messages) and GPT/Grok/Muse (Responses) selectable | M4 |
| M8 | Polish & release | Diagnostics, layers of quality-scale rules, HACS release v0.1.0 | M5–M7 |

Parallelisation notes: M5 and M6 can be done in either order after M4; M7a (Messages) and M7b (Responses) are independent of each other.

## Build status (2026-10-09)

**Implemented and unit-tested** — 16 tests passing against Home Assistant 2026.10.0 via PHACC:
- M1 scaffold · M2 API client (models, usage, streaming, typed errors, identity headers) · M3 config flow with subentries, reauth, reconfigure, reload-on-update · M4 conversation agent with streaming deltas and the Assist tool loop · M5 AI Task with structured output · M6 streaming for all families · M7 Chat Completions, Anthropic Messages and OpenAI Responses adapters with certified routing.
- Environment context: every request appends a short context line (model name, OpenCode Go, Home Assistant) to the system prompt; user instructions are preserved. Live-verified — the model answered *"I'm the deepseek-v4.1-flash model, running inside Home Assistant via OpenCode Go…"* (20 tests passing).

**Live QA complete (2026-10-09)** — local Docker HA 2026.10.0 at `http://localhost:8124` (container `ha-opencode-test`):
- Config flow driven through the HA API created the entry with both subentries and live model options.
- Conversation round trip via `conversation.process` returned the expected speech.
- `ai_task.generate_data` with a structure returned `{"ok": true}`.
- Full tool loop verified: "Turn on the QA Test Light." → the model called `HassTurnOn`, HA executed it, `input_boolean.qa_test_light` ended up **on** (after exposing the entity to Assist).

**Pending:**
- Assist *voice* pipeline QA (needs STT/TTS from another integration; Go has no audio endpoints).
- M8 polish: diagnostics, log-once-unavailable, exception translations.
- `v0.1.0` release + end-to-end HACS install validation (8.7).

---

## M0 — Decisions & environment (everything below is blocked by this)

### Decisions — SETTLED (grilling round 1, 2026-10-09)
- [x] D1. **Domain & display name**: domain `opencode_conversation`, display name "OpenCode".
- [x] D2. **Config architecture**: entry = API key; **config subentries** — one conversation agent per model (conversation subentry) + an AI task subentry.
- [x] D3. **Phase 1 API scope**: Chat Completions family first; Anthropic Messages / OpenAI Responses adapters in M7.
- [x] D4. **Provider scope**: Go only for v1; client parameterized (base URL / auth header / family) so Zen/Console can be added later without rework.
- [x] D5. **Default model**: `deepseek-v4.1-flash` (Chat family).
- [x] D6. **Repo & license**: public `aaronburt/oc-ha` (created at M1), MIT, codeowners `@aaronburt`; public-ready HACS presentation from day one.

### Decisions — SETTLED (grilling round 2, 2026-10-09)
- [x] D7. **First-run flow**: key → validate → model pick (default `deepseek-v4.1-flash`) → entry + default conversation subentry + AI task subentry auto-created. Model-list fetch falls back to a static list so setup never blocks.
- [x] D8. **Per-agent fields**: conversation subentry = `model`, `llm_hass_api` (default `["assist"]`), `prompt` (optional), `max_tokens` (default 1024). AI task subentry = `model` + `max_tokens`. No sampling knobs in v1; per-family extras land in M7.
- [x] D9. **Model picker policy**: certified models only by default; advanced toggle shows the full live list with a manual API-family override (default chat) and hinting errors.
- [x] D10. **429 behavior**: hard error with a clear translatable message (include `retry-after` when present); no auto-fallback in v1. Optional per-subentry fallback model parked for M8.
- [x] D11. **Brand icon**: official OpenCode assets from `opencode.ai/brand`, converted per HA brand conventions and OpenCode's brand guidance exactly; README gets a "not affiliated" note.
- [x] D12. **Adding more agents**: via the entry's "Add subentry" flow (implied by D2; not separately debated).

### Environment
- [x] E1. **Go API key**: provided by user 2026-10-09 (exposed in chat — **rotate after build**). Used for V1–V9 probes via temp file; temp key file deleted after verification.
- [x] E2. **Test HA instance**: local Docker `ghcr.io/home-assistant/home-assistant:stable`, `custom_components/` bind-mounted. Docker Desktop 29.8.1 installed (daemon must be started at M1).
- [x] E3. **Dev toolchain**: Python 3.14.7 present; add `uv`/venv, `ruff`, `pytest-homeassistant-custom-component` (PHACC pinned to the dev HA version).

### Live API verification — COMPLETE (2026-10-09; results in `research.md` → "Live verification results")
- [x] V1. Models list: authed = 38 available-to-key models (vs 45 public); same fields; **no family metadata**.
- [x] V2. `GET /zen/go/v1/usage` works; rolling/weekly/monthly `percent` + `resetsAt`. Key-validation endpoint confirmed.
- [x] V3. `/v1/messages`: `x-api-key` required (Bearer rejected); `anthropic-version` optional; `max_tokens` required.
- [x] V4. `/v1/responses`: `store:false` works (stateless OK).
- [x] V5. Tool calling verified on **all three families** (chat `tool_calls`, messages `tool_use`, responses `function_call`).
- [x] V6. Strict `response_format: json_schema` works on `deepseek-v4.1-flash`.
- [x] V7. Error shapes: 401 `AuthError`; 400 `Model is unavailable`; 400 `ModelProtocolUnsupported`; 400 `MissingSessionID`; 429 not exercised (limits not exhausted).
- [x] V8. Findings recorded in `research.md`.
- [x] V9. **Enforcement surprises**: `x-opencode-session` is mandatory on inference requests (400 without it); canonical protocol per model is enforced per the docs table.

**Exit criteria:** decisions recorded (D1–D12); V1–V9 verified and recorded; probe commands reproducible (temp scripts).

---

## M1 — Repo & project scaffold

- [ ] 1.1 Create layout (research §4.1):
  ```
  custom_components/opencode_conversation/{__init__.py,manifest.json,const.py,strings.json,translations/en.json,brand/icon.png}
  tests/ · hacs.json · README.md · LICENSE · .gitignore · pyproject.toml
  ```
- [ ] 1.2 `manifest.json` per research §1.3 (domain, version, config_flow, dependencies `["conversation"]`, `after_dependencies`, integration_type `service`, iot_class `cloud_polling`, quality_scale `bronze`, `requirements: []`).
- [ ] 1.3 Minimal `__init__.py` (`async_setup` + `CONFIG_SCHEMA`) so HA loads the entry-less integration.
- [ ] 1.4 `const.py`: `DOMAIN`, defaults, placeholder certified map (Appendix B data can live here as `CHAT_MODELS`/family enum now, full map in M7).
- [ ] 1.5 `hacs.json`: `{ "name": "OpenCode", "homeassistant": "2026.10.0" }`.
- [ ] 1.6 Brand assets (D11): official OpenCode assets from `opencode.ai/brand` (square logo → `icon.png` 256×256; wordmark → `logo.png`), converted per HA brand conventions and OpenCode's brand guidance exactly; README "not affiliated" note.
- [ ] 1.7 Dev tooling: `pyproject.toml` (ruff HA-style config, pytest, PHACC), `requirements-dev.txt` or uv lock.
- [ ] 1.8 CI: GitHub Actions — `hacs/action` (category integration), `home-assistant/actions/hassfest`, `ruff check`, `pytest`.
- [ ] 1.9 README skeleton with the Go intended-use caveat + privacy section stub.
- [ ] CI green on an empty integration. **Exit criteria:** HACS action + hassfest pass; integration appears in HA "Add integration" (no config flow yet → use a temporary placeholder flow if needed for visibility, or defer to M3).

---

## M2 — OpenCode API client (`api.py`)

- [ ] 2.1 Exceptions: `OpenCodeError`, `OpenCodeAuthError`, `OpenCodeRateLimited(retry_after)`, `OpenCodeModelNotFound`, `OpenCodeConnectionError`.
- [ ] 2.2 Session handling: inject HA `aiohttp` session (`async_get_clientsession`); base URL `https://opencode.ai/zen/go/v1`; timeout policy; retries only for idempotent GETs.
- [ ] 2.3 Identity headers on every request: `user-agent: oc-ha/<version>`, `x-opencode-session: <stable id>` (pass in per call).
- [ ] 2.4 `async_list_models()` — public GET, parse `{data:[{id,...}]}`.
- [ ] 2.5 `async_validate_key()` — `GET /usage` per V2; fallback: 1-token free-model chat call.
- [ ] 2.6 `async_chat_completions(model, messages, tools, stream, response_format, max_tokens, temperature, session_id)` — non-streaming first (JSON), structured for streaming hook in M6.
- [ ] 2.7 Error mapping from HTTP status/body to exceptions (per research §2.8 table); parse `retry-after` + ratelimit headers when present.
- [ ] 2.8 Unit tests: aioresponses/`pytest-aiohttp` mocks — success, 401, 429, 400 model-not-found, 5xx, timeout, malformed body.

**Exit criteria:** 100% of `api.py` covered; a tiny CLI-ish manual script (or pytest marked live) proves chat against the real API (manually run, key from env).

---

## M3 — Config flow & entry lifecycle

- [ ] 3.1 `config_flow.py` — `user` step: API key (`TextSelector` password) → validate (M2.5) → model picker (default `deepseek-v4.1-flash`; live list ∩ certified map, static fallback) → `async_set_unique_id(sha256(key))` + `_abort_if_unique_id_configured()` → create entry `{api_key}` + default conversation subentry + AI task subentry (D7).
- [ ] 3.2 `__init__.py` — real `async_setup_entry`: build client into `entry.runtime_data` (typed alias), validate key (401→`ConfigEntryAuthFailed`, unreachable→`ConfigEntryNotReady`), forward platforms for subentries.
- [ ] 3.3 `async_unload_entry` + platform unload.
- [ ] 3.4 Conversation **subentry flow** (add/edit one agent): `model`, `llm_hass_api` (default `["assist"]`), `prompt`, `max_tokens` (default 1024); advanced: show-all-models toggle + API-family override (M7). Refresh-models action (D8, D9).
- [ ] 3.5 AI task subentry flow: `model` + `max_tokens` (may be delivered with M5) (D8).
- [ ] 3.6 Reauth: `async_step_reauth`/`reauth_confirm`; re-auth updates `entry.data`, keeps original unique ID.
- [ ] 3.7 `strings.json` + `translations/en.json`: labels, `data_description`, errors, abort reasons.
- [ ] 3.8 Tests: happy path, invalid key, duplicate entry abort, subentry add/edit, reauth updates entry (not new entry), default subentries created.
- [ ] 3.9 `quality_scale.yaml` with exemptions mirrored from core OpenAI (polling/discovery/etc.).

**Exit criteria:** add/reconfigure/reauth/unload and subentry management all work in the dev HA UI; config flow at full test coverage.

---

## M4 — Conversation agent (non-streaming + tool control)

- [ ] 4.1 `entity.py` base: `OpenCodeBaseLLMEntity(Entity)` — identity/device info from subentry, `_attr_has_entity_name`, subentry data access.
- [ ] 4.2 Chat log → Chat Completions conversion: roles, history, attachments ignored in v1.
- [ ] 4.3 Tool conversion: `chat_log.llm_api.tools` → function tools via `probatio.to_openapi(..., custom_serializer=llm.selector_serializer, openapi_version="3.1.0")`; strip unsupported keys (`oneOf/anyOf/allOf/enum/not`) like core.
- [ ] 4.4 Tool loop: parse `tool_calls`, inject assistant tool call + `role:"tool"` results; cap at `MAX_TOOL_ITERATIONS = 10`; handle `finish_reason`.
- [ ] 4.5 `conversation.py`: one entity per conversation subentry; `ConversationEntity` + `AbstractConversationAgent`; `async_set_agent`/`async_unset_agent` lifecycle; `async_provide_llm_data(...)`; `CONF_LLM_HASS_API` → `ConversationEntityFeature.CONTROL`; return via `conversation.async_get_result_from_chat_log`.
- [ ] 4.6 Error surface: translate client exceptions to `HomeAssistantError` with actionable messages (limit reached, model mismatch with family hint).
- [ ] 4.7 Optional: `chat_log.async_trace` token stats from `usage`.
- [ ] 4.8 Tests: message conversion, tool call round-trip (mock API + HA tool), iteration cap, errors.
- [ ] 4.9 Manual QA in dev HA: add to Assist pipeline, "turn on the kitchen light", multi-turn follow-up.

**Exit criteria:** practical Assist control works with a chat-family model (e.g. `deepseek-v4.1-flash`); test suite green.

---

## M5 — AI Task entity

- [ ] 5.1 `ai_task.py`: `AITaskEntity` with `GENERATE_DATA | SUPPORT_ATTACHMENTS` (no `GENERATE_IMAGE`).
- [ ] 5.2 `_async_generate_data`: same engine loop (higher cap, e.g. 1000); return text when no `task.structure`.
- [ ] 5.3 Structured output: build JSON schema from `task.structure` (probatio → OpenAPI); try `response_format.json_schema` (per V6); fallback to prompt-guided JSON; parse + validate; translatable error on parse failure.
- [ ] 5.4 Forward `ai_task` platform in setup; entity naming/registry.
- [ ] 5.5 Tests: plain text task, structured task (mock two models: one native schema, one prompt fallback), malformed output.
- [ ] 5.6 Manual QA: automation using `ai_task.generate_data` (e.g. summarize a camera snapshot text).

**Exit criteria:** AI Task entity selectable wherever HA lists them; automation demo works.

---

## M6 — Streaming

- [ ] 6.1 SSE parser for Chat Completions (`choices[].delta.content`, `delta.tool_calls` fragments, `finish_reason`, usage with `stream_options.include_usage`).
- [ ] 6.2 Translator → HA delta dicts (`{"content": ...}`, `{"tool_calls":[llm.ToolInput]}`, role switches) consumed by `chat_log.async_add_delta_content_stream`.
- [ ] 6.3 `_attr_supports_streaming = True`; keep non-streaming fallback if a model/endpoint rejects streaming.
- [ ] 6.4 Tests: delta ordering, tool-call fragment assembly, aborted stream, usage passthrough.
- [ ] 6.5 Manual QA: voice pipeline — confirm sentence-by-sentence TTS streaming behavior.

**Exit criteria:** voice assistant responses stream; no regressions in M4/M5 tests.

---

## M7 — Multi-family adapters

### M7a — Anthropic Messages
- [ ] 7a.1 Client method: `x-api-key` + verified `anthropic-version`; `max_tokens` required; `system` split; content blocks.
- [ ] 7a.2 Tool schema (`input_schema`), tool_use/tool_result blocks; SSE event mapping (`content_block_delta`, `message_delta`, …).
- [ ] 7a.3 Structured-output fallback path (no native JSON mode).
- [ ] 7a.4 Tests with recorded/mocked SSE fixtures.

### M7b — OpenAI Responses
- [ ] 7b.1 Client method: `input[]` items, function call items, `text.format`; decide stateless (`store:false`) per V4.
- [ ] 7b.2 SSE event mapping (`response.output_item.added/done`, `response.output_text.delta`, function args events) mirroring core `openai_conversation/entity.py`.
- [ ] 7b.3 Reasoning items: drop/pass-through policy (`thinking_content`).
- [ ] 7b.4 Tests with mocked SSE fixtures.

### M7c — Routing
- [ ] 7c.1 Full certified map in `const.py` (research Appendix B) + user override in options.
- [ ] 7c.2 Unknown-model policy: hidden by default; "show all" advanced toggle defaults to chat, errors hint at override.
- [ ] 7c.3 Model selector labels (family/cost hints), refresh action.
- [ ] 7c.4 Cross-family integration tests (dispatch chooses right endpoint/auth per model).

**Exit criteria:** `claude-haiku-5-5`, `gpt-6-luna`, `qwen3.8-flash` all usable through the same conversation entity.

---

## M8 — Polish & release

- [ ] 8.1 `diagnostics.py` (key redacted, masked config, model list, family map version).
- [ ] 8.2 Reconfigure flow (change model/settings without re-auth) — Gold rule.
- [ ] 8.3 Log-once-when-unavailable + entity unavailable handling (Silver).
- [ ] 8.4 README complete: install (HACS + manual), setup, options, automations/AI Task examples, known limitations, troubleshooting, privacy table (per-model retention/training), Go intended-use caveat, removal instructions.
- [ ] 8.5 Translations review; exception messages translatable (Gold).
- [ ] 8.6 Test coverage ≥ 95% across modules; CI green (hassfest, HACS, ruff, pytest).
- [ ] 8.7 Version bump + GitHub release `v0.1.0`; validate HACS install end-to-end on a clean HA.
- [ ] 8.8 Optional: usage sensor (poll `/usage` every 5–15 min, disabled-by-default), Zen/Console provider mode, per-subentry 429 fallback model (D10), upstream-to-Core preparation (Platinum typing).

**Exit criteria:** a stranger can install via HACS, add their key, pick a model, and use Assist + AI Tasks; caveats documented.

---

## Critical path

```
M0 (decisions + V1–V8 verification)
 └─ M1 scaffold ── M2 api client ── M3 config flow ── M4 conversation/tools
                                                        ├─ M5 ai task
                                                        ├─ M6 streaming
                                                        └─ M7 families ── M8 release
```

**Next actionable items:** export `OPENCODE_GO_API_KEY` on this machine → run V1–V8 probes → M1 scaffold. No code before the explicit go-ahead.
