from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


_DEFAULT_SECRET_KEYS = frozenset(
    {
        "authorization",
        "x-api-key",
        "api_key",
        "openrouter_api_key",
        "token",
        "access_token",
        "password",
        "secret",
    }
)

_DEFAULT_CONTENT_KEYS = frozenset({"content", "arguments", "output", "text", "data"})

_HARD_STRING_CAP = 1_000_000  # safety: never store arbitrarily large strings


@dataclass(frozen=True)
class TraceSanitizeConfig:
    content_mode: str = "truncate"  # none|truncate|full
    max_chars: int = 4000
    redact_secrets: bool = True
    secret_keys: frozenset[str] = _DEFAULT_SECRET_KEYS
    content_keys: frozenset[str] = _DEFAULT_CONTENT_KEYS


def sanitize_trace_value(value: Any, *, cfg: TraceSanitizeConfig) -> Any:
    return _sanitize(value, cfg=cfg, parent_key=None)


def _sanitize(value: Any, *, cfg: TraceSanitizeConfig, parent_key: str | None) -> Any:
    if value is None:
        return None

    if isinstance(value, str):
        return _sanitize_string(value, cfg=cfg, parent_key=parent_key)

    if isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, list):
        return [_sanitize(v, cfg=cfg, parent_key=parent_key) for v in value]

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            key_lower = key.lower()
            if cfg.redact_secrets and key_lower in cfg.secret_keys:
                out[key] = "[REDACTED]"
                continue
            out[key] = _sanitize(v, cfg=cfg, parent_key=key_lower)
        return out

    # Fallback: stringify unknown objects.
    return _sanitize_string(str(value), cfg=cfg, parent_key=parent_key)


def _sanitize_string(
    s: str, *, cfg: TraceSanitizeConfig, parent_key: str | None
) -> Any:
    if not s:
        return s

    # Safety cap.
    if len(s) > _HARD_STRING_CAP:
        s = s[:_HARD_STRING_CAP] + f"...[TRUNCATED hard_cap={_HARD_STRING_CAP}]"

    # Content-ish fields can be treated more strictly.
    is_content = parent_key in cfg.content_keys if parent_key else False

    mode = (cfg.content_mode or "truncate").strip().lower()
    if is_content and mode == "none":
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
        return {"_redacted": True, "chars": len(s), "sha256_16": digest}

    if (is_content and mode == "truncate") or (
        not is_content and len(s) > cfg.max_chars
    ):
        max_chars = max(0, int(cfg.max_chars))
        if max_chars and len(s) > max_chars:
            return s[:max_chars] + f"...[TRUNCATED {len(s) - max_chars} chars]"
        return s

    # full: keep as-is.
    return s
