from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from openbridge.api import router
from openbridge.clients import OpenRouterClient
from openbridge.config import load_settings
from openbridge.logging import get_logger, setup_logging
from openbridge.metrics import RequestTimer
from openbridge.models.errors import ErrorDetail, ErrorResponse
from openbridge.state import MemoryStateStore, RedisStateStore
from openbridge.tools import ToolRegistry
from openbridge.utils import new_id


def _error_type_for_status(status_code: int) -> str:
    if status_code in (401, 403):
        return "authentication_error"
    if status_code == 404:
        return "invalid_request_error"
    if status_code == 429:
        return "rate_limit_error"
    if status_code >= 500:
        return "server_error"
    return "invalid_request_error"


def _openai_error_json(status_code: int, message: str) -> dict:
    error = ErrorResponse(
        error=ErrorDetail(
            message=message,
            type=_error_type_for_status(status_code),
            param=None,
            code=None,
        )
    )
    return error.model_dump()


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

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        message = str(exc.detail) if exc.detail is not None else "HTTP error"
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error_json(exc.status_code, message),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError):
        message = f"Invalid request: {exc.errors()}"
        return JSONResponse(
            status_code=422,
            content=_openai_error_json(422, message),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):  # noqa: BLE001
        logger = get_logger()
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content=_openai_error_json(500, "Internal server error"),
        )

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
