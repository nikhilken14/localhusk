from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from assistant.api.router import api_router
from assistant.core.config import APP_VERSION, get_settings
from assistant.core.errors import register_exception_handlers
from assistant.core.logging import configure_logging, shutdown_logging
from assistant.core.middleware import RequestMiddleware

log = logging.getLogger("assistant.system")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    from assistant.services.bootstrap import bootstrap

    await asyncio.to_thread(bootstrap)
    stop_event = asyncio.Event()
    app.state.worker_tasks = []
    if settings.enable_workers:
        from assistant.services.agent_runtime.worker import agent_worker_loop
        from assistant.services.automation import scheduler_loop

        app.state.worker_tasks = [asyncio.create_task(scheduler_loop(stop_event)), asyncio.create_task(agent_worker_loop(stop_event))]
    log.info("%s %s started (workers=%s)", settings.app_name, APP_VERSION, settings.enable_workers)
    try:
        yield
    finally:
        stop_event.set()
        if app.state.worker_tasks:
            await asyncio.wait(app.state.worker_tasks, timeout=10)
            for task in app.state.worker_tasks:
                task.cancel()
        shutdown_logging()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(RequestMiddleware, allowed_hosts=settings.allowed_host_list, allowed_origins=settings.cors_origin_list)
    app.add_middleware(  # added last = outermost, so preflights and error responses carry CORS headers
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"],
        allow_headers=["*"], expose_headers=["X-Request-ID"])
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
