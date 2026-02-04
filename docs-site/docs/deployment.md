# Deployment (Docker)

OpenBridge ships with a multi-stage `Dockerfile` and a ready-to-use `docker-compose.yml`.

## Docker Compose (recommended)

1. Create a local env file:

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY=...
```

2. Build and run:

```bash
docker compose up --build
```

The server is published to `http://127.0.0.1:8000` by default.

!!! note
    The container binds to `0.0.0.0:8000`, but the Compose port mapping is
    `127.0.0.1:8000:8000` to avoid accidental LAN exposure.

### Enable Redis-backed state/trace

The Compose file includes an optional Redis service behind the `redis` profile.

```bash
OPENBRIDGE_STATE_BACKEND=redis OPENBRIDGE_TRACE_BACKEND=redis \
  docker compose --profile redis up --build
```

If you enable either backend, point `OPENBRIDGE_REDIS_URL` / `OPENBRIDGE_TRACE_REDIS_URL`
at `redis://redis:6379/0` (the default in `docker-compose.yml`).

## Docker without Compose

```bash
docker build -t openbridge .
docker run --rm -p 127.0.0.1:8000:8000 -e OPENROUTER_API_KEY="sk-or-..." openbridge
```

## Security notes

- Do not expose OpenBridge on untrusted networks without authentication.
  Set `OPENBRIDGE_CLIENT_API_KEY` or place it behind an authenticated reverse proxy.
- Debug endpoints are disabled by default. If enabled, treat them as sensitive.

See also: [Configuration](configuration.md) and [Logging & tracing](logging.md).

