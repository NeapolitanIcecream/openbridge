# Architecture

OpenBridge is an HTTP adapter that sits between **Responses API** clients and OpenRouter
**Chat Completions**.

## High-level flow

```text
Client (OpenAI Responses API)
  |
  |  POST /v1/responses (stream? tools? previous_response_id?)
  v
OpenBridge
  |-- Request validation + normalization
  |-- Translation layer (Responses <-> Chat Completions)
  |-- Streaming bridge (SSE <-> SSE)
  |-- Optional state store (previous_response_id)
  |-- Optional trace store (debug bundles)
  v
OpenRouter (Chat Completions API)
  v
Provider / Model
```

## Core components (in this repo)

- **API layer**: `openbridge/api/routes.py` (FastAPI)
- **Upstream client**: `openbridge/clients/openrouter.py` (HTTPX)
- **Translation**:
  - `openbridge/translate/request.py` (Responses → Chat Completions)
  - `openbridge/translate/response.py` (Chat Completions → Responses)
- **Streaming bridge**: `openbridge/streaming/bridge.py`
- **Tool virtualization**: `openbridge/tools/*` (built-ins + registry)
- **State store**: `openbridge/state/*` (memory / redis / disabled)
- **Trace store**: `openbridge/trace/*` (memory / redis / disabled)

## Request lifecycle

1. **Receive** `POST /v1/responses`.
2. If `previous_response_id` is present, **load history** from the configured state store.
3. **Translate** the Responses request to a Chat Completions request:
   - `instructions` → a leading `system` message
   - `input` → `messages`
   - `tools` → **function tools** (built-in tool types are virtualized)
   - `text.format=json_schema` → `response_format=json_schema`
4. **Call** OpenRouter with retries for transient failures (e.g. 429/5xx).
5. **Translate back** to a Responses response:
   - non-stream: build a `response` object
   - stream: emit Responses streaming events as `text/event-stream`

## Tool loop mapping (key idea)

OpenAI Responses uses `call_id` to connect `function_call` ↔ `function_call_output`.
Chat Completions uses `tool_calls[].id` ↔ `tool` messages via `tool_call_id`.

OpenBridge preserves this relationship so tool loops can round-trip cleanly.

## Streaming bridge

For `stream=true`, OpenBridge reads upstream Chat Completions SSE chunks and emits
Responses streaming events such as:

- `response.output_text.delta` / `response.output_text.done`
- `response.function_call_arguments.delta` / `response.function_call_arguments.done`
- `response.completed` / `response.failed`

The bridge maintains an internal per-request state to aggregate deltas and to emit the
right “added/done” events for output items.

## Optional state and traces

- **State (`previous_response_id`)**: stores translated chat history and the Responses
  response, enabling stateful client workflows on top of stateless upstream APIs.
- **Tracing (debug bundles)**: stores a sanitized bundle of the original request, translated
  upstream payload, tool maps, and outputs. Debug endpoints can expose the bundle for
  local debugging when explicitly enabled.

