from __future__ import annotations

from typing import Any

from openbridge.models.chat import ChatCompletionResponse
from openbridge.models.responses import (
    ResponseOutputItem,
    ResponseOutputText,
    ResponsesCreateResponse,
)
from openbridge.tools.registry import ToolVirtualizationResult
from openbridge.utils import new_id, now_ts


def chat_response_to_responses(
    chat_response: ChatCompletionResponse,
    *,
    model: str,
    tool_map: ToolVirtualizationResult,
    response_id: str | None = None,
    created_at: int | None = None,
) -> ResponsesCreateResponse:
    response_id = response_id or new_id("resp")
    created_at = created_at or now_ts()
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

    return ResponsesCreateResponse(
        id=response_id,
        created_at=created_at,
        model=model,
        output=output,
        usage=chat_response.usage,
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

    return ResponseOutputItem(id=new_id("item"), type="reasoning", **extra)


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
        call_id=tool_call.id,
        name=name,
        arguments=tool_call.function.arguments,
    )


def _text_to_output_item(content: Any) -> ResponseOutputItem:
    if not isinstance(content, str):
        content = str(content)
    return ResponseOutputItem(
        id=new_id("item"),
        type="message",
        role="assistant",
        content=[ResponseOutputText(text=content)],
    )
