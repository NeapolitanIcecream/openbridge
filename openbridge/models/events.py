from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from openbridge.models.responses import ResponseOutputItem, ResponsesCreateResponse


class ResponseCreatedEvent(BaseModel):
    type: str = "response.created"
    response: ResponsesCreateResponse
    sequence_number: int


class ResponseInProgressEvent(BaseModel):
    type: str = "response.in_progress"
    response: ResponsesCreateResponse
    sequence_number: int


class ResponseOutputItemAddedEvent(BaseModel):
    type: str = "response.output_item.added"
    output_index: int
    item: ResponseOutputItem
    sequence_number: int


class ResponseContentPartAddedEvent(BaseModel):
    type: str = "response.content_part.added"
    item_id: str
    output_index: int
    content_index: int
    part: dict[str, Any]
    sequence_number: int


class ResponseOutputTextDeltaEvent(BaseModel):
    type: str = "response.output_text.delta"
    item_id: str
    output_index: int
    content_index: int
    delta: str
    sequence_number: int
    logprobs: list[dict[str, Any]] | None = None


class ResponseOutputTextDoneEvent(BaseModel):
    type: str = "response.output_text.done"
    item_id: str
    output_index: int
    content_index: int
    text: str
    sequence_number: int
    logprobs: list[dict[str, Any]] | None = None


class ResponseFunctionCallArgumentsDeltaEvent(BaseModel):
    type: str = "response.function_call_arguments.delta"
    item_id: str
    output_index: int
    delta: str
    sequence_number: int


class ResponseFunctionCallArgumentsDoneEvent(BaseModel):
    type: str = "response.function_call_arguments.done"
    item_id: str
    output_index: int
    arguments: str
    sequence_number: int


class ResponseOutputItemDoneEvent(BaseModel):
    type: str = "response.output_item.done"
    output_index: int
    item: ResponseOutputItem
    sequence_number: int


class ResponseContentPartDoneEvent(BaseModel):
    type: str = "response.content_part.done"
    item_id: str
    output_index: int
    content_index: int
    part: dict[str, Any]
    sequence_number: int


class ResponseCompletedEvent(BaseModel):
    type: str = "response.completed"
    response: ResponsesCreateResponse
    sequence_number: int


class ResponseFailedEvent(BaseModel):
    type: str = "response.failed"
    response: ResponsesCreateResponse
    sequence_number: int
