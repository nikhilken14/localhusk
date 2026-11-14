# LLM Providers & Models

Husk treats LLMs as pluggable providers. Configuration is stored in SQLite (`provider_configs`) with API keys held exclusively in the OS keyring.

## Supported adapter families

| Family | Typical base URL | Notes |
|--------|------------------|-------|
| OpenAI-compatible | `https://api.openai.com/v1` or local (Ollama, LM Studio, vLLM, OpenRouter, …) | Uses `/chat/completions` |
| Anthropic | `https://api.anthropic.com` | Messages API |
| Gemini | Google Generative Language API | |

Discovery helpers can list models from a reachable endpoint when the provider supports it.

## Adding a model (API)

```http
POST /api/v1/llm/models
Content-Type: application/json

{
  "name": "gpt-4o-mini",
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "is_default": false
}
```

Response never echoes the key; it returns `has_api_key: true`.

```http
GET /api/v1/llm/models
PATCH /api/v1/llm/models/{id}
DELETE /api/v1/llm/models/{id}
```

## Local models (Ollama example)

1. Start Ollama and pull a model: `ollama pull llama3.2`
2. In Husk Settings or via API set:
   - provider: `openai` (compatible)
   - base_url: `http://127.0.0.1:11434/v1`
   - model name: `llama3.2`
   - api_key: any non-empty string (or leave blank if the adapter allows)

## Default model & chat selection

- Workspace default is used when a conversation has no explicit `provider_id`.
- Chat requests accept an optional `provider_id` / model override.
- Streaming uses the same selection rules.

## Usage tracking

Token counts (input/output, estimated vs exact when the provider reports them) are recorded and available under `/api/v1/usage`.

## Security

- Keys never appear in logs, API responses, or the database.
- Only local Host headers and configured CORS origins may call the API.
- For production-like local use, keep the backend bound to `127.0.0.1`.
