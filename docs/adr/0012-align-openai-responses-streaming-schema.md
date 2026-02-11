# ADR 0012: Align Responses object + streaming events with OpenAI spec

- Status: Accepted
- Context: OpenAI Responses API (2026) defines `response.status`, `completed_at`, output item `status`, and streaming event fields like `sequence_number` and `item_id`.
- Context: Some strict clients (including Codex CLI) may retry or fail on schema mismatches or missing fields in Responses payloads / streaming events.
- Decision: Include core Response fields in OpenBridge outputs: `status`, `completed_at`, `error`, `text.format`, `truncation`, and stable defaults (`tool_choice=auto`, `tools=[]`, `metadata={}`).
- Decision: Add output item `status` and always include `output_text.annotations=[]` for message parts.
- Decision: Update streaming events to include `sequence_number` and `item_id`, and emit `response.in_progress` + `response.content_part.*` events for output text.
- Decision: Embed failure details under `response.error={code,message}` (no top-level `error` field) to match the API reference.
- Consequence: Improved interoperability with OpenAI-compatible SDKs and Codex; existing clients should continue working (payloads only gain fields).
