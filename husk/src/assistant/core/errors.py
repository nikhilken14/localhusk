"""Uniform JSON errors: ``{"detail": ..., "code": ..., "request_id": ...}``.

``detail`` is kept for compatibility with FastAPI's default shape so existing clients keep working.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("assistant.api")

_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
    409: "conflict", 413: "payload_too_large", 422: "validation_error", 429: "rate_limited",
    501: "not_implemented", 502: "upstream_error", 503: "unavailable",
}


class APIError(Exception):
    def __init__(self, status_code: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code or _CODES.get(status_code, "error")


def _body(request: Request, detail, code: str) -> dict:
    return {"detail": detail, "code": code, "request_id": getattr(request.state, "request_id", None)}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError):
        return JSONResponse(_body(request, exc.message, exc.code), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            _body(request, exc.detail, _CODES.get(exc.status_code, "error")),
            status_code=exc.status_code, headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(_body(request, errors, "validation_error"), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path, extra={"category": "api"})
        return JSONResponse(_body(request, "Internal server error", "internal_error"), status_code=500)
