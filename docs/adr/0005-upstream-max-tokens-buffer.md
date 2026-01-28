# ADR 0005: Add an Upstream max_tokens Buffer

- Status: Accepted
- Context: Some upstreams count hidden reasoning tokens within `max_tokens`, which can truncate short visible outputs (e.g. nonce echo, "OK") even when the Responses request sets `max_output_tokens`.
- Decision: OpenBridge adds a small buffer when mapping `max_output_tokens` → upstream `max_tokens`.
- Decision: The buffer is configurable via `OPENBRIDGE_MAX_TOKENS_BUFFER` (default: 64).
- Consequence: Short responses and tool-loop follow-ups become more reliable across providers.
- Consequence: Upstream token usage may be slightly higher than the client-requested `max_output_tokens` limit.
