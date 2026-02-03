## ADR 0010: Log cached and reasoning token breakdowns

- **Status**: Accepted
- **Context**: Upstreams may report cached input tokens and reasoning output tokens via `*_tokens_details`.
- **Context**: A single input/output token count hides what was cached or attributed to reasoning.
- **Decision**: In request summary logs, report input tokens excluding cached tokens and display cached tokens separately when available.
- **Decision**: In request summary logs, report total output tokens and display `reasoning_tokens` separately when available.
- **Decision**: Compute throughput (tokens/s) from uncached input + total output when both are available.
- **Consequences**: Logs become more actionable for cost/performance analysis while keeping API `usage` schema unchanged.

