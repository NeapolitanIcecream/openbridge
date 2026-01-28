from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbridge.config import Settings
from openbridge.models.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatToolCall,
    ChatToolCallFunction,
)
from openbridge.models.responses import (
    InputItem,
    ResponsesCreateRequest,
    ResponsesTool,
    ResponsesToolFunction,
    ToolChoiceAllowedTools,
    ToolChoiceFunction,
)
from openbridge.tools.registry import ToolRegistry, ToolVirtualizationResult
from openbridge.utils import drop_none, json_dumps


@dataclass
class TranslationResult:
    chat_request: ChatCompletionRequest
    tool_map: ToolVirtualizationResult
    messages_for_state: list[ChatMessage]


_model_map_cache: dict[Path, dict[str, str]] = {}


def load_model_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if path in _model_map_cache:
        return _model_map_cache[path]
    if not path.exists():
        _model_map_cache[path] = {}
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Model map must be a JSON object")
    _model_map_cache[path] = {str(k): str(v) for k, v in data.items()}
    return _model_map_cache[path]


def resolve_model(model: str, model_map: dict[str, str]) -> str:
    if model in model_map:
        return model_map[model]
    if "/" in model:
        return model
    return f"openai/{model}"


def translate_request(
    settings: Settings,
    request: ResponsesCreateRequest,
    tool_registry: ToolRegistry,
    *,
    history_messages: list[ChatMessage] | None = None,
) -> TranslationResult:
    model_map = load_model_map(settings.openbridge_model_map_path)
    messages: list[ChatMessage] = []
    history_messages = history_messages or []
    messages.extend(history_messages)

    if request.instructions:
        messages.insert(
            0,
            ChatMessage(role="system", content=request.instructions),
        )

    input_messages = input_items_to_messages(request.input, tool_registry=tool_registry)
    messages.extend(input_messages)

    inferred_tools = infer_tools_from_input_items(
        request.input, tool_registry=tool_registry
    )
    merged_tools = merge_tools(request.tools, inferred_tools)
    effective_tool_choice = request.tool_choice
    if (not request.tools) and inferred_tools and effective_tool_choice is None:
        # If the client didn't declare tools, do not allow the model to call tools,
        # even if we inferred minimal tool definitions from input items.
        effective_tool_choice = "none"

    tools, tool_choice = normalize_tools_and_choice(
        merged_tools, effective_tool_choice, tool_registry
    )
    response_format = build_response_format(request)
    reasoning = getattr(request, "reasoning", None)
    if reasoning is not None and not isinstance(reasoning, dict):
        raise ValueError("reasoning must be an object")

    chat_request = ChatCompletionRequest(
        model=resolve_model(request.model, model_map),
        messages=messages,
        tools=tools.chat_tools if tools.chat_tools else None,
        tool_choice=tool_choice,
        parallel_tool_calls=request.parallel_tool_calls,
        max_tokens=_upstream_max_tokens(
            request.max_output_tokens, buffer=int(settings.openbridge_max_tokens_buffer)
        ),
        temperature=request.temperature,
        top_p=request.top_p,
        verbosity=request.verbosity,
        reasoning=reasoning,
        response_format=response_format,
        stream=request.stream,
    )

    messages_for_state = history_messages + input_messages
    return TranslationResult(chat_request, tools, messages_for_state)


def normalize_tools_and_choice(
    tools: list[ResponsesTool] | None,
    tool_choice: str | ToolChoiceFunction | ToolChoiceAllowedTools | None,
    tool_registry: ToolRegistry,
) -> tuple[ToolVirtualizationResult, str | dict[str, Any] | None]:
    filtered_tools = tools or []
    normalized_tool_choice: str | dict[str, Any] | None = None

    if isinstance(tool_choice, ToolChoiceAllowedTools):
        allowed = tool_choice.tools
        filtered_tools = filter_tools_by_allowed(filtered_tools, allowed)
        normalized_tool_choice = tool_choice.mode
    elif isinstance(tool_choice, ToolChoiceFunction):
        normalized_tool_choice = {
            "type": "function",
            "function": {"name": tool_choice.name},
        }
    else:
        normalized_tool_choice = tool_choice

    tool_map = tool_registry.virtualize_tools(filtered_tools)
    return tool_map, normalized_tool_choice


