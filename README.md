# OpenBridge

OpenBridge is a lightweight HTTP bridge that lets clients built for the
OpenAI **Responses API** (`POST /v1/responses`) run on top of OpenRouter's
**Chat Completions API**.

It is especially useful for agent-style clients that rely on Responses semantics
(tool loops, streaming events, `previous_response_id`) and want access to
OpenRouter's model catalog without rewriting client code.

## Quick start

### Requirements

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv)
- An OpenRouter API key ([get one](https://openrouter.ai/keys))

### Run locally

```bash
export OPENROUTER_API_KEY="sk-or-..."
uv sync
uv run openbridge
```

The server starts at `http://127.0.0.1:8000`.

### Send a minimal request

```bash
curl -sS http://127.0.0.1:8000/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4.1","input":"Hello from OpenBridge"}'
```

### Use it from a Responses client

Point your client’s base URL to `http://127.0.0.1:8000` and keep calling
`POST /v1/responses` as usual.

## Install as a CLI (optional)

```bash
uv tool install .
openbridge --help
openbridge
```

## Configuration (minimal)

- `OPENROUTER_API_KEY` (**required**)
- `OPENBRIDGE_HOST`, `OPENBRIDGE_PORT` (bind address)
- `OPENBRIDGE_MODEL_MAP_PATH` (optional model alias mapping JSON)
- `OPENBRIDGE_STATE_BACKEND=memory|redis|disabled` and `OPENBRIDGE_REDIS_URL` (optional state)
- `OPENBRIDGE_CLIENT_API_KEY` (optional endpoint protection)

Note: OpenBridge serves **HTTP** by default. If you need HTTPS, enable TLS via
`OPENBRIDGE_SSL_CERTFILE` + `OPENBRIDGE_SSL_KEYFILE` (see docs).

## Documentation

- Read the docs source: [`docs-site/docs/`](docs-site/docs/)
- Serve the docs locally:

```bash
uv sync --extra docs
uv run mkdocs serve -f docs-site/mkdocs.yml
```

Start here:

- [`docs-site/docs/index.md`](docs-site/docs/index.md)
