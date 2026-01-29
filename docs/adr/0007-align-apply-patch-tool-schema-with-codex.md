# ADR 0007: Align apply_patch tool schema with Codex

- Status: Accepted
- Context: Codex exposes `apply_patch` as either a custom grammar tool or a function tool; the function tool uses JSON args `{ "input": "<patch>" }`.
- Context: OpenBridge virtualizes tools as function tools when calling upstream Chat Completions.
- Decision: OpenBridge defines the virtualized `apply_patch` tool as a function tool with parameters `{ input: string }` and `additionalProperties: false`.
- Decision: Tool virtualization uses unprefixed function names that match external tool types, so `apply_patch` remains `apply_patch`.
- Consequence: Tool names and schemas round-trip cleanly between Codex, OpenBridge, and upstream Chat Completions.
- Consequence: Requests that introduce tool name collisions fail early with a clear error.
