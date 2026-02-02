from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UsageSummary:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost: float | None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_usage(usage: dict[str, Any] | None) -> UsageSummary:
    """Parse OpenRouter/OpenAI-like usage dict into a normalized summary."""
    if not isinstance(usage, dict):
        return UsageSummary(
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            cost=None,
        )

    prompt_raw = usage.get("prompt_tokens")
    if prompt_raw is None:
        prompt_raw = usage.get("input_tokens")
    prompt = _int_or_none(prompt_raw)

    completion_raw = usage.get("completion_tokens")
    if completion_raw is None:
        completion_raw = usage.get("output_tokens")
    completion = _int_or_none(completion_raw)
    total = _int_or_none(usage.get("total_tokens"))
    cost = _float_or_none(usage.get("cost"))
    return UsageSummary(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost=cost,
    )


def _fmt_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def _fmt_cost(cost: float | None) -> str:
    if cost is None:
        return "-"
    # OpenRouter cost unit is credits.
    return f"{cost:.4f}cr"


def _fmt_tps(tps: float | None) -> str:
    return "-" if tps is None else f"{tps:.1f}"


def _short(value: str | None, *, width: int) -> str:
    if not value:
        return "-"
    v = " ".join(str(value).split())
    return textwrap.shorten(v, width=width, placeholder="...")


def format_request_summary_line(
    *,
    duration_s: float,
    model: str | None,
    source: str | None,
    usage: dict[str, Any] | None,
    finish_reason: str | None,
) -> str:
    """Format a single-line request summary for console logs."""
    usage_summary = parse_usage(usage)
    prompt = usage_summary.prompt_tokens
    completion = usage_summary.completion_tokens
    total = usage_summary.total_tokens
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    tps = None
    if total is not None and duration_s > 0:
        tps = float(total) / float(duration_s)

    duration_ms = int(duration_s * 1000)
    return (
        f"REQ {duration_ms:>6}ms"
        f" | model={_short(model, width=40)}"
        f" | src={_short(source, width=40)}"
        f" | in={_fmt_int(prompt)} out={_fmt_int(completion)}"
        f" | cost={_fmt_cost(usage_summary.cost)}"
        f" | tps={_fmt_tps(tps)}"
        f" | finish={finish_reason or '-'}"
    )
