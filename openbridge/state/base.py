from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from openbridge.models.chat import ChatMessage
from openbridge.models.responses import ResponsesCreateResponse


class StoredResponse(BaseModel):
    response: ResponsesCreateResponse
    messages: list[ChatMessage]
    tool_function_map: dict[str, str]
    model: str


class StateStore(Protocol):
    async def get(self, response_id: str) -> StoredResponse | None:
        ...

    async def set(self, response_id: str, record: StoredResponse, ttl_seconds: int) -> None:
        ...

    async def delete(self, response_id: str) -> None:
        ...
