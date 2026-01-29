from __future__ import annotations

import time

from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response


REQUEST_COUNT = Counter(
    "openbridge_requests_total",
    "Total HTTP requests",
    ["path", "method", "status"],
)
REQUEST_LATENCY = Histogram(
    "openbridge_request_latency_seconds",
    "HTTP request latency in seconds",
    ["path", "method"],
)


def metrics_response() -> Response:
    data = generate_latest()
    return Response(content=data, media_type="text/plain; version=0.0.4")


class RequestTimer:
    def __init__(self, method: str) -> None:
        self._method = method
        self._start = time.time()

    def observe(self, status_code: int, *, path: str) -> None:
        REQUEST_COUNT.labels(path, self._method, str(status_code)).inc()
        REQUEST_LATENCY.labels(path, self._method).observe(time.time() - self._start)
