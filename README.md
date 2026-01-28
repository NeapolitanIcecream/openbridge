# OpenBridge

OpenBridge is a lightweight compatibility layer that allows applications designed for the OpenAI Responses API (`POST /v1/responses`) to seamlessly use OpenRouter's Chat Completions API.

It bridges the gap between stateful, tool-centric clients (like AI agents) and the widely compatible Chat Completions standard, enabling access to a vast array of models via OpenRouter without changing client code.

## Key Features

- **API Compatibility**: Exposes a standard `POST /v1/responses` endpoint that translates requests to OpenRouter's Chat Completions format.
- **Tool Calling Support**: Full support for function calling and tool loops. Automatically virtualizes built-in tools (like `apply_patch`) as standard function tools.
- **Streaming**: Robust Server-Sent Events (SSE) translation, converting Chat Completions chunks into Responses API events (e.g., `output_text.delta`, `output_item.added`).
- **Structured Outputs**: Supports `json_schema` for reliable, structured data extraction.
- **Optional State Management**: Implements `previous_response_id` support using a configurable backend (Memory or Redis), enabling stateful conversations on top of stateless upstream APIs.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- An [OpenRouter API Key](https://openrouter.ai/keys)

### Run

```bash
# Set your OpenRouter API Key
export OPENROUTER_API_KEY="sk-or-..."

# Install dependencies and run
uv sync
uv run openbridge
```

The server will start at `http://127.0.0.1:8000`.

Show CLI help:

```bash
uv run openbridge --help
```

Optionally install it as a global CLI tool:

```bash
uv tool install .
openbridge --help
openbridge
```

### Health Check

```bash
curl -sS http://127.0.0.1:8000/healthz
```

## HTTPS / TLS

OpenBridge serves **HTTP** by default. If a client tries to connect via `https://127.0.0.1:8000`, Uvicorn will log `Invalid HTTP request received.` and the client will disconnect.

Options:

- Use an **HTTP** base URL (recommended for local dev): `http://127.0.0.1:8000`
- Run OpenBridge with **TLS** by setting:
  - `OPENBRIDGE_SSL_CERTFILE`
  - `OPENBRIDGE_SSL_KEYFILE`
  - `OPENBRIDGE_SSL_KEYFILE_PASSWORD` (optional)

## Configuration

Configuration is managed via environment variables.

### Required

- `OPENROUTER_API_KEY`: Your OpenRouter API key.

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Upstream API URL. |
| `OPENBRIDGE_HOST` | `127.0.0.1` | Host to bind the server to. |
| `OPENBRIDGE_PORT` | `8000` | Port to bind the server to. |
| `OPENBRIDGE_SSL_CERTFILE` | - | TLS certificate file path (enables HTTPS). |
| `OPENBRIDGE_SSL_KEYFILE` | - | TLS private key file path (enables HTTPS). |
| `OPENBRIDGE_SSL_KEYFILE_PASSWORD` | - | Optional private key password. |
| `OPENBRIDGE_STATE_BACKEND` | `memory` | State backend: `memory`, `redis`, or `disabled`. |
| `OPENBRIDGE_REDIS_URL` | - | Redis URL (required if backend is `redis`). |
| `OPENBRIDGE_MODEL_MAP_PATH` | - | Path to a JSON file for mapping model aliases. |

### Model Mapping

You can map simplified model names to OpenRouter specific IDs using a JSON file:

```json
{
  "gpt-4o": "openai/gpt-4o",
  "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet"
}
```

## Endpoints

- `POST /v1/responses`: Main endpoint for creating responses (stream and non-stream).
- `GET /v1/responses/{response_id}`: Retrieve past response details (requires state enabled).
- `DELETE /v1/responses/{response_id}`: Delete a past response (requires state enabled).
- `GET /healthz`: Service health check.
- `GET /version`: Service version info.
- `GET /metrics`: Prometheus metrics.

## Development

Run tests and linting:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```
