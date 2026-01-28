from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class TraceRecord(BaseModel):
    """
    A best-effort request trace for debugging.

    This record is intentionally JSON-serializable and safe-ish by default:
    it should only store sanitized/truncated payloads.
    """

    request_id: str
    response_id: str | None = None
    created_at: int
    updated_at: int

    method: str | None = None
    path: str | None = None
    stream: bool | None = None

    # Sanitized snapshots (never store upstream API keys / auth headers here).
    responses_request: dict[str, Any] | None = None
    chat_request: dict[str, Any] | None = None
    messages_for_state: list[dict[str, Any]] | None = None
    tool_map: dict[str, Any] | None = None

    responses_response: dict[str, Any] | None = None
    assistant_message: dict[str, Any] | None = None

    upstream: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class TraceStore(Protocol):
    async def get_by_request_id(self, request_id: str) -> TraceRecord | None: ...

    async def get_by_response_id(self, response_id: str) -> TraceRecord | None: ...

    async def set(self, record: TraceRecord, ttl_seconds: int) -> None: ...

    async def close(self) -> None: ...
