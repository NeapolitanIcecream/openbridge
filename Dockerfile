# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

# Install system certificates for outbound HTTPS (OpenRouter).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder

# Install uv (copying the official static binaries).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies in a separate layer for better Docker caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Copy the project into the image and install it (non-editable).
COPY . /app
RUN uv sync --locked --no-dev --no-editable

FROM base AS runtime

WORKDIR /app

# Create a non-root user for runtime.
RUN useradd --create-home --uid 10001 app

# Copy the virtual environment built by uv.
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    OPENBRIDGE_HOST="0.0.0.0" \
    OPENBRIDGE_PORT="8000"

EXPOSE 8000

USER app

CMD ["openbridge"]
