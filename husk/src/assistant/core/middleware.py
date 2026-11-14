"""Pure-ASGI middleware (safe with streaming/SSE, unlike BaseHTTPMiddleware).

* assigns/propagates ``X-Request-ID``
* rejects requests whose Host header isn't a local name (DNS-rebinding defence)
* rejects state-changing requests from browser origins that aren't in CORS_ORIGINS, so a random
  website can't make your browser POST to the local API
* logs requests (errors and writes at INFO, successful reads at DEBUG)
"""
from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.responses import JSONResponse

log = logging.getLogger("assistant.api")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(host: str) -> str:
    host = host.strip().lower()
    return host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]


class RequestMiddleware:
    def __init__(self, app, *, allowed_hosts: list[str], allowed_origins: list[str]):
        self.app = app
        self.allowed_hosts = set(allowed_hosts)
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        request_id = (headers.get("x-request-id") or uuid4().hex)[:64]
        scope.setdefault("state", {})["request_id"] = request_id
        method, path = scope["method"], scope["path"]

        denial = None
        if self.allowed_hosts and "*" not in self.allowed_hosts and _hostname(headers.get("host", "")) not in self.allowed_hosts:
            denial = "Host not allowed (set ALLOWED_HOSTS to add it)"
        elif method not in SAFE_METHODS and headers.get("origin") and headers["origin"] not in self.allowed_origins:
            denial = "Origin not allowed (set CORS_ORIGINS to add it)"
        if denial:
            log.warning("Blocked %s %s: %s", method, path, denial)
            response = JSONResponse({"detail": denial, "code": "forbidden", "request_id": request_id}, status_code=403,
                                    headers={"X-Request-ID": request_id})
            return await response(scope, receive, send)

        started = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            level = logging.INFO if (method not in SAFE_METHODS or status >= 400) else logging.DEBUG
            log.log(level, "%s %s -> %s (%d ms)", method, path, status, elapsed, extra={"category": "api"})
