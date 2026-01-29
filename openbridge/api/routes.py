from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette import EventSourceResponse

from openbridge import __version__
from openbridge.logging import get_logger
from openbridge.metrics import metrics_response
from openbridge.models.chat import ChatCompletionResponse
from openbridge.models.errors import ErrorDetail, ErrorResponse
from openbridge.models.responses import ResponsesCreateRequest, ResponsesCreateResponse
from openbridge.state import StoredResponse
from openbridge.trace import TraceRecord, TraceSanitizeConfig, sanitize_trace_value
from openbridge.services import (
    apply_degrade_fields,
    call_with_retry,
    extract_error_message,
)
from openbridge.translate import chat_response_to_responses, translate_request
from openbridge.utils import json_dumps, new_id, now_ts


router = APIRouter()


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _trace_enabled(request: Request) -> bool:
    settings = request.app.state.settings
    if getattr(settings, "openbridge_trace_enabled", False):
        return True
    if _is_truthy(request.headers.get("x-openbridge-trace")):
        return True
    if _is_truthy(request.query_params.get("openbridge_trace")):
        return True
    return False


def _debug_endpoints_enabled(request: Request) -> bool:
    settings = request.app.state.settings
    return bool(getattr(settings, "openbridge_debug_endpoints", False))


def _log_trace_if_enabled(
    settings: Any, logger: Any, trace_record: TraceRecord
) -> None:
    if not getattr(settings, "openbridge_trace_log", False):
        return
    try:
        payload = trace_record.model_dump(exclude_none=True)
    except Exception:  # noqa: BLE001
        payload = {"request_id": trace_record.request_id, "error": "trace_dump_failed"}
    logger.info("TRACE {}", json_dumps(payload))


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/metrics")
async def metrics():
    return metrics_response()


@router.get("/v1/debug/requests/{request_id}")
async def debug_request(request: Request, request_id: str):
    settings = request.app.state.settings
    _require_client_auth(request, settings.openbridge_client_api_key)
    if not _debug_endpoints_enabled(request):
        raise HTTPException(status_code=404, detail="Not found")

    trace_store = getattr(request.app.state, "trace_store", None)
    state_store = request.app.state.state_store

    trace = await trace_store.get_by_request_id(request_id) if trace_store else None
    stored = None
    if trace and trace.response_id and state_store is not None:
        stored = await state_store.get(trace.response_id)

    if trace is None and stored is None:
        raise HTTPException(status_code=404, detail="debug trace not found")

    return JSONResponse(
        content={
            "request_id": request_id,
            "response_id": trace.response_id if trace else None,
            "trace": trace.model_dump(exclude_none=True) if trace else None,
            "state": stored.model_dump(exclude_none=True) if stored else None,
        }
    )


@router.get("/v1/debug/responses/{response_id}")
async def debug_response(request: Request, response_id: str):
    settings = request.app.state.settings
    _require_client_auth(request, settings.openbridge_client_api_key)
    if not _debug_endpoints_enabled(request):
        raise HTTPException(status_code=404, detail="Not found")

    trace_store = getattr(request.app.state, "trace_store", None)
    state_store = request.app.state.state_store

    trace = await trace_store.get_by_response_id(response_id) if trace_store else None
    stored = await state_store.get(response_id) if state_store is not None else None

    if trace is None and stored is None:
        raise HTTPException(status_code=404, detail="debug trace not found")

    return JSONResponse(
        content={
            "response_id": response_id,
            "request_id": trace.request_id if trace else None,
            "trace": trace.model_dump(exclude_none=True) if trace else None,
            "state": stored.model_dump(exclude_none=True) if stored else None,
        }
    )


@router.get("/v1/responses/{response_id}")
async def get_response(request: Request, response_id: str):
    settings = request.app.state.settings
    _require_client_auth(request, settings.openbridge_client_api_key)
    state_store = request.app.state.state_store
    if state_store is None:
        raise HTTPException(status_code=501, detail="State store is disabled")
    stored = await state_store.get(response_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="response_id not found")
    return JSONResponse(content=stored.response.model_dump())


