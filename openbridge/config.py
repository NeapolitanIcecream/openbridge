from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openrouter_api_key: str = Field(..., alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_http_referer: str | None = Field(
        None,
        alias="OPENROUTER_HTTP_REFERER",
    )
    openrouter_x_title: str | None = Field(
        None,
        alias="OPENROUTER_X_TITLE",
    )

    openbridge_host: str = Field("127.0.0.1", alias="OPENBRIDGE_HOST")
    openbridge_port: int = Field(8000, alias="OPENBRIDGE_PORT")
    openbridge_log_level: str = Field("INFO", alias="OPENBRIDGE_LOG_LEVEL")
    openbridge_ssl_certfile: Path | None = Field(None, alias="OPENBRIDGE_SSL_CERTFILE")
    openbridge_ssl_keyfile: Path | None = Field(None, alias="OPENBRIDGE_SSL_KEYFILE")
    openbridge_ssl_keyfile_password: str | None = Field(
        None, alias="OPENBRIDGE_SSL_KEYFILE_PASSWORD"
    )
    openbridge_state_backend: Literal["memory", "redis", "disabled"] = Field(
        "memory",
        alias="OPENBRIDGE_STATE_BACKEND",
    )
    openbridge_redis_url: str = Field(
        "redis://localhost:6379/0",
        alias="OPENBRIDGE_REDIS_URL",
    )
    openbridge_model_map_path: Path | None = Field(
        None,
        alias="OPENBRIDGE_MODEL_MAP_PATH",
    )
    openbridge_client_api_key: str | None = Field(
        None,
        alias="OPENBRIDGE_CLIENT_API_KEY",
    )
    openbridge_request_timeout_s: float = Field(
        120.0,
        alias="OPENBRIDGE_REQUEST_TIMEOUT_S",
    )
    openbridge_retry_max_attempts: int = Field(
        2,
        alias="OPENBRIDGE_RETRY_MAX_ATTEMPTS",
    )
    openbridge_retry_max_seconds: float = Field(
        15.0,
        alias="OPENBRIDGE_RETRY_MAX_SECONDS",
    )
    openbridge_retry_backoff: float = Field(
        0.5,
        alias="OPENBRIDGE_RETRY_BACKOFF",
    )
    openbridge_degrade_fields: list[str] = Field(
        default_factory=lambda: ["verbosity"],
        alias="OPENBRIDGE_DEGRADE_FIELDS",
    )
    openbridge_memory_ttl_seconds: int = Field(
        3600,
        alias="OPENBRIDGE_MEMORY_TTL_SECONDS",
    )

    @field_validator("openbridge_degrade_fields", mode="before")
    @classmethod
    def _split_degrade_fields(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @model_validator(mode="after")
    def _validate_tls_settings(self) -> "Settings":
        cert = self.openbridge_ssl_certfile
        key = self.openbridge_ssl_keyfile
        if (cert is None) ^ (key is None):
            raise ValueError(
                "OPENBRIDGE_SSL_CERTFILE and OPENBRIDGE_SSL_KEYFILE must be set together"
            )
        if cert is not None and not cert.exists():
            raise ValueError(f"OPENBRIDGE_SSL_CERTFILE not found: {cert}")
        if key is not None and not key.exists():
            raise ValueError(f"OPENBRIDGE_SSL_KEYFILE not found: {key}")
        return self


_settings: Settings | None = None


def load_settings() -> Settings:
    global _settings
    if _settings is None:
        # Settings is loaded from environment variables via pydantic-settings.
        # Use Any to avoid static type checkers requiring init params.
        settings_cls: Any = Settings
        _settings = settings_cls()
    assert _settings is not None
    return _settings


def reset_settings_cache() -> None:
    """Reset the cached Settings instance.

    This is mainly useful for tests and CLI invocations that intentionally vary
    environment variables between runs.
    """
    global _settings
    _settings = None
