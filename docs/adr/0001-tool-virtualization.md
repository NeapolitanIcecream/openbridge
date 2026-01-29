# ADR 0001: Tool Virtualization for OpenRouter Chat Completions

- Status: Accepted
- Context: OpenRouter Chat Completions reliably supports function tools; built-in tool shapes are not stable.
- Decision: OpenBridge always sends function tools upstream and virtualizes built-in/MCP tools into function tools.
- Decision: Virtualized tool function names match external tool types; name collisions are rejected early.
- Decision: A reverse map translates upstream tool_calls back into Responses output items.
- Consequence: Tool loops are consistent and do not rely on provider-side special cases.
- Consequence: Built-in tool behavior depends on the local executor, not OpenRouter.
