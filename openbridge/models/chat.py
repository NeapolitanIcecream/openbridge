from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ChatToolFunction(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ChatToolDefinition(BaseModel):
    type: Literal["function"]
    function: ChatToolFunction


class ChatToolCallFunction(BaseModel):
    name: str
    arguments: str


class ChatToolCall(BaseModel):
    id: str
    type: Literal["function"]
    function: ChatToolCallFunction


class ChatMessage(BaseModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: Any | None = None
    tool_calls: list[ChatToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    reasoning: str | None = None
    reasoning_details: list[dict[str, Any]] | None = None

    model_config = ConfigDict(extra="allow")


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: list[ChatToolDefinition] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    verbosity: str | None = None
    reasoning: dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    stream: bool | None = None

    model_config = ConfigDict(extra="allow")


class ChatCompletionChoice(BaseModel):
    index: int | None = None
    message: ChatMessage | None = None
    delta: dict[str, Any] | None = None
    finish_reason: str | None = None

    model_config = ConfigDict(extra="allow")


class ChatCompletionResponse(BaseModel):
    id: str | None = None
    object: str | None = None
    created: int | None = None
    model: str | None = None
    choices: list[ChatCompletionChoice] = []
    usage: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")
