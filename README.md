# OpenCode for Home Assistant

Use models from your [OpenCode Go](https://opencode.ai/go) subscription as Home Assistant voice and chat assistants and AI Task entities.

> **Not affiliated with, endorsed by, or supported by OpenCode or Anomaly.** This is a community integration that uses the public OpenCode Go API with your own subscription key.

## Features

- **Conversation agent** — chat in the dashboard, in voice pipelines, or from automations. Turn on *Control Home Assistant* to let it act on intents (lights, covers, scripts, and more). Off by default.
- **AI Task entity** — plain text or structured output (JSON schema) via `ai_task.generate_data`.
- **Multiple agents and model discovery** — one agent per model under a single API key; the flows list your subscription's models, with a manual override for anything missing.
- **Every OpenCode Go API family** — Chat Completions, Anthropic Messages, and OpenAI Responses.
- **Streaming responses** — voice replies start speaking before generation finishes.
- **Environment awareness** — each request tells the model it runs in Home Assistant, without overriding your instructions.

## Setup

**Requirements:** Home Assistant 2026.10 or newer, and an OpenCode Go (or Go Plus) subscription with an API key from the [OpenCode Console](https://opencode.ai/console).

### Install

**HACS**

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/aaronburt/oc-ha` as type **Integration**.
3. Install **OpenCode** and restart Home Assistant.

**Manual**

Copy `custom_components/opencode_conversation/` into your Home Assistant `config/custom_components/` directory and restart.

### First run

1. Go to **Settings → Devices & services → Add integration** and pick **OpenCode**.
2. Paste your API key and choose a model. A default conversation agent and AI Task entity are created. The agent is chat-only until you turn on *Control Home Assistant*.
3. To use it in Assist, open **Settings → Voice assistants**, select your pipeline, and choose the OpenCode agent as the *Conversation agent*.

### Adding more agents

Open the integration and choose **Add conversation agent**. Each agent has its own:

| Option | Description |
|---|---|
| **Model** | Pick one available to your subscription, or enter a **Custom model ID** for one not listed (set **API family** manually). |
| **API family** | Wire protocol: Automatic, Chat Completions, Messages, or Responses. Only needed for custom IDs. |
| **Control Home Assistant** | Off by default. Enables Assist intents. Text the model reads, such as entity names and states, can influence those actions. |
| **Instructions** | Optional extra system prompt for this agent. |
| **Maximum response tokens** | Upper limit per response. |

### AI Tasks

Use the `ai_task.generate_data` action with the OpenCode AI Task entity, for example to describe a camera snapshot or return structured data:

```yaml
action: ai_task.generate_data
data:
  task_name: describe
  instructions: "Describe what is visible in this image in one sentence."
  entity_id: ai_task.opencode_ai_task
response_variable: result
```

## Known limitations

- **No speech-to-text, text-to-speech, or image generation** — OpenCode Go has no endpoints for these, so the AI Task entity generates data only.
- **Text only** — attachments are not sent yet.
- **Model list is curated** — OpenCode adds and removes models regularly. Use *Custom model ID* plus *API family* for anything not in the list yet.
- **Capabilities vary by model** — tool calling works across all families, but quality and structured-output support differ.

## Troubleshooting

- **"Invalid API key"** — check the key in the [OpenCode Console](https://opencode.ai/console). If it was rotated, use **Reauthenticate** on the integration.
- **"OpenCode usage limit reached"** — Go plans have per-model 5-hour, weekly, and monthly limits. Switch the agent to another model or wait for the reset; check usage in the console.
- **"Model … is no longer available"** — the model was removed from Go. Edit the agent and pick another model.
- **"Model … does not support the configured API family"** — for a custom model, set the correct **API family** in the agent options.
- When reporting an issue, enable debug logging for `custom_components.opencode_conversation`.

## Privacy

- Your API key is stored in your Home Assistant configuration and sent only to `opencode.ai`.
- OpenCode Go is designed for coding agents and OpenCode monitors traffic for abuse. This integration sends typical assistant traffic; keep usage reasonable and review the [OpenCode Go docs](https://opencode.ai/v2/docs/console/go) for current terms.
- **Data handling varies by model.** The model picker marks any model that keeps prompts or may use them for training. Check the [Go privacy table](https://opencode.ai/v2/docs/console/go#privacy) before sending sensitive data.

## Removal

Remove **OpenCode** from **Settings → Devices & services**. Manual installs can then delete the `custom_components/opencode_conversation` folder.

## License

[MIT](LICENSE)
