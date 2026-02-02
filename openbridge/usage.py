from __future__ import annotations

from typing import Any

from openbridge.request_summary import parse_usage


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_responses_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Normalize an OpenAI/OpenRouter-like usage dict to the OpenAI Responses API schema.

    The Responses API expects:
    - input_tokens / input_tokens_details
    - output_tokens / output_tokens_details
    - total_tokens
    """
    if not isinstance(usage, dict):
        return None

    summary = parse_usage(usage)
    input_tokens = summary.prompt_tokens
    output_tokens = summary.completion_tokens
    total_tokens = summary.total_tokens
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    normalized: dict[str, Any] = {}
    if input_tokens is not None:
        normalized["input_tokens"] = input_tokens
    if output_tokens is not None:
        normalized["output_tokens"] = output_tokens
    if total_tokens is not None:
        normalized["total_tokens"] = total_tokens

    input_details = usage.get("input_tokens_details")
    if not isinstance(input_details, dict):
        input_details = usage.get("prompt_tokens_details")
    if isinstance(input_details, dict):
        cached_tokens = _int_or_none(input_details.get("cached_tokens"))
        if cached_tokens is not None:
            normalized["input_tokens_details"] = {"cached_tokens": cached_tokens}

    output_details = usage.get("output_tokens_details")
    if not isinstance(output_details, dict):
        output_details = usage.get("completion_tokens_details")
    if isinstance(output_details, dict):
        reasoning_tokens = _int_or_none(output_details.get("reasoning_tokens"))
        if reasoning_tokens is not None:
            normalized["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}

    return normalized or None
