from __future__ import annotations

from assistant.providers.adapters import AnthropicAdapter, GeminiAdapter, OpenAIAdapter

PROVIDER_KINDS = {"openai", "anthropic", "gemini", "openai_compatible", "ollama"}

# Used when a configuration leaves base_url empty.  Without this, "ollama" would silently
# talk to api.openai.com.
DEFAULT_BASE_URLS = {"ollama": "http://localhost:11434/v1"}


def effective_base_url(kind: str, base_url: str | None) -> str | None:
    return (base_url or "").strip() or DEFAULT_BASE_URLS.get(kind)


class ProviderRegistry:
    def __init__(self):
        self._providers = {
            "openai": OpenAIAdapter(use_completion_tokens=True),
            "openai_compatible": OpenAIAdapter(),
            "ollama": OpenAIAdapter(),
            "anthropic": AnthropicAdapter(),
            "gemini": GeminiAdapter(),
        }

    def get(self, kind: str):
        if kind not in self._providers:
            raise ValueError(f"Unsupported provider kind: {kind}")
        return self._providers[kind]


registry = ProviderRegistry()
