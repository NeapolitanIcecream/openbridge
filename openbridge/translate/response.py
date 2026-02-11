from __future__ import annotations

from typing import Any

from openbridge.models.chat import ChatCompletionResponse
from openbridge.models.responses import (
    ResponseOutputItem,
    ResponseOutputText,
    ResponseTextConfig,
    ResponseTextFormat,
    ResponsesCreateResponse,
)
from openbridge.tools.registry import ToolVirtualizationResult
from openbridge.usage import normalize_responses_usage
from openbridge.utils import new_id, now_ts


def chat_response_to_responses(
    chat_response: ChatCompletionResponse,
    *,
    model: str,
    tool_map: ToolVirtualizationResult,
    response_id: str | None = None,
    created_at: int | None = None,
    completed_at: int | None = None,
    request: Any | None = None,
    store: bool | None = None,
) -> ResponsesCreateResponse:
    response_id = response_id or new_id("resp")
    created_at = created_at or now_ts()
    completed_at = completed_at or created_at
    output: list[ResponseOutputItem] = []

    message = None
    if chat_response.choices:
        message = chat_response.choices[0].message

    if message is not None:
        reasoning_item = _maybe_reasoning_to_output_item(message)
        if reasoning_item is not None:
            output.append(reasoning_item)

    if message and message.tool_calls:
        for tool_call in message.tool_calls:
            item = _tool_call_to_output_item(tool_call, tool_map)
            output.append(item)

    if message and message.content:
        output.append(_text_to_output_item(message.content))

    # Best-effort: include commonly expected Response object fields for strict clients.
    instructions = (
        getattr(request, "instructions", None) if request is not None else None
    )
    max_output_tokens = (
        getattr(request, "max_output_tokens", None) if request is not None else None
    )
    parallel_tool_calls = (
        getattr(request, "parallel_tool_calls", None) if request is not None else None
    )
    if parallel_tool_calls is None and request is not None:
        parallel_tool_calls = True
    previous_response_id = (
        getattr(request, "previous_response_id", None) if request is not None else None
    )
    temperature = getattr(request, "temperature", None) if request is not None else None
    if temperature is None and request is not None:
        temperature = 1.0
    top_p = getattr(request, "top_p", None) if request is not None else None
    if top_p is None and request is not None:
        top_p = 1.0
    tool_choice = getattr(request, "tool_choice", None) if request is not None else None
    if tool_choice is None and request is not None:
        tool_choice = "auto"
    tools = getattr(request, "tools", None) if request is not None else None
    if tools is None and request is not None:
        tools = []
    text = getattr(request, "text", None) if request is not None else None
    if text is None:
        text = ResponseTextConfig(format=ResponseTextFormat(type="text", schema=None))

    return ResponsesCreateResponse(
        id=response_id,
        created_at=created_at,
        status="completed",
        completed_at=completed_at,
        error=None,
        incomplete_details=None,
        instructions=instructions,
        max_output_tokens=max_output_tokens,
        model=model,
        output=output,
        parallel_tool_calls=parallel_tool_calls,
        previous_response_id=previous_response_id,
        store=store,
        temperature=temperature,
        top_p=top_p,
        tool_choice=tool_choice,
        tools=tools,
        text=text,
        truncation="disabled",
        usage=normalize_responses_usage(chat_response.usage),
        metadata=getattr(request, "metadata", None) if request is not None else {},
    )


def _maybe_reasoning_to_output_item(message: Any) -> ResponseOutputItem | None:
    """
    Convert OpenRouter-specific reasoning fields to an OpenAI Responses `reasoning` output item.

    Notes:
    - OpenAI Responses does not expose raw chain-of-thought tokens; the standard `reasoning` item
      typically carries a summary and/or encrypted content (when requested).
    - OpenRouter Chat Completions may expose `message.reasoning` and `message.reasoning_details[]`.
      We preserve these blocks verbatim under `openrouter_*` fields for round-trip replay.
    """
    reasoning: Any = getattr(message, "reasoning", None)
    reasoning_details: Any = getattr(message, "reasoning_details", None)

    extra: dict[str, Any] = {}
    if isinstance(reasoning, str) and reasoning:
        extra["openrouter_reasoning"] = reasoning

    details: list[dict[str, Any]] = []
    if isinstance(reasoning_details, list):
        for detail in reasoning_details:
            if isinstance(detail, dict):
                details.append(detail)

    if details:
        extra["openrouter_reasoning_details"] = details
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
        if summary_parts:
            extra["summary"] = summary_parts

    if not extra:
        return None

    return ResponseOutputItem(
        id=new_id("item"), type="reasoning", status="completed", **extra
    )


def _tool_call_to_output_item(
    tool_call: Any, tool_map: ToolVirtualizationResult
) -> ResponseOutputItem:
    function_name = tool_call.function.name
    external_type = tool_map.function_name_map.get(function_name)
    if external_type:
        item_type = f"{external_type}_call"
        name = external_type
    else:
        item_type = "function_call"
        name = function_name
    return ResponseOutputItem(
        id=new_id("item"),
        type=item_type,
        status="completed",
        call_id=tool_call.id,
        name=name,
        arguments=tool_call.function.arguments,
    )


def _text_to_output_item(content: Any) -> ResponseOutputItem:
    if not isinstance(content, str):
        content = str(content)
    return ResponseOutputItem(
        id=new_id("msg"),
        type="message",
        status="completed",
        role="assistant",
        content=[ResponseOutputText(text=content)],
    )
