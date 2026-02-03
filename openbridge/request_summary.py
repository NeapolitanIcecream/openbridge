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
    cached_tokens: int | None
    reasoning_tokens: int | None

    def input_tokens_excluding_cached(self) -> int | None:
        """Return input tokens excluding cached tokens when available."""
        if self.prompt_tokens is None:
            return None
        if self.cached_tokens is None:
            return self.prompt_tokens
        return max(0, self.prompt_tokens - self.cached_tokens)


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
            cached_tokens=None,
            reasoning_tokens=None,
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

    cached_tokens: int | None = None
    input_details = usage.get("input_tokens_details")
    if not isinstance(input_details, dict):
        input_details = usage.get("prompt_tokens_details")
    if isinstance(input_details, dict):
        cached_tokens = _int_or_none(input_details.get("cached_tokens"))

    reasoning_tokens: int | None = None
    output_details = usage.get("output_tokens_details")
    if not isinstance(output_details, dict):
        output_details = usage.get("completion_tokens_details")
    if isinstance(output_details, dict):
        reasoning_tokens = _int_or_none(output_details.get("reasoning_tokens"))

    return UsageSummary(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost=cost,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _fmt_int(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def _fmt_input_tokens(*, prompt_tokens: int | None, cached_tokens: int | None) -> str:
    if prompt_tokens is None:
        return "-"
    if cached_tokens is None or cached_tokens <= 0:
        return f"{prompt_tokens:,}"
    uncached = max(0, prompt_tokens - cached_tokens)
    return f"{uncached:,} (+ {cached_tokens:,} cached)"


def _fmt_output_tokens(
    *, completion_tokens: int | None, reasoning_tokens: int | None
) -> str:
    if completion_tokens is None:
        return "-"
    if reasoning_tokens is None or reasoning_tokens <= 0:
        return f"{completion_tokens:,}"
    return f"{completion_tokens:,} (reasoning {reasoning_tokens:,})"


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
    prompt_total = usage_summary.prompt_tokens
    completion_total = usage_summary.completion_tokens
    total = usage_summary.total_tokens

    prompt_excl_cached = usage_summary.input_tokens_excluding_cached()
    total_for_tps = total
    if prompt_excl_cached is not None and completion_total is not None:
        total_for_tps = prompt_excl_cached + completion_total
    tps = None
    if total_for_tps is not None and duration_s > 0:
        tps = float(total_for_tps) / float(duration_s)

    duration_ms = int(duration_s * 1000)
    return (
        f"REQ {duration_ms:>6}ms"
        f" | model={_short(model, width=40)}"
        f" | input={_fmt_input_tokens(prompt_tokens=prompt_total, cached_tokens=usage_summary.cached_tokens)}"
        f" | output={_fmt_output_tokens(completion_tokens=completion_total, reasoning_tokens=usage_summary.reasoning_tokens)}"
        f" | cost={_fmt_cost(usage_summary.cost)}"
        f" | tps={_fmt_tps(tps)}"
        f" | finish={finish_reason or '-'}"
        f" | src={_short(source, width=40)}"
    )
