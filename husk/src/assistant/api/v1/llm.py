from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.errors import APIError
from assistant.core.secrets import SecretStoreError, delete_secret, get_secret, store_secret
from assistant.db.models import ProviderConfig
from assistant.providers.discovery import DiscoveryError, discover_models
from assistant.providers.registry import PROVIDER_KINDS
from assistant.services import llm

router = APIRouter(tags=["llm"])
log = logging.getLogger("assistant.llm")


class ModelBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    base_url: str | None = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, description="Write-only. Omitted or blank keeps the stored key; send clear_api_key=true to remove it.")
    max_output_tokens: int = Field(default=2048, ge=1, le=128000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    is_default: bool = False

    @field_validator("name", "model")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class ModelCreate(ModelBase):
    pass


class ModelUpdate(ModelBase):
    is_default: bool | None = None
    clear_api_key: bool = False


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    kind: str
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = Field(default=None, description="Existing connection whose stored key should be used")


def _check_kind(kind: str) -> None:
    if kind not in PROVIDER_KINDS:
        raise APIError(422, f"kind must be one of: {', '.join(sorted(PROVIDER_KINDS))}")


def public(p: ProviderConfig) -> dict:
    status = "unknown" if p.last_test_ok is None else ("connected" if p.last_test_ok else "error")
    return {
        "id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "model": p.model,
        "has_api_key": bool(p.credential_ref), "max_output_tokens": p.max_output_tokens, "temperature": p.temperature,
        "is_default": p.is_default,
        "connectivity": {"status": status, "latency_ms": p.last_test_latency_ms, "checked_at": p.last_test_at, "error": p.last_test_error},
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def _get(db: Session, model_id: str) -> ProviderConfig:
    p = db.get(ProviderConfig, model_id)
    if p is None:
        raise APIError(404, "Model connection not found")
    return p


def _set_default(db: Session, p: ProviderConfig) -> None:
    for other in db.scalars(select(ProviderConfig).where(ProviderConfig.id != p.id, ProviderConfig.is_default.is_(True))):
        other.is_default = False
    p.is_default = True


def _store_key(p: ProviderConfig, key: str) -> None:
    ref = p.credential_ref or f"provider:{uuid4()}"
    try:
        store_secret(ref, key.strip())
    except SecretStoreError as exc:
        raise APIError(503, str(exc), "secret_store_unavailable") from exc
    p.credential_ref = ref


@router.get("/llm/models")
def list_models(db: Session = Depends(get_db)):
    return [public(p) for p in db.scalars(select(ProviderConfig).order_by(ProviderConfig.created_at))]


@router.post("/llm/models", status_code=201)
def create_model(payload: ModelCreate, db: Session = Depends(get_db)):
    _check_kind(payload.kind)
    p = ProviderConfig(name=payload.name, kind=payload.kind, base_url=(payload.base_url or "").strip() or None, model=payload.model,
                       max_output_tokens=payload.max_output_tokens, temperature=payload.temperature)
    if payload.api_key and payload.api_key.strip():
        _store_key(p, payload.api_key)
    first = db.scalar(select(ProviderConfig.id).limit(1)) is None
    db.add(p)
    db.flush()
    if payload.is_default or first:
        _set_default(db, p)
    db.commit()
    return public(p)


@router.put("/llm/models/{model_id}")
def update_model(model_id: str, payload: ModelUpdate, db: Session = Depends(get_db)):
    p = _get(db, model_id)
    _check_kind(payload.kind)
    p.name, p.kind, p.model = payload.name, payload.kind, payload.model
    p.base_url = (payload.base_url or "").strip() or None
    p.max_output_tokens, p.temperature = payload.max_output_tokens, payload.temperature
    if "api_key" in payload.model_fields_set and payload.api_key and payload.api_key.strip():
        _store_key(p, payload.api_key)
    # blank/empty api_key is ignored so edit forms that re-send "" do not wipe the keyring entry
    if getattr(payload, "clear_api_key", False):
        try:
            delete_secret(p.credential_ref)
        except SecretStoreError as exc:
            raise APIError(503, str(exc), "secret_store_unavailable") from exc
        p.credential_ref = None
    if payload.is_default:
        _set_default(db, p)
    p.last_test_at = p.last_test_ok = p.last_test_latency_ms = p.last_test_error = None  # config changed: old test is stale
    db.commit()
    return public(p)


@router.delete("/llm/models/{model_id}", status_code=204)
def delete_model(model_id: str, db: Session = Depends(get_db)):
    p = _get(db, model_id)
    credential_ref = p.credential_ref
    was_default = p.is_default
    db.delete(p)
    db.flush()
    if was_default:  # never leave the workspace without a default if any model remains
        successor = db.scalar(select(ProviderConfig).order_by(ProviderConfig.created_at).limit(1))
        if successor:
            successor.is_default = True
    db.commit()
    # Only remove the key after the DB transaction succeeds; otherwise a rollback
    # would leave a provider row pointing at a missing credential.
    try:
        delete_secret(credential_ref)
    except SecretStoreError:
        log.exception("Could not remove credential for deleted provider", extra={"category": "llm"})


@router.post("/llm/models/{model_id}/default")
def set_default_model(model_id: str, db: Session = Depends(get_db)):
    p = _get(db, model_id)
    _set_default(db, p)
    db.commit()
    return public(p)


@router.post("/llm/models/{model_id}/test", summary="Validate connectivity (always 200; see `ok`)")
async def test_model(model_id: str, db: Session = Depends(get_db)):
    return await llm.run_connectivity_test(db, _get(db, model_id))


@router.post("/llm/discover")
async def discover(payload: DiscoverRequest, db: Session = Depends(get_db)):
    _check_kind(payload.kind)
    key = payload.api_key.strip() if payload.api_key else None
    base_url = payload.base_url
    if payload.model_id:
        stored = _get(db, payload.model_id)
        try:
            key = key or get_secret(stored.credential_ref)
        except SecretStoreError as exc:
            raise APIError(503, str(exc), "secret_store_unavailable") from exc
        base_url = base_url or stored.base_url
    try:
        models = await discover_models(payload.kind, base_url, key)
    except DiscoveryError as exc:
        raise APIError(502, str(exc), "discovery_failed") from exc
    return {"kind": payload.kind, "models": models}
