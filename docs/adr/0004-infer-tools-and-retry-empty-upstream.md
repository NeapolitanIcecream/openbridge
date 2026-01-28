# ADR 0004: Infer Tools from Input Items and Retry Empty Upstream Completions

- Status: Accepted
- Context: Some clients send follow-up tool loop turns with `input` items (e.g. `function_call_output`) but omit `tools[]`.
- Decision: When `tools[]` is missing, OpenBridge infers minimal tool definitions from `input` tool call items to keep upstream Chat Completions valid.
- Decision: If tools are inferred and `tool_choice` is not provided, OpenBridge forces `tool_choice="none"` to avoid new tool calls.
- Context: Some upstreams occasionally return HTTP 200 with empty `choices` / empty assistant message for short replies.
- Decision: For non-stream requests, if translated output is empty and `max_output_tokens > 0`, OpenBridge retries once; otherwise it returns HTTP 502.
- Consequence: Tool loop follow-ups are more compatible and deterministic across providers.