def filter_tools_by_allowed(
    tools: list[ResponsesTool], allowed: list[ResponsesTool]
) -> list[ResponsesTool]:
    allowed_set: set[str] = set()
    for tool in allowed:
        if tool.type == "function":
            if tool.function and tool.function.name:
                allowed_set.add(tool.function.name)
            elif tool.name:
                allowed_set.add(tool.name)
        else:
            allowed_set.add(tool.type)

    filtered: list[ResponsesTool] = []
    for tool in tools:
        if tool.type == "function":
            name = tool.function.name if tool.function else tool.name
            if name and name in allowed_set:
                filtered.append(tool)
        else:
            if tool.type in allowed_set:
                filtered.append(tool)
    return filtered


def build_response_format(request: ResponsesCreateRequest) -> dict[str, Any] | None:
    if not request.text or not request.text.format:
        return None
    fmt = request.text.format
    if fmt.type == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": drop_none(
                {"name": fmt.name, "strict": fmt.strict, "schema": fmt.schema_}
            ),
        }
    if fmt.type == "json_object":
        return {"type": "json_object"}
    return None


def input_items_to_messages(
    input_value: str | list[InputItem],
    *,
    tool_registry: ToolRegistry,
) -> list[ChatMessage]:
    if isinstance(input_value, str):
        return [ChatMessage(role="user", content=input_value)]

    messages: list[ChatMessage] = []
    pending_reasoning_details: list[dict[str, Any]] = []
    for raw_item in input_value:
        item = (
            raw_item
            if isinstance(raw_item, InputItem)
            else InputItem.model_validate(raw_item)
        )
        if item.role is not None and item.content is not None:
            content = item.content
            if not isinstance(content, (str, list, dict)):
                content = json_dumps(content)
            msg = ChatMessage(role=item.role, content=content)
            if msg.role == "assistant" and pending_reasoning_details:
                msg.reasoning_details = list(pending_reasoning_details)
                pending_reasoning_details.clear()
            messages.append(msg)
            continue

        item_type = item.type or ""
        if item_type == "reasoning":
            data = item.model_dump()
            raw_details = data.get("openrouter_reasoning_details")
            if isinstance(raw_details, list):
                for detail in raw_details:
                    if isinstance(detail, dict):
                        pending_reasoning_details.append(detail)
            continue

        if item_type == "function_call":
            _append_tool_call(
                messages,
                ChatToolCall(
                    id=item.call_id or "",
                    type="function",
                    function=ChatToolCallFunction(
                        name=item.name or "",
                        arguments=item.arguments or "{}",
                    ),
                ),
            )
            if pending_reasoning_details and messages and messages[-1].role == "assistant":
                messages[-1].reasoning_details = list(pending_reasoning_details)
                pending_reasoning_details.clear()
            continue

        if item_type == "function_call_output":
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=item.call_id,
                    content=_stringify_output(item.output),
                )
            )
            continue

        if item_type.endswith("_call"):
            external_type = item_type[: -len("_call")]
            function_name = tool_registry.function_name_for_external(external_type)
            _append_tool_call(
                messages,
                ChatToolCall(
                    id=item.call_id or "",
                    type="function",
                    function=ChatToolCallFunction(
                        name=function_name,
                        arguments=tool_registry.tool_call_args_from_item(
                            external_type, item
                        ),
                    ),
                ),
            )
            if pending_reasoning_details and messages and messages[-1].role == "assistant":
                messages[-1].reasoning_details = list(pending_reasoning_details)
                pending_reasoning_details.clear()
            continue

        if item_type.endswith("_call_output"):
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=item.call_id,
                    content=_stringify_output(item.output),
                )
            )
            continue

    return messages


