## ADR 0009: Normalize Responses API usage schema

- **Status**: Accepted
- **Context**: OpenAI Responses API defines `usage` as `{ input_tokens, output_tokens, total_tokens, ... }`, while OpenRouter Chat Completions commonly returns `{ prompt_tokens, completion_tokens, total_tokens, cost, ... }`.
- **Context**: Some clients (e.g. Codex) deserialize Responses payloads strictly and may retry on schema mismatches.
- **Decision**: Normalize `usage` in OpenBridge Responses API outputs to the Responses schema (`input_tokens` / `output_tokens` / `total_tokens` and their `*_details`), mapping from `prompt_tokens` / `completion_tokens` when needed.
- **Decision**: Exclude OpenRouter-only fields (e.g. `cost`) from the Response `usage` object to maximize compatibility.
- **Decision**: Keep the raw upstream usage dict for request summary logs so cost and throughput can still be reported.
- **Consequences**: Improves client interoperability; Response `usage` becomes spec-aligned; OpenRouter-specific usage fields remain available in logs but not in the API response payload.

