# Configuration

OpenBridge is configured via environment variables (and optionally a local `.env` file).
Run `openbridge --help` to see the CLI flags that map to common settings.

## Required

- `OPENROUTER_API_KEY`: OpenRouter API key used for upstream calls.

## OpenRouter settings

- `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- `OPENROUTER_HTTP_REFERER` (optional, attribution)
- `OPENROUTER_X_TITLE` (optional, attribution)

## Server settings

- `OPENBRIDGE_HOST` (default: `127.0.0.1`)
- `OPENBRIDGE_PORT` (default: `8000`)

## Client authentication (optional)

If `OPENBRIDGE_CLIENT_API_KEY` is set, OpenBridge requires one of:

- `Authorization: Bearer <key>`
- `X-API-Key: <key>`

## Model alias mapping (optional)

Use `OPENBRIDGE_MODEL_MAP_PATH` to map client-friendly model aliases to OpenRouter model ids.

Example:

```json
{
  "gpt-4o": "openai/gpt-4o",
  "gpt-4.1": "openai/gpt-4.1"
}
```

## State (`previous_response_id`)

- `OPENBRIDGE_STATE_BACKEND`: `memory` (default) | `redis` | `disabled`
- `OPENBRIDGE_REDIS_URL` (default: `redis://localhost:6379/0`)
- `OPENBRIDGE_MEMORY_TTL_SECONDS` (default: `3600`)

When state is disabled, `previous_response_id` and `GET/DELETE /v1/responses/{id}` return
an error.

## Reliability knobs

- `OPENBRIDGE_REQUEST_TIMEOUT_S` (default: `120`)
- `OPENBRIDGE_RETRY_MAX_ATTEMPTS` (default: `2`)
- `OPENBRIDGE_RETRY_MAX_SECONDS` (default: `15`)
- `OPENBRIDGE_RETRY_BACKOFF` (default: `0.5`)
- `OPENBRIDGE_DEGRADE_FIELDS` (default: `verbosity`)
- `OPENBRIDGE_MAX_TOKENS_BUFFER` (default: `64`)

## TLS / HTTPS (optional)

OpenBridge serves HTTP by default. To enable HTTPS, set both:

- `OPENBRIDGE_SSL_CERTFILE`
- `OPENBRIDGE_SSL_KEYFILE`

Optional:

- `OPENBRIDGE_SSL_KEYFILE_PASSWORD`

## Debugging and tracing

See [Logging & tracing](logging.md) for the trace feature and its environment variables.

