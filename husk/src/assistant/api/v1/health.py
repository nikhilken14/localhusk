from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.config import APP_VERSION, get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001
        database = "error"
    body = {"status": "ok" if database == "ok" else "degraded", "app": get_settings().app_name, "version": APP_VERSION, "database": database}
    return JSONResponse(body, status_code=200 if database == "ok" else 503)


@router.get("/ready", summary="Readiness: database, schema, secret store, background workers")
def readiness(request: Request, db: Session = Depends(get_db)):
    checks: dict[str, dict] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        checks["schema"] = {"ok": revision is not None, "revision": revision}
    except Exception:  # noqa: BLE001
        checks["schema"] = {"ok": False, "error": "migrations have not been applied"}
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        backend = keyring.get_keyring()
        checks["secret_store"] = {"ok": not isinstance(backend, FailKeyring), "backend": type(backend).__name__}
    except Exception as exc:  # noqa: BLE001
        checks["secret_store"] = {"ok": False, "error": type(exc).__name__}
    workers_expected = get_settings().enable_workers
    tasks = getattr(request.app.state, "worker_tasks", [])
    running = bool(tasks) and all(not t.done() for t in tasks)
    checks["workers"] = {"ok": running or not workers_expected, "enabled": workers_expected}
    ready = all(c["ok"] for c in checks.values())
    return JSONResponse({"status": "ready" if ready else "not_ready", "checks": checks}, status_code=200 if ready else 503)
