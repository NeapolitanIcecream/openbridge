from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from openbridge.api import router
from openbridge.clients import OpenRouterClient
from openbridge.config import load_settings
from openbridge.logging import get_logger, setup_logging
from openbridge.metrics import RequestTimer
from openbridge.state import MemoryStateStore, RedisStateStore
from openbridge.tools import ToolRegistry
from openbridge.utils import new_id


def create_app() -> FastAPI:
    settings = load_settings()
    setup_logging(settings.openbridge_log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.tool_registry = ToolRegistry.default_registry()
        app.state.openrouter_client = OpenRouterClient(settings)
        if settings.openbridge_state_backend == "redis":
            app.state.state_store = RedisStateStore(settings.openbridge_redis_url)
        elif settings.openbridge_state_backend == "memory":
            app.state.state_store = MemoryStateStore()
        else:
            app.state.state_store = None
        yield
        await app.state.openrouter_client.close()
        if hasattr(app.state.state_store, "close"):
            await app.state.state_store.close()

    app = FastAPI(title="OpenBridge", lifespan=lifespan)

    @app.middleware("http")
    async def request_context_middleware(request, call_next):
        request_id = request.headers.get("x-request-id") or new_id("req")
        request.state.request_id = request_id
        timer = RequestTimer(request.url.path, request.method)
        logger = get_logger()
        with logger.contextualize(request_id=request_id):
            response = await call_next(request)
        response.headers["x-request-id"] = request_id
        timer.observe(response.status_code)
        return response

    app.include_router(router)
    return app


app = create_app()
