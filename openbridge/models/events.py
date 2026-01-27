from __future__ import annotations

from pydantic import BaseModel

from openbridge.models.responses import ResponseOutputItem, ResponsesCreateResponse


class ResponseCreatedEvent(BaseModel):
    type: str = "response.created"
    response: ResponsesCreateResponse


class ResponseOutputItemAddedEvent(BaseModel):
    type: str = "response.output_item.added"
    output_index: int
    item: ResponseOutputItem


class ResponseOutputTextDeltaEvent(BaseModel):
    type: str = "response.output_text.delta"
    output_index: int
    content_index: int
    delta: str


class ResponseOutputTextDoneEvent(BaseModel):
    type: str = "response.output_text.done"
    output_index: int
    content_index: int
    text: str


class ResponseFunctionCallArgumentsDeltaEvent(BaseModel):
    type: str = "response.function_call_arguments.delta"
    output_index: int
    delta: str


class ResponseFunctionCallArgumentsDoneEvent(BaseModel):
    type: str = "response.function_call_arguments.done"
    output_index: int
    arguments: str


class ResponseOutputItemDoneEvent(BaseModel):
    type: str = "response.output_item.done"
    output_index: int
    item: ResponseOutputItem


class ResponseCompletedEvent(BaseModel):
    type: str = "response.completed"
    response: ResponsesCreateResponse


class ResponseFailedEvent(BaseModel):
    type: str = "response.failed"
    response: ResponsesCreateResponse
    error: dict
