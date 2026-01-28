# OpenBridge

OpenBridge is a compatibility layer that exposes an OpenAI Responses API surface while sending requests to OpenRouter Chat Completions. It focuses on stable tool calling, streaming conversion, and optional state for `previous_response_id`.

## Compatibility Levels

- Level 0: plain text, non-stream, no tools
- Level 1: tool calling + tool loop, streaming
- Level 2: `previous_response_id` + structured outputs (json_schema)
- Level 3: built-in/MCP tools via function virtualization

## Endpoints

- `POST /v1/responses` (stream and non-stream)
- `GET /v1/responses/{response_id}` (state enabled only)
- `DELETE /v1/responses/{response_id}` (state enabled only)
- `GET /healthz`
- `GET /version`
- `GET /metrics`

## Configuration

Required:

- `OPENROUTER_API_KEY`

Optional:

- `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_X_TITLE`
- `OPENBRIDGE_HOST` (default: `127.0.0.1`)
- `OPENBRIDGE_PORT` (default: `8000`)
- `OPENBRIDGE_LOG_LEVEL` (default: `INFO`)
- `OPENBRIDGE_STATE_BACKEND` (`memory`, `redis`, `disabled`)
- `OPENBRIDGE_REDIS_URL`
- `OPENBRIDGE_MODEL_MAP_PATH` (JSON mapping of model aliases)
- `OPENBRIDGE_CLIENT_API_KEY` (optional client auth)
- `OPENBRIDGE_REQUEST_TIMEOUT_S`
- `OPENBRIDGE_RETRY_MAX_ATTEMPTS`
- `OPENBRIDGE_RETRY_MAX_SECONDS`
- `OPENBRIDGE_RETRY_BACKOFF`
- `OPENBRIDGE_DEGRADE_FIELDS` (comma-separated)
- `OPENBRIDGE_MEMORY_TTL_SECONDS`

Example model map:

```json
{
  "gpt-4.1": "openai/gpt-4.1"
}
```

## Run

```bash
export OPENROUTER_API_KEY="..."
uv sync
uv run python main.py
```

## Quick Test

```bash
curl -sS http://127.0.0.1:8000/healthz
```

## Notes

- Tool virtualization is always enabled; built-in/MCP tools are mapped to function tools upstream.
- Function tool names must not start with `ob_` (reserved for virtualized tools).
- `previous_response_id` requires a state backend; set `OPENBRIDGE_STATE_BACKEND=redis` for multi-instance use.

## Tests

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```
