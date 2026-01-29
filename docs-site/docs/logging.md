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

Debug endpoints are disabled by default and should not be enabled on untrusted networks.