def infer_tools_from_input_items(
    input_value: str | list[InputItem],
    *,
    tool_registry: ToolRegistry,
) -> list[ResponsesTool]:
    """
    Infer minimal tool definitions from Responses input items.

    This improves compatibility for follow-up requests that include tool call items
    (e.g. function_call / *_call) but omit the tools[] field.
    """
    if isinstance(input_value, str):
        return []

    inferred: list[ResponsesTool] = []
    seen: set[str] = set()

    for raw_item in input_value:
        item = (
            raw_item
            if isinstance(raw_item, InputItem)
            else InputItem.model_validate(raw_item)
        )
        item_type = item.type or ""

        if item_type == "function_call":
            name = (item.name or "").strip()
            if not name:
                continue
            # Avoid creating user-defined tools with the internal reserved prefix.
            if name.startswith("ob_"):
                continue
            key = f"function:{name}"
            if key in seen:
                continue
            inferred.append(
                ResponsesTool(
                    type="function",
                    function=ResponsesToolFunction(
                        name=name,
                        description="Inferred tool definition (client did not provide schema).",
                        parameters={
                            "type": "object",
                            "properties": {},
                            "additionalProperties": True,
                        },
                    ),
                )
            )
            seen.add(key)
            continue

        # Built-in tool call items (tool virtualization).
        if item_type.endswith("_call") and item_type != "function_call":
            external_type = item_type[: -len("_call")]
            if not external_type:
                continue
            key = f"builtin:{external_type}"
            if key in seen:
                continue
            inferred.append(ResponsesTool(type=external_type))
            seen.add(key)
            continue

        if item_type.endswith("_call_output") and item_type != "function_call_output":
            external_type = item_type[: -len("_call_output")]
            if not external_type:
                continue
            key = f"builtin:{external_type}"
            if key in seen:
                continue
            inferred.append(ResponsesTool(type=external_type))
            seen.add(key)
            continue

    return inferred


def merge_tools(
    tools: list[ResponsesTool] | None,
    inferred_tools: list[ResponsesTool],
) -> list[ResponsesTool] | None:
    if (not tools) and (not inferred_tools):
        return None

    merged: list[ResponsesTool] = []
    seen: set[str] = set()

    def _tool_key(tool: ResponsesTool) -> str | None:
        if tool.type == "function":
            name = ""
            if tool.function and tool.function.name:
                name = str(tool.function.name)
            elif tool.name:
                name = str(tool.name)
            name = name.strip()
            if not name:
                return None
            return f"function:{name}"
        return f"builtin:{tool.type}"

    for tool in (tools or []) + inferred_tools:
        key = _tool_key(tool)
        if key is None or key in seen:
            continue
        seen.add(key)
        merged.append(tool)

    return merged


def _upstream_max_tokens(
    max_output_tokens: int | None,
    *,
    buffer: int,
) -> int | None:
    """
    Compute upstream `max_tokens` from Responses `max_output_tokens`.

    Some upstreams account for hidden reasoning tokens within `max_tokens`, which can
    starve short visible outputs. Adding a small buffer improves reliability for
    "ACK/OK" style responses and tool loop follow-ups.
    """
    if max_output_tokens is None:
        return None
    if max_output_tokens <= 0:
        return max_output_tokens
    if buffer <= 0:
        return max_output_tokens
    return max_output_tokens + buffer


def _append_tool_call(messages: list[ChatMessage], tool_call: ChatToolCall) -> None:
    if messages and messages[-1].role == "assistant" and messages[-1].tool_calls:
        messages[-1].tool_calls.append(tool_call)
        return
    messages.append(ChatMessage(role="assistant", content=None, tool_calls=[tool_call]))


def _stringify_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json_dumps(output)
