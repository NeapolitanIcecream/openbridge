from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from openbridge.clients.openrouter import OpenRouterClient
from openbridge.config import Settings
from openbridge.models.chat import ChatCompletionRequest, ChatMessage, ChatToolCall, ChatToolCallFunction
from openbridge.models.events import (
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)
from openbridge.models.responses import ResponseOutputItem, ResponseOutputText, ResponsesCreateResponse
from openbridge.tools.registry import ToolVirtualizationResult
from openbridge.utils import json_dumps, new_id


@dataclass
class ToolCallState:
    index: int
    call_id: str
    name: str
    arguments: str
    output_index: int
    external_type: str | None


class ResponsesStreamTranslator:
    def __init__(
        self,
        *,
        response_id: str,
        model: str,
        created_at: int,
        tool_map: ToolVirtualizationResult,
    ) -> None:
        self._response_id = response_id
        self._model = model
        self._created_at = created_at
        self._tool_map = tool_map
        self._output_items: list[ResponseOutputItem] = []
        self._text_output_index: int | None = None
        self._text_content: str = ""
        self._tool_calls: dict[int, ToolCallState] = {}

    def start_events(self) -> list[dict[str, Any]]:
        response = self._build_response()
        return [_event("response.created", ResponseCreatedEvent(response=response).model_dump())]

    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        choices = chunk.get("choices", [])
        for choice in choices:
            delta = choice.get("delta", {})
            if "content" in delta and delta["content"] is not None:
                events.extend(self._handle_text_delta(delta["content"]))
            if "tool_calls" in delta and delta["tool_calls"]:
                events.extend(self._handle_tool_call_deltas(delta["tool_calls"]))
        return events

    def finish_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self._text_output_index is not None:
            events.append(
                _event(
                    "response.output_text.done",
                    ResponseOutputTextDoneEvent(
                        output_index=self._text_output_index,
                        content_index=0,
                        text=self._text_content,
                    ).model_dump(),
                )
            )
            item = self._output_items[self._text_output_index]
            events.append(
                _event(
                    "response.output_item.done",
                    ResponseOutputItemDoneEvent(
                        output_index=self._text_output_index, item=item
                    ).model_dump(),
                )
            )

        for state in sorted(self._tool_calls.values(), key=lambda entry: entry.output_index):
            events.append(
                _event(
                    "response.function_call_arguments.done",
                    ResponseFunctionCallArgumentsDoneEvent(
                        output_index=state.output_index, arguments=state.arguments
                    ).model_dump(),
                )
            )
            item = self._output_items[state.output_index]
            events.append(
                _event(
                    "response.output_item.done",
                    ResponseOutputItemDoneEvent(
                        output_index=state.output_index, item=item
                    ).model_dump(),
                )
            )

        response = self._build_response()
        events.append(
            _event(
                "response.completed",
                ResponseCompletedEvent(response=response).model_dump(),
            )
        )
        return events

    def failure_event(self, error: dict[str, Any]) -> dict[str, Any]:
        response = self._build_response()
        return _event(
            "response.failed",
            ResponseFailedEvent(response=response, error=error).model_dump(),
        )

    def assistant_message(self) -> ChatMessage | None:
        tool_calls: list[ChatToolCall] = []
        for state in sorted(self._tool_calls.values(), key=lambda entry: entry.output_index):
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
        if not tool_calls and not content:
            return None
        return ChatMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls or None,
        )

    def final_response(self) -> ResponsesCreateResponse:
        return self._build_response()

    def _handle_text_delta(self, delta: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self._text_output_index is None:
            item = ResponseOutputItem(
                id=new_id("item"),
                type="message",
                role="assistant",
                content=[ResponseOutputText(text="")],
            )
            self._text_output_index = len(self._output_items)
            self._output_items.append(item)
            events.append(
                _event(
                    "response.output_item.added",
                    ResponseOutputItemAddedEvent(
                        output_index=self._text_output_index, item=item
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
                    output_index=self._text_output_index,
                    content_index=0,
                    delta=delta,
                ).model_dump(),
            )
        )
        return events

    def _handle_tool_call_deltas(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            index = tool_call.get("index", 0)
            state = self._tool_calls.get(index)
            call_id = tool_call.get("id") or (state.call_id if state else new_id("call"))
            function = tool_call.get("function", {}) or {}
            name = function.get("name") or (state.name if state else "")
            arguments_delta = function.get("arguments")
            if state is None:
                external_type = self._tool_map.function_name_map.get(name)
                item_type = f"{external_type}_call" if external_type else "function_call"
                item = ResponseOutputItem(
                    id=new_id("item"),
                    type=item_type,
                    call_id=call_id,
                    name=external_type or name,
                    arguments="",
                )
                output_index = len(self._output_items)
                self._output_items.append(item)
                state = ToolCallState(
                    index=index,
                    call_id=call_id,
                    name=name,
                    arguments="",
                    output_index=output_index,
                    external_type=external_type,
                )
                self._tool_calls[index] = state
                events.append(
                    _event(
                        "response.output_item.added",
                        ResponseOutputItemAddedEvent(
                            output_index=output_index, item=item
                        ).model_dump(),
                    )
                )

            if name and state.name != name:
                state.name = name
                item = self._output_items[state.output_index]
                if state.external_type is None:
                    external_type = self._tool_map.function_name_map.get(name)
                    if external_type:
                        state.external_type = external_type
                        item.type = f"{external_type}_call"
                        item.name = external_type
                    else:
                        item.name = name

            if arguments_delta:
                state.arguments += arguments_delta
                self._output_items[state.output_index].arguments = state.arguments
                events.append(
                    _event(
                        "response.function_call_arguments.delta",
                        ResponseFunctionCallArgumentsDeltaEvent(
                            output_index=state.output_index, delta=arguments_delta
                        ).model_dump(),
                    )
                )
        return events

    def _build_response(self) -> ResponsesCreateResponse:
        return ResponsesCreateResponse(
            id=self._response_id,
            created_at=self._created_at,
            model=self._model,
            output=list(self._output_items),
        )


async def stream_responses_events(
    *,
    client: OpenRouterClient,
    chat_request: ChatCompletionRequest,
    tool_map: ToolVirtualizationResult,
    response_id: str,
    created_at: int,
    settings: Settings,
    on_complete: Callable[[ResponsesCreateResponse, ChatMessage | None], Awaitable[None]]
    | None,
) -> AsyncIterator[dict[str, Any]]:
    payload = chat_request.model_dump(exclude_none=True)
    translator = ResponsesStreamTranslator(
        response_id=response_id,
        model=chat_request.model,
        created_at=created_at,
        tool_map=tool_map,
    )
    started = False

    class StreamRetryableError(Exception):
        pass

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
                    async for sse in client.stream_chat_completions(payload):
                        if not started:
                            for event in translator.start_events():
                                started = True
                                yield event
                        if sse.data == "[DONE]":
                            break
                        chunk = json.loads(sse.data)
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
            await on_complete(translator.final_response(), translator.assistant_message())
    except Exception as exc:  # noqa: BLE001
        error = {"message": str(exc), "type": "upstream_error"}
        if started:
            yield translator.failure_event(error)
        else:
            raise


def _event(event_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event_name, "data": json_dumps(data)}
