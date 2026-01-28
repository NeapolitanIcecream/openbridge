from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from httpx_sse import EventSource, aconnect_sse

from openbridge.config import Settings


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.openbridge_request_timeout_s)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._settings.openrouter_api_key}"}
        if self._settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self._settings.openrouter_http_referer
        if self._settings.openrouter_x_title:
            headers["X-Title"] = self._settings.openrouter_x_title
        return headers

    def _url(self) -> str:
        return f"{self._settings.openrouter_base_url.rstrip('/')}/chat/completions"

    async def chat_completions(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._client.post(
            self._url(),
            headers=self._headers(),
            json=payload,
        )

    async def stream_chat_completions(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[Any]:
        async with self.connect_chat_completions_sse(payload) as event_source:
            async for sse in event_source.aiter_sse():
                yield sse

    @asynccontextmanager
    async def connect_chat_completions_sse(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[EventSource]:
        async with aconnect_sse(
            self._client,
            "POST",
            self._url(),
            headers=self._headers(),
            json=payload,
        ) as event_source:
            yield event_source
