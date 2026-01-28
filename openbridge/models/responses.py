from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    type: Literal["json_schema", "json_object"]
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


class ResponseOutputItem(BaseModel):
    id: str
    type: str
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
    model: str
    output: list[ResponseOutputItem]
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")
