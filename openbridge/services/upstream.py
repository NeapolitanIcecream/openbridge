from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from openbridge.clients.openrouter import OpenRouterClient
from openbridge.config import Settings


RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableUpstreamError(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Retryable upstream error: {response.status_code}")


async def call_with_retry(
    *,
    client: OpenRouterClient,
    payload: dict[str, Any],
    settings: Settings,
) -> httpx.Response:
    @retry(
        retry=retry_if_exception_type((httpx.RequestError, RetryableUpstreamError)),
        stop=stop_after_attempt(settings.openbridge_retry_max_attempts),
        wait=wait_exponential_jitter(
            initial=settings.openbridge_retry_backoff,
            max=settings.openbridge_retry_max_seconds,
        ),
        reraise=True,
    )
    async def _call() -> httpx.Response:
        response = await client.chat_completions(payload)
        if response.status_code in RETRYABLE_STATUS:
            raise RetryableUpstreamError(response)
        return response

    return await _call()


def extract_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict):
        error = data.get("error", {})
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
        if "message" in data:
            return str(data["message"])
    return response.text


def apply_degrade_fields(
    payload: dict[str, Any], fields: list[str], error_message: str
) -> dict[str, Any] | None:
    for field in fields:
        if field in payload and field in error_message:
            new_payload = dict(payload)
            new_payload.pop(field, None)
            return new_payload
    return None
