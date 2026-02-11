from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    Protocol,
)

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from openbridge.config import Settings
from openbridge.models.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatToolCall,
    ChatToolCallFunction,
)
from openbridge.models.events import (
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseInProgressEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)
from openbridge.models.responses import (
    ResponseOutputItem,
    ResponseOutputText,
    ResponsesCreateRequest,
    ResponseStatus,
    ResponseTextConfig,
    ResponseTextFormat,
    ResponsesCreateResponse,
)
from openbridge.services import apply_degrade_fields, extract_error_message
from openbridge.tools.registry import ToolVirtualizationResult
from openbridge.usage import normalize_responses_usage
from openbridge.utils import json_dumps, new_id, now_ts


class ChatCompletionsSSEClient(Protocol):
    def connect_chat_completions_sse(
        self, payload: dict[str, Any]
    ) -> AsyncContextManager[Any]: ...


@dataclass
class ToolCallState:
    index: int
    call_id: str | None = None
    name: str | None = None
    arguments: str = ""
    output_index: int | None = None
    external_type: str | None = None
    pending_argument_deltas: list[str] = field(default_factory=list)


class ResponsesStreamTranslator:
    def __init__(
        self,
        *,
        response_id: str,
        model: str,
        created_at: int,
        tool_map: ToolVirtualizationResult,
        responses_request: ResponsesCreateRequest | None = None,
        store: bool | None = None,
    ) -> None:
        self._response_id = response_id
        self._model = model
        self._created_at = created_at
        self._tool_map = tool_map
        self._output_items: list[ResponseOutputItem] = []
        self._text_output_index: int | None = None
        self._text_content: str = ""
        self._tool_calls: dict[int, ToolCallState] = {}
        self._reasoning_output_index: int | None = None
        self._reasoning_detail_order: list[str] = []
        self._reasoning_detail_map: dict[str, dict[str, Any]] = {}
        self._assistant_reasoning: str | None = None
        self._usage: dict[str, Any] | None = None
        self._sequence_number: int = 0
        self._final_status: ResponseStatus | None = None
        self._final_completed_at: int | None = None
        self._final_error: dict[str, Any] | None = None

        # Copy selected request fields into the Response object for strict clients.
        self._instructions = (
            responses_request.instructions if responses_request is not None else None
        )
        self._max_output_tokens = (
            responses_request.max_output_tokens
            if responses_request is not None
            else None
        )
        self._parallel_tool_calls = (
            responses_request.parallel_tool_calls
            if responses_request is not None
            else None
        )
        if self._parallel_tool_calls is None and responses_request is not None:
            self._parallel_tool_calls = True
        self._previous_response_id = (
            responses_request.previous_response_id
            if responses_request is not None
            else None
        )
        self._temperature = (
            responses_request.temperature if responses_request is not None else None
        )
        if self._temperature is None and responses_request is not None:
            self._temperature = 1.0
        self._top_p = responses_request.top_p if responses_request is not None else None
        if self._top_p is None and responses_request is not None:
            self._top_p = 1.0
        self._tool_choice = (
            responses_request.tool_choice if responses_request is not None else None
        )
        if self._tool_choice is None and responses_request is not None:
            self._tool_choice = "auto"
        self._tools = responses_request.tools if responses_request is not None else None
        if self._tools is None and responses_request is not None:
            self._tools = []
        self._metadata = (
            responses_request.metadata if responses_request is not None else None
        )
        if self._metadata is None and responses_request is not None:
            self._metadata = {}
        self._reasoning_cfg = (
            getattr(responses_request, "reasoning", None)
            if responses_request is not None
            else None
        )
        text = responses_request.text if responses_request is not None else None
        if text is None:
            text = ResponseTextConfig(
                format=ResponseTextFormat(type="text", schema=None)
            )
        self._text_cfg = text

        if store is not None:
            self._store = bool(store)
        elif responses_request is not None:
            self._store = (
                True
                if responses_request.store is None
                else bool(responses_request.store)
            )
        else:
            self._store = None

    def set_usage(self, usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        self._usage = usage

    def _next_seq(self) -> int:
        self._sequence_number += 1
        return self._sequence_number

    def start_events(self) -> list[dict[str, Any]]:
        response = self._build_response(
            status="in_progress", completed_at=None, error=None
        )
        return [
            _event(
                "response.created",
                ResponseCreatedEvent(
                    response=response, sequence_number=self._next_seq()
                ).model_dump(),
            ),
            _event(
                "response.in_progress",
                ResponseInProgressEvent(
                    response=response, sequence_number=self._next_seq()
                ).model_dump(),
            ),
        ]

    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        choices = chunk.get("choices", [])
        if not isinstance(choices, list):
            return events
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                continue
            if "content" in delta and delta["content"] is not None:
                events.extend(self._handle_text_delta(delta["content"]))
            if "tool_calls" in delta and delta["tool_calls"]:
                events.extend(self._handle_tool_call_deltas(delta["tool_calls"]))
            if "reasoning_details" in delta and delta["reasoning_details"]:
                events.extend(
                    self._handle_reasoning_details(delta["reasoning_details"])
                )
            if "reasoning" in delta and delta["reasoning"] is not None:
                # Some providers may emit a free-form reasoning string. Preserve it for round-trip.
                value = delta["reasoning"]
                if isinstance(value, str) and value:
                    self._assistant_reasoning = (
                        (self._assistant_reasoning or "") + value
                    ) or None
        return events

    def finish_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self._reasoning_output_index is not None:
            item = self._output_items[self._reasoning_output_index]
            details = self._final_reasoning_details()
            if details:
                setattr(item, "openrouter_reasoning_details", details)
                summary_parts = self._reasoning_details_to_summary(details)
                if summary_parts:
                    setattr(item, "summary", summary_parts)
            if self._assistant_reasoning:
                setattr(item, "openrouter_reasoning", self._assistant_reasoning)
            item.status = "completed"
            events.append(
                _event(
                    "response.output_item.done",
                    ResponseOutputItemDoneEvent(
                        output_index=self._reasoning_output_index,
                        item=item,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )

        if self._text_output_index is not None:
            item = self._output_items[self._text_output_index]
            item_id = item.id
            events.append(
                _event(
                    "response.output_text.done",
                    ResponseOutputTextDoneEvent(
                        item_id=item_id,
                        output_index=self._text_output_index,
                        content_index=0,
                        text=self._text_content,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )
            events.append(
                _event(
                    "response.content_part.done",
                    ResponseContentPartDoneEvent(
                        item_id=item_id,
                        output_index=self._text_output_index,
                        content_index=0,
                        part=(
                            item.content[0].model_dump()
                            if item.content
                            else ResponseOutputText(
                                text=self._text_content
                            ).model_dump()
                        ),
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )
            item.status = "completed"
            events.append(
                _event(
                    "response.output_item.done",
                    ResponseOutputItemDoneEvent(
                        output_index=self._text_output_index,
                        item=item,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )

        tool_states = [
            (state.output_index, state)
            for state in self._tool_calls.values()
            if state.output_index is not None
        ]
        for output_index, state in sorted(tool_states, key=lambda entry: entry[0]):
            item = self._output_items[int(output_index)]
            item_id = item.id
            events.append(
                _event(
                    "response.function_call_arguments.done",
                    ResponseFunctionCallArgumentsDoneEvent(
                        item_id=item_id,
                        output_index=int(output_index),
                        arguments=state.arguments,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )
            item.status = "completed"
            events.append(
                _event(
                    "response.output_item.done",
                    ResponseOutputItemDoneEvent(
                        output_index=int(output_index),
                        item=item,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )

        completed_at = now_ts()
        self._final_status = "completed"
        self._final_completed_at = completed_at
        self._final_error = None
        response = self._build_response(
            status="completed", completed_at=completed_at, error=None
        )
        events.append(
            _event(
                "response.completed",
                ResponseCompletedEvent(
                    response=response, sequence_number=self._next_seq()
                ).model_dump(),
            )
        )
        return events

    def failure_event(self, error: dict[str, Any]) -> dict[str, Any]:
        code = error.get("code") or error.get("type") or "server_error"
        message = error.get("message") or str(error)
        err_obj = {"code": str(code), "message": str(message)}

        self._final_status = "failed"
        self._final_completed_at = None
        self._final_error = err_obj

        response = self._build_response(
            status="failed", completed_at=None, error=err_obj
        )
        return _event(
            "response.failed",
            ResponseFailedEvent(
                response=response, sequence_number=self._next_seq()
            ).model_dump(),
        )

    def assistant_message(self) -> ChatMessage | None:
        tool_calls: list[ChatToolCall] = []
        tool_states = [
            (state.output_index, state)
            for state in self._tool_calls.values()
            if state.output_index is not None
        ]
        for _, state in sorted(tool_states, key=lambda entry: entry[0]):
            if not state.call_id or not state.name:
                continue
            tool_calls.append(
                ChatToolCall(
                    id=state.call_id,
                    type="function",
                    function=ChatToolCallFunction(
                        name=state.name, arguments=state.arguments
                    ),
                )
            )
        content = self._text_content or None
        reasoning_details = self._final_reasoning_details()
        reasoning = self._assistant_reasoning
        if not tool_calls and not content and not reasoning_details and not reasoning:
            return None
        msg = ChatMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls or None,
        )
        if reasoning_details:
            msg.reasoning_details = reasoning_details
        if reasoning:
            msg.reasoning = reasoning
        return msg

    def final_response(self) -> ResponsesCreateResponse:
        status = self._final_status or "in_progress"
        return self._build_response(
            status=status,
            completed_at=self._final_completed_at,
            error=self._final_error,
        )

    def _handle_text_delta(self, delta: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if delta == "":
            # Avoid creating empty text output items from upstreams that emit
            # empty string deltas alongside tool calls.
            return events
        if self._text_output_index is None:
            item = ResponseOutputItem(
                id=new_id("msg"),
                type="message",
                status="in_progress",
                role="assistant",
                content=[ResponseOutputText(text="")],
            )
            self._text_output_index = len(self._output_items)
            self._output_items.append(item)
            events.append(
                _event(
                    "response.output_item.added",
                    ResponseOutputItemAddedEvent(
                        output_index=self._text_output_index,
                        item=item,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )
            events.append(
                _event(
                    "response.content_part.added",
                    ResponseContentPartAddedEvent(
                        item_id=item.id,
                        output_index=self._text_output_index,
                        content_index=0,
                        part=(
                            item.content[0].model_dump()
                            if item.content
                            else ResponseOutputText(text="").model_dump()
                        ),
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )

        self._text_content += delta
        item = self._output_items[self._text_output_index]
        if item.content:
            item.content[0].text = self._text_content
        events.append(
            _event(
                "response.output_text.delta",
                ResponseOutputTextDeltaEvent(
                    item_id=item.id,
                    output_index=self._text_output_index,
                    content_index=0,
                    delta=delta,
                    sequence_number=self._next_seq(),
                ).model_dump(),
            )
        )
        return events

    def _handle_tool_call_deltas(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            index = tool_call.get("index", 0)
            state = self._tool_calls.get(index)
            if state is None:
                state = ToolCallState(index=index)
                self._tool_calls[index] = state

            call_id = tool_call.get("id")
            if call_id:
                state.call_id = call_id

            function = tool_call.get("function", {}) or {}
            name = function.get("name")
            if name:
                state.name = name
                if state.external_type is None:
                    state.external_type = self._tool_map.function_name_map.get(name)

            arguments_delta = function.get("arguments")
            if arguments_delta is not None:
                state.arguments += arguments_delta
                if state.output_index is None:
                    state.pending_argument_deltas.append(arguments_delta)
                else:
                    item = self._output_items[int(state.output_index)]
                    item.arguments = state.arguments
                    events.append(
                        _event(
                            "response.function_call_arguments.delta",
                            ResponseFunctionCallArgumentsDeltaEvent(
                                item_id=item.id,
                                output_index=int(state.output_index),
                                delta=arguments_delta,
                                sequence_number=self._next_seq(),
                            ).model_dump(),
                        )
                    )

            events.extend(self._maybe_emit_tool_call_item_added(state))
        return events

    def _handle_reasoning_details(self, details: Any) -> list[dict[str, Any]]:
        if not isinstance(details, list):
            return []

        events: list[dict[str, Any]] = []
        if self._reasoning_output_index is None:
            item = ResponseOutputItem(
                id=new_id("item"), type="reasoning", status="in_progress"
            )
            self._reasoning_output_index = len(self._output_items)
            self._output_items.append(item)
            events.append(
                _event(
                    "response.output_item.added",
                    ResponseOutputItemAddedEvent(
                        output_index=self._reasoning_output_index,
                        item=item,
                        sequence_number=self._next_seq(),
                    ).model_dump(),
                )
            )

        for detail in details:
            if not isinstance(detail, dict):
                continue
            raw_id = detail.get("id")
            if isinstance(raw_id, str) and raw_id:
                key = raw_id
            else:
                key = f"{detail.get('type')}:{detail.get('index')}"
            if key not in self._reasoning_detail_map:
                self._reasoning_detail_order.append(key)
                self._reasoning_detail_map[key] = dict(detail)
                continue
            existing = self._reasoning_detail_map[key]
            for k, v in detail.items():
                if v is None:
                    continue
                existing[k] = v

        return events

    def _final_reasoning_details(self) -> list[dict[str, Any]]:
        if not self._reasoning_detail_order:
            return []
        return [
            self._reasoning_detail_map[key]
            for key in self._reasoning_detail_order
            if key in self._reasoning_detail_map
        ]

    def _reasoning_details_to_summary(
        self, details: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        summary_parts: list[dict[str, str]] = []
        for detail in details:
            if (
                detail.get("type") == "reasoning.summary"
                and isinstance(detail.get("summary"), str)
                and detail.get("summary")
            ):
                summary_parts.append(
                    {"type": "summary_text", "text": str(detail["summary"])}
                )
        return summary_parts

    def _maybe_emit_tool_call_item_added(
        self, state: ToolCallState
    ) -> list[dict[str, Any]]:
        if state.output_index is not None:
            return []
        if not state.call_id or not state.name:
            return []

        external_type = state.external_type
        item_type = f"{external_type}_call" if external_type else "function_call"
        item_name = external_type or state.name
        item = ResponseOutputItem(
            id=new_id("item"),
            type=item_type,
            status="in_progress",
            call_id=state.call_id,
            name=item_name,
            arguments="",
        )
        output_index = len(self._output_items)
        self._output_items.append(item)
        state.output_index = output_index

        events: list[dict[str, Any]] = [
            _event(
                "response.output_item.added",
                ResponseOutputItemAddedEvent(
                    output_index=output_index,
                    item=item,
                    sequence_number=self._next_seq(),
                ).model_dump(),
            )
        ]

        if state.pending_argument_deltas:
            for delta in state.pending_argument_deltas:
                item.arguments = state.arguments if delta else item.arguments
                events.append(
                    _event(
                        "response.function_call_arguments.delta",
                        ResponseFunctionCallArgumentsDeltaEvent(
                            item_id=item.id,
                            output_index=output_index,
                            delta=delta,
                            sequence_number=self._next_seq(),
                        ).model_dump(),
                    )
                )
            state.pending_argument_deltas.clear()

        return events

    def _build_response(
        self,
        *,
        status: ResponseStatus,
        completed_at: int | None,
        error: dict[str, Any] | None,
    ) -> ResponsesCreateResponse:
        return ResponsesCreateResponse(
            id=self._response_id,
            created_at=self._created_at,
            status=status,
            completed_at=completed_at,
            error=error,
            incomplete_details=None,
            instructions=self._instructions,
            max_output_tokens=self._max_output_tokens,
            model=self._model,
            output=list(self._output_items),
            parallel_tool_calls=self._parallel_tool_calls,
            previous_response_id=self._previous_response_id,
            reasoning=self._reasoning_cfg
            if isinstance(self._reasoning_cfg, dict)
            else None,
            store=self._store,
            temperature=self._temperature,
            top_p=self._top_p,
            tool_choice=self._tool_choice,
            tools=self._tools,
            text=self._text_cfg,
            truncation="disabled",
            usage=self._usage,
            metadata=self._metadata,
        )


async def stream_responses_events(
    *,
    client: ChatCompletionsSSEClient,
    chat_request: ChatCompletionRequest,
    tool_map: ToolVirtualizationResult,
    response_id: str,
    created_at: int,
    settings: Settings,
    responses_request: ResponsesCreateRequest | None = None,
    store: bool | None = None,
    on_upstream_request_id: Callable[[str | None], Awaitable[None]] | None = None,
    on_upstream_stats: Callable[[dict[str, Any] | None, str | None], Awaitable[None]]
    | None = None,
    on_complete: Callable[
        [ResponsesCreateResponse, ChatMessage | None], Awaitable[None]
    ]
    | None,
) -> AsyncIterator[dict[str, Any]]:
    payload: dict[str, Any] = chat_request.model_dump(exclude_none=True)
    translator = ResponsesStreamTranslator(
        response_id=response_id,
        model=chat_request.model,
        created_at=created_at,
        tool_map=tool_map,
        responses_request=responses_request,
        store=store,
    )
    started = False
    finish_reason: str | None = None
    last_usage: dict[str, Any] | None = None

    class StreamRetryableError(Exception):
        pass

    retryable_status = {429, 500, 502, 503, 504}

    retrying = AsyncRetrying(
        retry=retry_if_exception_type(StreamRetryableError),
        stop=stop_after_attempt(settings.openbridge_retry_max_attempts),
        wait=wait_exponential_jitter(
            initial=settings.openbridge_retry_backoff,
            max=settings.openbridge_retry_max_seconds,
        ),
        reraise=True,
    )

    try:
        async for attempt in retrying:
            with attempt:
                try:
                    async with client.connect_chat_completions_sse(
                        payload
                    ) as event_source:
                        response = event_source.response
                        if on_upstream_request_id is not None:
                            await on_upstream_request_id(
                                response.headers.get("x-request-id")
                            )
                        if response.status_code in retryable_status:
                            await response.aread()
                            raise StreamRetryableError(
                                f"Retryable upstream status: {response.status_code}"
                            )

                        if response.status_code >= 400:
                            await response.aread()
                            error_message = extract_error_message(response)
                            degraded_payload = apply_degrade_fields(
                                payload,
                                settings.openbridge_degrade_fields,
                                error_message,
                            )
                            if degraded_payload:
                                payload = degraded_payload
                                raise StreamRetryableError(
                                    "Upstream rejected payload; retrying with degraded fields"
                                )

                            if not started:
                                for event in translator.start_events():
                                    started = True
                                    yield event
                            yield translator.failure_event(
                                {"message": error_message, "type": "upstream_error"}
                            )
                            return

                        content_type = response.headers.get(
                            "content-type", ""
                        ).partition(";")[0]
                        if "text/event-stream" not in content_type:
                            await response.aread()
                            error_message = extract_error_message(response)
                            degraded_payload = apply_degrade_fields(
                                payload,
                                settings.openbridge_degrade_fields,
                                error_message,
                            )
                            if degraded_payload:
                                payload = degraded_payload
                                raise StreamRetryableError(
                                    "Upstream did not return SSE; retrying with degraded fields"
                                )

                            if not started:
                                for event in translator.start_events():
                                    started = True
                                    yield event
                            yield translator.failure_event(
                                {"message": error_message, "type": "upstream_error"}
                            )
                            return

                        if not started:
                            for event in translator.start_events():
                                started = True
                                yield event

                        async for sse in event_source.aiter_sse():
                            if not sse.data:
                                continue
                            if sse.data == "[DONE]":
                                break
                            chunk = json.loads(sse.data)
                            if not isinstance(chunk, dict):
                                # Ignore non-object frames defensively.
                                continue

                            if isinstance(chunk.get("usage"), dict):
                                raw_usage = dict(chunk["usage"])
                                last_usage = raw_usage
                                translator.set_usage(
                                    normalize_responses_usage(raw_usage)
                                )
                                if on_upstream_stats is not None:
                                    await on_upstream_stats(raw_usage, finish_reason)

                            choices = chunk.get("choices")
                            if isinstance(choices, list):
                                for choice in choices:
                                    if not isinstance(choice, dict):
                                        continue
                                    fr = choice.get("finish_reason")
                                    if isinstance(fr, str) and fr:
                                        finish_reason = fr
                                        if on_upstream_stats is not None:
                                            await on_upstream_stats(
                                                last_usage, finish_reason
                                            )

                            # OpenRouter can send mid-stream errors as a final chunk with
                            # finish_reason="error" and a top-level `error` object.
                            if isinstance(chunk.get("error"), dict):
                                error_obj = chunk["error"]
                                error_message = error_obj.get("message") or str(
                                    error_obj
                                )
                                if not started:
                                    for event in translator.start_events():
                                        started = True
                                        yield event
                                yield translator.failure_event(
                                    {
                                        "message": str(error_message),
                                        "type": "upstream_error",
                                    }
                                )
                                return

                            for event in translator.process_chunk(chunk):
                                yield event
                    break
                except Exception as exc:  # noqa: BLE001
                    if not started:
                        raise StreamRetryableError(str(exc)) from exc
                    raise
        for event in translator.finish_events():
            yield event
        if on_complete is not None:
            await on_complete(
                translator.final_response(), translator.assistant_message()
            )
    except Exception as exc:  # noqa: BLE001
        error = {"message": str(exc), "type": "upstream_error"}
        if not started:
            for event in translator.start_events():
                yield event
        yield translator.failure_event(error)


def _event(event_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event_name, "data": json_dumps(data)}
