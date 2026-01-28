from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette import EventSourceResponse

from openbridge import __version__
from openbridge.logging import get_logger
from openbridge.metrics import metrics_response
from openbridge.models.chat import ChatCompletionResponse
from openbridge.models.errors import ErrorDetail, ErrorResponse
from openbridge.models.responses import ResponsesCreateRequest
from openbridge.state import StoredResponse
from openbridge.services import (
    apply_degrade_fields,
    call_with_retry,
    extract_error_message,
)
from openbridge.translate import chat_response_to_responses, translate_request
from openbridge.utils import new_id, now_ts


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/metrics")
async def metrics():
    return metrics_response()


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chat_request = translation.chat_request
    tool_map = translation.tool_map

    response_id = new_id("resp")
    created_at = now_ts()

    if payload.stream:
        from openbridge.streaming.bridge import stream_responses_events

        async def on_complete(final_response, assistant_message):
            if state_store is None or payload.store is False:
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

        event_stream = stream_responses_events(
            client=openrouter_client,
            chat_request=chat_request,
            tool_map=tool_map,
            response_id=response_id,
            created_at=created_at,
            settings=settings,
            on_complete=on_complete,
        )
        return EventSourceResponse(event_stream)

    async def _call_upstream(payload_dict: dict) -> object:
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

    upstream_payload = chat_request.model_dump(exclude_none=True)
    upstream_response = await _call_upstream(upstream_payload)
    if upstream_response.status_code >= 400:
        return _upstream_error_response(upstream_response)

    upstream_request_id = upstream_response.headers.get("x-request-id")
    if upstream_request_id:
        logger.bind(upstream_request_id=upstream_request_id).info(
            "OpenRouter response received"
        )

    def _build_responses(resp) -> tuple[ChatCompletionResponse, object]:
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
    if (
        not responses.output
        and (payload.max_output_tokens is None or payload.max_output_tokens > 0)
    ):
        # Some upstreams occasionally return HTTP 200 with an empty choices/message.
        # Retry once to improve reliability for short "ACK/OK" responses.
        logger.warning("Upstream returned empty output; retrying once")
        upstream_response2 = await _call_upstream(upstream_payload)
        if upstream_response2.status_code >= 400:
            return _upstream_error_response(upstream_response2)
        upstream_request_id2 = upstream_response2.headers.get("x-request-id")
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

    if state_store is not None and payload.store is not False:
        assistant_message = (
            chat_response.choices[0].message if chat_response.choices else None
        )
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
