## ADR 0006: Debug trace channel for messages/payloads

- **Status**: Accepted
- **Context**: When clients (e.g. Codex) behave unexpectedly, users need to inspect the actual upstream `messages` and translated payloads to verify what OpenBridge sent/received.
- **Decision**: Add an optional trace capture pipeline that records sanitized snapshots (Responses request, Chat Completions payload, tool maps, upstream request id) keyed by `request_id` and `response_id`, and expose them via gated `/v1/debug/*` endpoints.
- **Security**: Debug endpoints are disabled by default. Trace data is sanitized/truncated by default, with an explicit opt-in for full content capture.
- **Storage**: Provide pluggable backends (`memory` for local dev, `redis` for multi-instance) with TTL and bounded in-memory size.
- **Consequences**: Faster root-cause analysis for translation/tool/streaming issues; small code complexity increase; operators must avoid enabling debug endpoints on untrusted networks without auth.
