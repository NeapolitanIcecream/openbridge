# ADR 0011: Docker Deployment (uv + docker-compose)

- Status: Accepted
- Context: Users want a reproducible way to run OpenBridge without a local Python/uv install.
- Decision: Provide a multi-stage Dockerfile that installs dependencies via `uv sync --locked` and runs the `openbridge` CLI.
- Decision: The runtime container binds to `0.0.0.0:8000` by default and runs as a non-root user.
- Decision: Provide docker-compose with a minimal service and an optional Redis service (profile `redis`) for state/trace backends.
- Consequence: `uv.lock` remains the single source of truth for dependency resolution in the container image.
- Consequence: Redis-backed state/trace is available without changing application code.
