from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ResponseStatus = Literal[
    "completed",
    "failed",
    "in_progress",
    "cancelled",
    "queued",
    "incomplete",
]

OutputItemStatus = Literal["in_progress", "completed"]


class ResponsesToolFunction(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ResponsesTool(BaseModel):
    type: str
    function: ResponsesToolFunction | None = None
    name: str | None = None
    description: str | None = None
    parameters: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class ToolChoiceFunction(BaseModel):
    type: Literal["function"]
    name: str


class ToolChoiceAllowedTools(BaseModel):
    type: Literal["allowed_tools"]
    mode: Literal["auto", "none", "required"]
    tools: list[ResponsesTool]


class ResponseTextFormat(BaseModel):
    type: Literal["text", "json_schema", "json_object"]
    name: str | None = None
    strict: bool | None = None
    schema_: dict[str, Any] | None = Field(None, alias="schema")

    model_config = ConfigDict(extra="allow")


class ResponseTextConfig(BaseModel):
    format: ResponseTextFormat | None = None

    model_config = ConfigDict(extra="allow")


class InputItem(BaseModel):
    type: str | None = None
    role: Literal["system", "developer", "user", "assistant", "tool"] | None = None
    content: Any | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None
    output: Any | None = None

    model_config = ConfigDict(extra="allow")


class ResponsesCreateRequest(BaseModel):
    model: str
    input: str | list[InputItem]
    instructions: str | None = None
    tools: list[ResponsesTool] | None = None
    tool_choice: str | ToolChoiceFunction | ToolChoiceAllowedTools | None = None
    parallel_tool_calls: bool | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    verbosity: str | None = None
    text: ResponseTextConfig | None = None
    stream: bool | None = False
    previous_response_id: str | None = None
    store: bool | None = None
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class ResponseOutputText(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ResponseOutputItem(BaseModel):
    id: str
    type: str
    status: OutputItemStatus | None = None
    role: str | None = None
    content: list[ResponseOutputText] | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None

    model_config = ConfigDict(extra="allow")


class ResponsesCreateResponse(BaseModel):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    status: ResponseStatus | None = None
    completed_at: int | None = None
    error: dict[str, Any] | None = None
    incomplete_details: dict[str, Any] | None = None
    instructions: Any | None = None
    max_output_tokens: int | None = None
    model: str
    output: list[ResponseOutputItem]
    parallel_tool_calls: bool | None = None
    previous_response_id: str | None = None
    reasoning: dict[str, Any] | None = None
    store: bool | None = None
    temperature: float | None = None
    text: ResponseTextConfig | None = None
    tool_choice: Any | None = None
    tools: list[ResponsesTool] | None = None
    top_p: float | None = None
    truncation: str | None = None
    usage: dict[str, Any] | None = None
    user: str | None = None
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")
