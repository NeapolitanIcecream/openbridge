# ADR 0002: State Handling for previous_response_id

- Status: Accepted
- Context: OpenRouter requests are stateless, but Responses clients can send `previous_response_id`.
- Decision: OpenBridge stores normalized chat messages and tool virtualization maps per response ID.
- Decision: `instructions` are transient and are not stored; each request injects its own system message.
- Decision: Storage backends are memory (default) or Redis with TTL; disabled mode returns 501.
- Consequence: `GET/DELETE /v1/responses/{response_id}` works only when state is enabled.
