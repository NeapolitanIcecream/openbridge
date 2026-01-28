# ADR 0003: Optional TLS for Local Proxies

- Status: Accepted
- Context: Some clients may attempt to connect to local base URLs via HTTPS (e.g. `https://127.0.0.1:8000`).
- Context: When OpenBridge serves plain HTTP, TLS handshakes show up as `Invalid HTTP request received.` and clients disconnect.
- Decision: OpenBridge remains HTTP by default, but supports HTTPS when `OPENBRIDGE_SSL_CERTFILE` and `OPENBRIDGE_SSL_KEYFILE` are provided.
- Decision: OpenBridge fails fast when only one of cert/key is configured, or when files are missing.
- Consequence: Users can either use an `http://` base URL for local development or enable TLS (or terminate TLS in a reverse proxy).
