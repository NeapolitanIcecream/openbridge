# Logging

OpenBridge uses **loguru** for logs and **Rich** for console rendering.

## Console output format

By default, logs are printed to stdout with the following columns:

```text
YYYY-MM-DD HH:mm:ss | LEVEL    | <request_id> | <upstream_request_id> | message
```

- **request_id**: extracted from the incoming `X-Request-Id` header, or generated automatically.
  OpenBridge always returns it in the response header `X-Request-Id`.
- **upstream_request_id**: the upstream `x-request-id` returned by OpenRouter (when available).

This makes it easy to correlate:

- client request ↔ OpenBridge logs (`request_id`)
- OpenBridge request ↔ OpenRouter support logs (`upstream_request_id`)

## Request summary logs (usage, cost, throughput)

OpenBridge emits a single **request summary** line for every completed or interrupted
`POST /v1/responses` request (both non-streaming and streaming).

The summary is logged as an `INFO` message starting with `REQ` and includes:

- duration
- model
- request source (`X-OpenBridge-Source` header, or `User-Agent` as fallback)
- input / output tokens
- cost (OpenRouter credits)
- throughput (tokens/s)
- finish reason (e.g. `stop`, `tool_calls`, `error`, `cancelled`)

Example:

```text
... | INFO     | req_... | or_... | REQ   842ms | model=openai/gpt-4.1 | src=codex-cli/0.92.0 | in=194 out=2 | cost=0.9500cr | tps=232.8 | finish=stop
```

## Log level

Configure the log level via environment variables:

- `OPENBRIDGE_LOG_LEVEL` (default: `INFO`)

## Write logs to a file

To write logs to a file (in addition to console output), set:

- `OPENBRIDGE_LOG_FILE=/path/to/openbridge.log`

Or use the CLI flag:

```bash
uv run openbridge --log-file ./openbridge.log
```

Notes:

- The parent directory must exist.
- The file sink is asynchronous (`enqueue=True`) to reduce request latency impact.

## Trace logging (JSON payloads for debugging)

OpenBridge can capture a **sanitized trace bundle** per request (Responses request, translated
Chat Completions payload including `messages`, tool maps, upstream ids, and final outputs).

There are two steps:

1) **Enable trace capture**

- Global: `OPENBRIDGE_TRACE_ENABLED=1` (or `--trace`)
- Per-request: send `X-OpenBridge-Trace: 1` (or `?openbridge_trace=1`)

2) **Optionally log the trace bundle**

- `OPENBRIDGE_TRACE_LOG=1` (or `--trace-log`)

When trace logging is enabled, OpenBridge emits a single line per completed/failed request:

```text
... | TRACE {...json...}
```

### Control trace content size / sensitivity

Trace data is sanitized by default. Configure via:

- `OPENBRIDGE_TRACE_CONTENT`:
  - `none`: do not store message content; keep only hashes and sizes
  - `truncate` (default): store truncated content
  - `full`: store full content (local dev only)
- `OPENBRIDGE_TRACE_MAX_CHARS` (default: `4000`): truncation budget per string field when using `truncate`

Example (local dev):

```bash
uv run openbridge --debug-endpoints --trace --trace-content full --trace-log --log-file ./openbridge.log
```

## Viewing traces without log files

If you prefer an on-demand workflow, enable debug endpoints and use the CLI viewer:

```bash
uv run openbridge --debug-endpoints --trace
uv run openbridge debug resp_...
uv run openbridge debug req_... --raw -o ./bundle.json
```

Notes:

- **IDs**: use a `resp_*` id (the Responses `id` returned by `POST /v1/responses`) or a
  `req_*` id (the `X-Request-Id` response header).
- **Remote server**: use `--base-url http://host:port` to point the CLI at a different
  OpenBridge instance.
- **Protected debug endpoints**: if `OPENBRIDGE_CLIENT_API_KEY` is set on the server,
  pass `--api-key ...` (or set `OPENBRIDGE_CLIENT_API_KEY` in your environment) so the CLI
  can send `Authorization: Bearer ...`.
- **Explicit kind**: if your id does not start with `req_` or `resp_`, use `--kind request|response`.
- **Raw / export**: `--raw` prints plain JSON, and `--output/-o` writes the bundle to a file.

Debug endpoints are disabled by default and should not be enabled on untrusted networks.
