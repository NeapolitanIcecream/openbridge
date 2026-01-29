import os
from pathlib import Path
from typing import Any

import pytest

from openbridge.config import Settings


def _settings_from_env() -> Settings:
    settings_cls: Any = Settings
    return settings_cls()


@pytest.fixture(autouse=True)
def clean_env():
    """Clean up environment variables before each test."""
    # Store original values
    orig_values = {}
    keys_to_clean = [
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_X_TITLE",
        "OPENBRIDGE_HOST",
        "OPENBRIDGE_PORT",
        "OPENBRIDGE_LOG_LEVEL",
        "OPENBRIDGE_STATE_BACKEND",
        "OPENBRIDGE_REDIS_URL",
        "OPENBRIDGE_STATE_KEY_PREFIX",
        "OPENBRIDGE_DEGRADE_FIELDS",
        "OPENBRIDGE_MODEL_MAP_PATH",
        "OPENBRIDGE_CLIENT_API_KEY",
        "OPENBRIDGE_REQUEST_TIMEOUT_S",
        "OPENBRIDGE_RETRY_MAX_ATTEMPTS",
        "OPENBRIDGE_RETRY_MAX_SECONDS",
        "OPENBRIDGE_RETRY_BACKOFF",
        "OPENBRIDGE_MEMORY_TTL_SECONDS",
    ]

    for key in keys_to_clean:
        if key in os.environ:
            orig_values[key] = os.environ[key]
            del os.environ[key]

    yield

    # Restore original values
    for key in keys_to_clean:
        if key in os.environ:
            del os.environ[key]
        if key in orig_values:
            os.environ[key] = orig_values[key]


def test_settings_default_values():
    """Test that Settings has correct default values."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"

    settings = _settings_from_env()

    assert settings.openrouter_api_key == "test_key"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.openbridge_host == "127.0.0.1"
    assert settings.openbridge_port == 8000
    assert settings.openbridge_log_level == "INFO"
    assert settings.openbridge_state_backend == "memory"
    assert settings.openbridge_redis_url == "redis://localhost:6379/0"
    assert settings.openbridge_state_key_prefix == "openbridge:state"
    assert settings.openbridge_request_timeout_s == 120.0
    assert settings.openbridge_retry_max_attempts == 2
    assert settings.openbridge_retry_max_seconds == 15.0
    assert settings.openbridge_retry_backoff == 0.5
    assert settings.openbridge_degrade_fields == ["verbosity"]
    assert settings.openbridge_memory_ttl_seconds == 3600


def test_settings_from_environment_variables():
    """Test that Settings loads values from environment variables."""
    os.environ["OPENROUTER_API_KEY"] = "custom_key"
    os.environ["OPENBRIDGE_HOST"] = "0.0.0.0"
    os.environ["OPENBRIDGE_PORT"] = "9000"
    os.environ["OPENBRIDGE_LOG_LEVEL"] = "DEBUG"
    os.environ["OPENBRIDGE_STATE_BACKEND"] = "redis"
    os.environ["OPENBRIDGE_STATE_KEY_PREFIX"] = "openbridge:test_state"

    settings = _settings_from_env()

    assert settings.openrouter_api_key == "custom_key"
    assert settings.openbridge_host == "0.0.0.0"
    assert settings.openbridge_port == 9000
    assert settings.openbridge_log_level == "DEBUG"
    assert settings.openbridge_state_backend == "redis"
    assert settings.openbridge_state_key_prefix == "openbridge:test_state"


def test_settings_state_backend_options():
    """Test that state_backend accepts valid options."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"

    for backend in ["memory", "redis", "disabled"]:
        os.environ["OPENBRIDGE_STATE_BACKEND"] = backend
        settings = _settings_from_env()
        assert settings.openbridge_state_backend == backend


def test_settings_degrade_fields_from_json_array():
    """Test that degrade_fields can be parsed from JSON array string."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"
    os.environ["OPENBRIDGE_DEGRADE_FIELDS"] = '["verbosity","temperature","top_p"]'

    settings = _settings_from_env()

    assert settings.openbridge_degrade_fields == ["verbosity", "temperature", "top_p"]


def test_settings_degrade_fields_from_json_array_with_spaces():
    """Test that degrade_fields can be parsed from JSON array with spaces."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"
    os.environ["OPENBRIDGE_DEGRADE_FIELDS"] = '["field1", "field2", "field3"]'

    settings = _settings_from_env()

    assert settings.openbridge_degrade_fields == ["field1", "field2", "field3"]


def test_settings_degrade_fields_empty_array():
    """Test that degrade_fields handles empty JSON array."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"
    os.environ["OPENBRIDGE_DEGRADE_FIELDS"] = "[]"

    settings = _settings_from_env()

    assert settings.openbridge_degrade_fields == []


def test_settings_optional_fields():
    """Test that optional fields can be None."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"

    settings = _settings_from_env()

    assert settings.openrouter_http_referer is None
    assert settings.openrouter_x_title is None
    assert settings.openbridge_model_map_path is None
    assert settings.openbridge_client_api_key is None


def test_settings_model_map_path_as_path():
    """Test that model_map_path is converted to Path."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"
    os.environ["OPENBRIDGE_MODEL_MAP_PATH"] = "/tmp/model_map.json"

    settings = _settings_from_env()

    assert isinstance(settings.openbridge_model_map_path, Path)
    assert str(settings.openbridge_model_map_path) == "/tmp/model_map.json"


def test_settings_numeric_fields():
    """Test that numeric fields are properly typed."""
    os.environ["OPENROUTER_API_KEY"] = "test_key"
    os.environ["OPENBRIDGE_PORT"] = "8080"
    os.environ["OPENBRIDGE_REQUEST_TIMEOUT_S"] = "60.5"
    os.environ["OPENBRIDGE_RETRY_MAX_ATTEMPTS"] = "5"
    os.environ["OPENBRIDGE_RETRY_BACKOFF"] = "1.5"

    settings = _settings_from_env()

    assert isinstance(settings.openbridge_port, int)
    assert settings.openbridge_port == 8080
    assert isinstance(settings.openbridge_request_timeout_s, float)
    assert settings.openbridge_request_timeout_s == 60.5
    assert isinstance(settings.openbridge_retry_max_attempts, int)
    assert settings.openbridge_retry_max_attempts == 5
    assert isinstance(settings.openbridge_retry_backoff, float)
    assert settings.openbridge_retry_backoff == 1.5
