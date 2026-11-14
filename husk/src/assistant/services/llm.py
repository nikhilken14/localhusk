"""Resolve stored model configurations into call-ready snapshots, run test calls."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.core.errors import APIError
from assistant.core.redact import redact
from assistant.core.secrets import SecretStoreError, get_secret
from assistant.core.timeutil import utcnow
from assistant.db.models import ProviderConfig
from assistant.providers.base import ChatMessageInput, Completion, GenerationOptions
from assistant.providers.registry import effective_base_url, registry

log = logging.getLogger("assistant.llm")


@dataclass(frozen=True)
class ProviderSnapshot:
    """Plain data copy of a ProviderConfig + its secret, safe to hand to another thread/task."""

    id: str
    name: str
    kind: str
    model: str
    base_url: str | None
    api_key: str | None
    temperature: float
    max_output_tokens: int

    def options(self, temperature: float | None = None, max_output_tokens: int | None = None,
                *, cap_tokens: int | None = None) -> GenerationOptions:
        tokens = max_output_tokens if max_output_tokens is not None else self.max_output_tokens
        if cap_tokens:
            tokens = min(tokens, cap_tokens)
        return GenerationOptions(self.model, self.temperature if temperature is None else temperature, tokens)


def get_default_provider(db: Session) -> ProviderConfig | None:
    return db.scalar(select(ProviderConfig).where(ProviderConfig.is_default.is_(True)).limit(1))


def snapshot(provider: ProviderConfig) -> ProviderSnapshot:
    try:
        secret = get_secret(provider.credential_ref)
    except SecretStoreError as exc:
        raise APIError(503, str(exc), "secret_store_unavailable") from exc
    return ProviderSnapshot(
        provider.id, provider.name, provider.kind, provider.model,
        effective_base_url(provider.kind, provider.base_url), secret,
        provider.temperature, provider.max_output_tokens,
    )


def resolve_provider(db: Session, provider_id: str | None = None, *fallback_ids: str | None) -> ProviderConfig:
    """Explicit id -> fallback ids (e.g. conversation/agent preference) -> workspace default."""
    for candidate in (provider_id, *fallback_ids):
        if candidate:
            provider = db.get(ProviderConfig, candidate)
            if provider:
                return provider
            if candidate == provider_id:
                raise APIError(404, "Model connection not found")
    provider = get_default_provider(db)
    if not provider:
        raise APIError(400, "Configure an LLM model and set it as default", "no_default_model")
    return provider


def safe_error(exc: Exception, secret: str | None = None) -> str:
    """Short, secret-free description suitable for the UI and the log table."""
    status = getattr(exc, "status_code", None)
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    prefix = f"{type(exc).__name__}" + (f" (HTTP {status})" if status else "")
    return redact(f"{prefix}: {message}", [secret])[:300]


async def complete(provider: ProviderSnapshot, messages: list[ChatMessageInput], options: GenerationOptions) -> Completion:
    try:
        return await registry.get(provider.kind).complete(messages, options, provider.api_key, provider.base_url)
    except Exception as exc:  # noqa: BLE001 - provider SDKs raise many types
        log.warning("LLM call failed for %s/%s: %s", provider.name, provider.model, safe_error(exc, provider.api_key),
                    extra={"category": "llm"})
        raise APIError(502, f"LLM request failed: {safe_error(exc, provider.api_key)}", "llm_error") from exc


async def run_connectivity_test(db: Session, provider: ProviderConfig) -> dict:
    """Make a tiny completion, record the outcome on the config, and report latency/error."""
    snap = snapshot(provider)
    started = time.perf_counter()
    ok, error, sample = True, None, ""
    try:
        result = await registry.get(snap.kind).complete(
            [ChatMessageInput("user", "Reply with exactly: connection successful")],
            snap.options(0.0, 32), snap.api_key, snap.base_url,
        )
        sample = result.text[:160]
    except Exception as exc:  # noqa: BLE001
        ok, error = False, safe_error(exc, snap.api_key)
    latency = int((time.perf_counter() - started) * 1000)
    provider.last_test_at = utcnow()
    provider.last_test_ok = ok
    provider.last_test_latency_ms = latency if ok else None
    provider.last_test_error = None if ok else error
    db.commit()
    level = logging.INFO if ok else logging.WARNING
    log.log(level, "Model test %s/%s: %s", snap.name, snap.model, "ok" if ok else error, extra={"category": "llm"})
    return {"ok": ok, "status": "connected" if ok else "error", "model": snap.model, "latency_ms": latency if ok else None,
            "error": error, "sample": sample, "checked_at": provider.last_test_at}
