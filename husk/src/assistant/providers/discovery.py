"""List the models an endpoint offers (used by ``POST /llm/discover``)."""
from __future__ import annotations

import httpx

from assistant.core.redact import redact
from assistant.providers.registry import effective_base_url


class DiscoveryError(RuntimeError):
    pass


async def _get_json(url: str, headers: dict, secret: str | None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise DiscoveryError(redact(f"Could not reach {url}: {type(exc).__name__}", [secret])) from exc
    if response.status_code in (401, 403):
        raise DiscoveryError("The endpoint rejected the API key")
    if response.status_code >= 400:
        raise DiscoveryError(f"The endpoint returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise DiscoveryError("The endpoint did not return JSON") from exc
    return data if isinstance(data, dict) else {"data": data}


async def discover_models(kind: str, base_url: str | None, api_key: str | None) -> list[dict]:
    base = (effective_base_url(kind, base_url) or "").rstrip("/")
    models: list[dict] = []
    if kind == "anthropic":
        root = base or "https://api.anthropic.com"
        data = await _get_json(f"{root}/v1/models?limit=100",
                               {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}, api_key)
        models = [{"id": m["id"], "name": m.get("display_name") or m["id"]} for m in data.get("data", []) if "id" in m]
    elif kind == "gemini":
        root = base or "https://generativelanguage.googleapis.com"
        data = await _get_json(f"{root}/v1beta/models?pageSize=200", {"x-goog-api-key": api_key or ""}, api_key)
        for m in data.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", ["generateContent"]):
                model_id = str(m.get("name", "")).removeprefix("models/")
                if model_id:
                    models.append({"id": model_id, "name": m.get("displayName") or model_id})
    else:
        if kind == "openai" and not base:
            base = "https://api.openai.com/v1"
        if not base:
            raise DiscoveryError("base_url is required for this provider kind")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data: dict = {}
        if kind == "ollama":  # Ollama's native listing is richer than /v1/models
            try:
                data = await _get_json(f"{base.removesuffix('/v1')}/api/tags", headers, api_key)
                models = [{"id": m["name"], "name": m["name"]} for m in data.get("models", []) if "name" in m]
            except DiscoveryError:
                models = []
        if not models:
            data = await _get_json(f"{base}/models", headers, api_key)
            models = [{"id": m["id"], "name": m["id"]} for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
    return sorted(models, key=lambda m: m["id"])
