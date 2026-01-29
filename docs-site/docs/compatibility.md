# API compatibility

OpenBridge aims to be a **practical compatibility layer**, not a perfect re-implementation
of every Responses feature and edge case.

This page documents the compatibility surface that is intentionally supported today.

## Endpoints

- `POST /v1/responses` (streaming and non-streaming)
- `GET /v1/responses/{response_id}` (requires state enabled)
- `DELETE /v1/responses/{response_id}` (requires state enabled)
- `GET /healthz`, `GET /version`, `GET /metrics`
- Debug endpoints under `/v1/debug/*` (optional, disabled by default)

## Compatibility levels (mental model)

- **Level 0 (most robust)**: text-only, `input` is a string, no tools, no streaming.
- **Level 1 (recommended)**: tool calling + tool loop, including streaming SSE translation.
- **Level 2 (stateful)**: `previous_response_id` + JSON Schema structured outputs.
- **Level 3 (tool protocol)**: built-in tool types and “agent tools” carried via function-tool
  virtualization (e.g. `apply_patch`, `shell`).

## Request fields (common subset)

OpenBridge supports the common Responses request fields used by agent-like clients:

- `model` (with optional alias mapping via `OPENBRIDGE_MODEL_MAP_PATH`)
- `instructions` (mapped into a leading `system` message)
- `input` (string or item array)
- `tools`, `tool_choice`, `parallel_tool_calls`
- `max_output_tokens`, `temperature`, `top_p`, `verbosity`
- `text.format`:
  - `json_schema` → upstream `response_format=json_schema`
  - `json_object` → upstream `response_format=json_object` (model still needs instructions)
- `stream`
- `previous_response_id` (requires state enabled)

If the upstream rejects specific optional fields, OpenBridge can retry once with a
reduced payload based on `OPENBRIDGE_DEGRADE_FIELDS` (default: `verbosity`).

## Tool calling and tool loop

OpenBridge preserves the core linkage between the two APIs:

- Responses output items use `call_id`
- Chat Completions uses `tool_calls[].id`, and tool messages reference it via `tool_call_id`

The bridge keeps these ids aligned so clients can execute tools locally and append
tool outputs back into the next Responses request.

### Built-in tool types (virtualized)

Some upstreams only accept **function tools**. To keep compatibility, OpenBridge provides
a small set of built-in tools as **virtualized function tools**:

- `apply_patch`
- `shell`
- `local_shell`

## Structured outputs (JSON Schema)

When a Responses request asks for:

- `text.format.type = "json_schema"`

OpenBridge maps it to OpenRouter's `response_format.type = "json_schema"` and returns the
model output in a Responses-compatible form.

Support is model/provider dependent; if the upstream does not support structured outputs,
OpenBridge will surface the upstream error (or a degraded retry may occur if configured).

## Reasoning passthrough (best-effort)

OpenRouter Chat Completions can expose reasoning via `message.reasoning` and
`message.reasoning_details[]` for some models. OpenBridge preserves these details
best-effort and stores them in traces/state to improve tool-loop continuity.

Some providers/models intentionally do not return reasoning content even when reasoning
is enabled; in that case there is nothing to pass through.

## Known limitations

- **`include` and other advanced Responses extensions** are not guaranteed to be supported.
- **Server-side tool use** (e.g. provider-managed `web_search`) may bypass normal tool-loop
  behavior. For consistent semantics, prefer function-tool virtualization.
- **Perfect event parity** for Responses streaming is not guaranteed; OpenBridge focuses on
  the events most clients rely on (text + tool-call argument deltas + lifecycle events).

