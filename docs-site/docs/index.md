# OpenBridge

OpenBridge is a small HTTP service that exposes a compatible subset of the
OpenAI **Responses API** (`POST /v1/responses`) on top of OpenRouter's
**Chat Completions API**.

It is designed for clients (agents, tool loops) that already rely on Responses
semantics (instructions, output items, `previous_response_id`, SSE events) but
want OpenRouter's model catalog without rewriting client code.

## What it does

- **Responses API facade**: implements `POST /v1/responses` (streaming and non-streaming).
- **Translation layer**: converts Responses requests into Chat Completions payloads and
  converts upstream outputs back to Responses shapes.
- **Tool loop compatibility**: maps Responses `function_call` / `function_call_output`
  to Chat Completions `tool_calls` / `role="tool"` messages. Built-in tool types are
  virtualized as function tools for upstream compatibility.
- **Optional state**: supports `previous_response_id` with a memory/Redis backend.
- **Debuggability**: optional trace capture and debug endpoints to inspect sanitized,
  translated payloads.

## Quick start

Prerequisites:

- Python 3.12+
- `uv`
- An OpenRouter API key (`OPENROUTER_API_KEY`)

Run:

```bash
export OPENROUTER_API_KEY="sk-or-..."
uv sync
uv run openbridge
```

Then send a minimal request:

```bash
curl -sS http://127.0.0.1:8000/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4.1","input":"Hello from OpenBridge"}'
```

## Docs

- [Architecture](architecture.md)
- [API compatibility](compatibility.md)
- [Configuration](configuration.md)
- [Logging & tracing](logging.md)
