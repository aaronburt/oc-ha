# OpenCode for Home Assistant

Use models from your [OpenCode Go](https://opencode.ai/go) subscription as Home Assistant voice/chat assistants and AI Task entities — the same way the Ollama, OpenAI, and Google Generative AI integrations work.

> **Not affiliated with, endorsed by, or supported by OpenCode or Anomaly.** This is a community integration that uses the public OpenCode Go API with your own subscription key.

## Features

- **Assist conversation agent** — chat in the dashboard, use it in voice pipelines, or call it from automations. Select *Assist* as the Home Assistant API to let the model control your home with intents (lights, covers, scripts, and so on).
- **AI Task entity** — use `ai_task.generate_data` in automations, including structured output (JSON schema) for models that support it.
- **Multiple agents per subscription** — add one conversation agent per model (for example a cheap model for voice and a stronger model for automations). Each agent is a config subentry under a single API key.
- **All three OpenCode Go API families** — Chat Completions models (DeepSeek V4, GLM, Kimi, LongCat, MiMo, …), Anthropic Messages models (Claude Haiku 5.5, MiniMax, Qwen), and OpenAI Responses models (GPT, Grok, Muse Spark).
- **Streaming responses** — token-by-token streaming, so Assist voice responses can start speaking before the model has finished.
- **Model discovery** — the setup flow and agent options show the models available to *your* subscription, with a manual override for new or unlisted models.

## Requirements

- Home Assistant **2026.10** or newer.
- An **OpenCode Go** (or Go Plus) subscription and an API key from the [OpenCode Console](https://opencode.ai/console).

## Installation

### HACS

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/aaronburt/oc-ha` as type **Integration**.
3. Install **OpenCode** and restart Home Assistant.

### Manual

Copy `custom_components/opencode_conversation/` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

1. Go to **Settings → Devices & services → Add integration** and search for **OpenCode**.
2. Paste your OpenCode Go API key and pick a model. A default assistant and an AI Task entity are created automatically.
3. To use it in Assist, go to **Settings → Voice assistants**, select your pipeline, and choose the OpenCode assistant as the *Conversation agent*.

### Adding more agents

Open the OpenCode integration, then **Add conversation agent** to create additional agents with other models or prompts. Each agent can have its own:

| Option | Description |
|---|---|
| **Model** | Any model available to your subscription (certified set by default). |
| **Custom model ID** | Use a model that is not listed yet. Set the API family manually when doing this. |
| **API family** | Which wire protocol the model speaks: Automatic, Chat Completions, Messages, or Responses. Only needed for custom models. |
| **Control Home Assistant** | Select *Assist* to let the agent control your home. Leave empty for a chat-only agent. |
| **Instructions** | Optional extra system prompt for this agent. |
| **Maximum response tokens** | Upper limit per response. |

### AI Tasks

Use the `ai_task.generate_data` action with the OpenCode AI Task entity, for example to summarise a camera snapshot or generate structured data:

```yaml
action: ai_task.generate_data
data:
  task_name: describe
  instructions: "Describe what is visible in this image in one sentence."
  entity_id: ai_task.opencode_ai_task
response_variable: result
```

## Known limitations

- **No STT/TTS.** OpenCode Go does not offer speech-to-text or text-to-speech endpoints; use another integration for those pipeline stages.
- **No image generation.** Go has no image generation models, so the AI Task entity only generates data.
- **Attachments are not supported yet.** AI tasks and conversations currently send text only.
- **Family mapping is curated.** OpenCode adds models regularly. New models are used via the *Custom model ID* + *API family* fields until a release ships an updated mapping.
- **Model capabilities vary.** Tool calling is supported across the three families but individual models differ in quality; structured output is requested natively where available and falls back to prompt-guided JSON on Anthropic Messages models.

## Troubleshooting

- **"Invalid API key"** — check the key in the OpenCode Console. If it was rotated, use **Reauthenticate** on the integration.
- **"OpenCode usage limit reached"** — Go plans have per-model 5-hour/weekly/monthly limits. Switch the agent to another model or wait for the reset; you can check usage in the [console](https://opencode.ai/console).
- **"Model … is no longer available"** — the model was removed from Go. Edit the agent and pick another model.
- **"Model … does not support the configured API family"** — for a custom model, set the correct **API family** in the agent options.
- Enable debug logging for `custom_components.opencode_conversation` when reporting issues.

## Privacy and intended use

- Your API key is stored in your Home Assistant configuration and sent only to `opencode.ai`.
- **OpenCode Go is designed for coding agents**, and OpenCode states that traffic is monitored for abuse. This integration sends typical assistant traffic (chat, tool calls) — use it with that in mind, keep usage reasonable, and review the [OpenCode Go docs](https://opencode.ai/v2/docs/console/go) for current terms.
- Data handling varies per model. Most Go models are zero-retention and not used for training; Grok/GPT requests are retained up to 30 days, Claude up to 30 days, and Muse Spark Contributor models may be used for training and are region-limited. Check the [Go privacy table](https://opencode.ai/v2/docs/console/go#privacy) before sending sensitive data.

## Removal

Remove the integration from **Settings → Devices & services**. Manual installs can delete the `custom_components/opencode_conversation` folder afterwards.

## License

[MIT](LICENSE)
