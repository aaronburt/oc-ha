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