@router.delete("/v1/responses/{response_id}")
async def delete_response(request: Request, response_id: str):
    settings = request.app.state.settings
    _require_client_auth(request, settings.openbridge_client_api_key)
    state_store = request.app.state.state_store
    if state_store is None:
        raise HTTPException(status_code=501, detail="State store is disabled")
    await state_store.delete(response_id)
    return {"id": response_id, "deleted": True}


@router.post("/v1/responses")
async def create_response(request: Request, payload: ResponsesCreateRequest):
    settings = request.app.state.settings
    _require_client_auth(request, settings.openbridge_client_api_key)

    logger = get_logger()
    openrouter_client = request.app.state.openrouter_client
    tool_registry = request.app.state.tool_registry
    state_store = request.app.state.state_store
    trace_store = getattr(request.app.state, "trace_store", None)
    request_id = getattr(request.state, "request_id", None) or new_id("req")

    trace_cfg = TraceSanitizeConfig(
        content_mode=settings.openbridge_trace_content,
        max_chars=settings.openbridge_trace_max_chars,
        redact_secrets=True,
    )
    trace_record: TraceRecord | None = None

    history_messages = []
    stored: StoredResponse | None = None
    if payload.previous_response_id:
        if state_store is None:
            raise HTTPException(status_code=501, detail="State store is disabled")
        stored = await state_store.get(payload.previous_response_id)
        if stored is None:
            raise HTTPException(
                status_code=404, detail="previous_response_id not found"
            )
        history_messages = stored.messages

    try:
        translation = translate_request(
            settings, payload, tool_registry, history_messages=history_messages
        )
    except ValueError as exc:
        if trace_store is not None and _trace_enabled(request):
            ts = now_ts()
            trace_record = TraceRecord(
                request_id=request_id,
                created_at=ts,
                updated_at=ts,
                method=request.method,
                path=str(request.url.path),
                stream=bool(payload.stream),
                responses_request=sanitize_trace_value(
                    payload.model_dump(exclude_none=True), cfg=trace_cfg
                ),
                error={"type": "translation_error", "message": str(exc)},
            )
            await trace_store.set(trace_record, settings.openbridge_trace_ttl_seconds)
            logger.warning("Debug trace captured for translation error")
            _log_trace_if_enabled(settings, logger, trace_record)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chat_request = translation.chat_request
    tool_map = translation.tool_map

    response_id = new_id("resp")
    created_at = now_ts()

    if trace_store is not None and _trace_enabled(request):
        trace_record = TraceRecord(
            request_id=request_id,
            response_id=response_id,
            created_at=created_at,
            updated_at=created_at,
            method=request.method,
            path=str(request.url.path),
            stream=bool(payload.stream),
            responses_request=sanitize_trace_value(
                payload.model_dump(exclude_none=True), cfg=trace_cfg
            ),
            chat_request=sanitize_trace_value(
                chat_request.model_dump(exclude_none=True), cfg=trace_cfg
            ),
            messages_for_state=sanitize_trace_value(
                [
                    m.model_dump(exclude_none=True)
                    for m in translation.messages_for_state
                ],
                cfg=trace_cfg,
            ),
            tool_map={
                "function_name_map": dict(tool_map.function_name_map),
                "external_name_map": dict(tool_map.external_name_map),
            },
        )
        await trace_store.set(trace_record, settings.openbridge_trace_ttl_seconds)
        logger.bind(response_id=response_id).info("Debug trace captured")
        _log_trace_if_enabled(settings, logger, trace_record)

    if payload.stream:
        from openbridge.streaming.bridge import stream_responses_events

        async def on_upstream_request_id(upstream_id: str | None) -> None:
            if upstream_id:
                logger.bind(upstream_request_id=upstream_id).info(
                    "OpenRouter SSE connected"
                )
            if trace_store is None or trace_record is None:
                return
            trace_record.updated_at = now_ts()
            trace_record.upstream = trace_record.upstream or {}
            if upstream_id:
                trace_record.upstream["upstream_request_id"] = upstream_id
            await trace_store.set(trace_record, settings.openbridge_trace_ttl_seconds)

        async def on_complete(final_response, assistant_message):
            if state_store is None or payload.store is False:
                # Still persist the trace payload when enabled.
                if trace_store is not None and trace_record is not None:
                    trace_record.updated_at = now_ts()
                    trace_record.responses_response = sanitize_trace_value(
                        final_response.model_dump(exclude_none=True), cfg=trace_cfg
                    )
                    if assistant_message is not None:
                        trace_record.assistant_message = sanitize_trace_value(
                            assistant_message.model_dump(exclude_none=True),
                            cfg=trace_cfg,
                        )
                    await trace_store.set(
                        trace_record, settings.openbridge_trace_ttl_seconds
                    )
                    _log_trace_if_enabled(settings, logger, trace_record)
                return
            messages = translation.messages_for_state
            if assistant_message is not None:
                messages = messages + [assistant_message]
            record = StoredResponse(
                response=final_response,
                messages=messages,
                tool_function_map=tool_map.function_name_map,
                model=chat_request.model,
            )
            await state_store.set(
                response_id, record, settings.openbridge_memory_ttl_seconds
            )
            if trace_store is not None and trace_record is not None:
                trace_record.updated_at = now_ts()
                trace_record.responses_response = sanitize_trace_value(
                    final_response.model_dump(exclude_none=True), cfg=trace_cfg
                )
                if assistant_message is not None:
                    trace_record.assistant_message = sanitize_trace_value(
                        assistant_message.model_dump(exclude_none=True), cfg=trace_cfg
                    )
                await trace_store.set(
                    trace_record, settings.openbridge_trace_ttl_seconds
                )
                _log_trace_if_enabled(settings, logger, trace_record)

        raw_stream = stream_responses_events(
            client=openrouter_client,
            chat_request=chat_request,
            tool_map=tool_map,
            response_id=response_id,
            created_at=created_at,
            settings=settings,
            on_upstream_request_id=on_upstream_request_id,
            on_complete=on_complete,
        )

        async def event_stream():
            # The request middleware's logger context does not cover streaming iteration.
            # Re-apply request_id here so logs and traces stay correlated.
            with logger.contextualize(request_id=request_id):
                async for event in raw_stream:
                    yield event

        return EventSourceResponse(event_stream())

    async def _call_upstream(payload_dict: dict[str, Any]) -> httpx.Response:
        upstream_response = await call_with_retry(
            client=openrouter_client,
            payload=payload_dict,
            settings=settings,
        )
        if upstream_response.status_code >= 400:
            error_message = extract_error_message(upstream_response)
            degraded_payload = apply_degrade_fields(
                payload_dict, settings.openbridge_degrade_fields, error_message
            )
            if degraded_payload:
                upstream_response = await call_with_retry(
                    client=openrouter_client,
                    payload=degraded_payload,
                    settings=settings,
                )
        return upstream_response

    upstream_payload: dict[str, Any] = chat_request.model_dump(exclude_none=True)
    upstream_response = await _call_upstream(upstream_payload)
    upstream_request_id = upstream_response.headers.get("x-request-id")
    if trace_store is not None and trace_record is not None:
        trace_record.updated_at = now_ts()
        trace_record.upstream = trace_record.upstream or {}
        trace_record.upstream["status_code"] = upstream_response.status_code
        if upstream_request_id:
            trace_record.upstream["upstream_request_id"] = upstream_request_id
        if upstream_response.status_code >= 400:
            trace_record.error = {
                "type": "upstream_error",
                "message": extract_error_message(upstream_response),
            }
        await trace_store.set(trace_record, settings.openbridge_trace_ttl_seconds)
        if upstream_response.status_code >= 400:
            _log_trace_if_enabled(settings, logger, trace_record)

    if upstream_response.status_code >= 400:
        return _upstream_error_response(upstream_response)

    if upstream_request_id:
        logger.bind(upstream_request_id=upstream_request_id).info(
            "OpenRouter response received"
        )

    def _build_responses(
        resp: httpx.Response,
    ) -> tuple[ChatCompletionResponse, ResponsesCreateResponse]:
        chat_response = ChatCompletionResponse.model_validate(resp.json())
        responses = chat_response_to_responses(
            chat_response,
            model=chat_request.model,
            tool_map=tool_map,
            response_id=response_id,
            created_at=created_at,
        )
        return chat_response, responses

    chat_response, responses = _build_responses(upstream_response)
    if not responses.output and (
        payload.max_output_tokens is None or payload.max_output_tokens > 0
    ):
        # Some upstreams occasionally return HTTP 200 with an empty choices/message.
        # Retry once to improve reliability for short "ACK/OK" responses.
        logger.warning("Upstream returned empty output; retrying once")
        if trace_record is not None:
            trace_record.notes.append("empty_output_retry_once")
        upstream_response2 = await _call_upstream(upstream_payload)
        upstream_request_id2 = upstream_response2.headers.get("x-request-id")
        if trace_store is not None and trace_record is not None:
            trace_record.updated_at = now_ts()
            trace_record.upstream = trace_record.upstream or {}
            trace_record.upstream["status_code"] = upstream_response2.status_code
            if upstream_request_id2:
                trace_record.upstream["upstream_request_id"] = upstream_request_id2
            if upstream_response2.status_code >= 400:
                trace_record.error = {
                    "type": "upstream_error",
                    "message": extract_error_message(upstream_response2),
                }
            await trace_store.set(trace_record, settings.openbridge_trace_ttl_seconds)

        if upstream_response2.status_code >= 400:
            return _upstream_error_response(upstream_response2)
        if upstream_request_id2:
            logger.bind(upstream_request_id=upstream_request_id2).info(
                "OpenRouter response received (retry)"
            )
        chat_response2, responses2 = _build_responses(upstream_response2)
        if responses2.output:
            upstream_response = upstream_response2
            chat_response = chat_response2
            responses = responses2
        else:
            raise HTTPException(
                status_code=502, detail="Upstream returned empty completion"
            )

    assistant_message = (
        chat_response.choices[0].message if chat_response.choices else None
    )
    if trace_store is not None and trace_record is not None:
        trace_record.updated_at = now_ts()
        trace_record.responses_response = sanitize_trace_value(
            responses.model_dump(exclude_none=True), cfg=trace_cfg
        )
        if assistant_message is not None:
            trace_record.assistant_message = sanitize_trace_value(
                assistant_message.model_dump(exclude_none=True), cfg=trace_cfg
            )
        await trace_store.set(trace_record, settings.openbridge_trace_ttl_seconds)
        _log_trace_if_enabled(settings, logger, trace_record)

    if state_store is not None and payload.store is not False:
        messages = translation.messages_for_state
        if assistant_message is not None:
            messages = messages + [assistant_message]
        record = StoredResponse(
            response=responses,
            messages=messages,
            tool_function_map=tool_map.function_name_map,
            model=chat_request.model,
        )
        await state_store.set(
            response_id, record, settings.openbridge_memory_ttl_seconds
        )

    return JSONResponse(content=responses.model_dump())


def _require_client_auth(request: Request, api_key: str | None) -> None:
    if not api_key:
        return
    header = request.headers.get("authorization") or request.headers.get("x-api-key")
    if not header:
        raise HTTPException(status_code=401, detail="Missing client API key")
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
    else:
        token = header.strip()
    if token != api_key:
        raise HTTPException(status_code=401, detail="Invalid client API key")


def _upstream_error_response(response) -> JSONResponse:
    try:
        data = response.json()
    except ValueError:
        data = {}
    error_data = data.get("error", {}) if isinstance(data, dict) else {}
    message = error_data.get("message") or response.text
    error_type = error_data.get("type") or "invalid_request_error"
    error = ErrorResponse(
        error=ErrorDetail(
            message=message,
            type=error_type,
            param=error_data.get("param"),
            code=error_data.get("code"),
        )
    )
    return JSONResponse(status_code=response.status_code, content=error.model_dump())
