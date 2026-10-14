"""Low-cardinality HTTP metrics for the local ReleasePilot API."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)


class HttpMetrics:
    content_type = CONTENT_TYPE_LATEST

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "releasepilot_http_requests_total",
            "HTTP requests served by the ReleasePilot API.",
            labelnames=("method", "status"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "releasepilot_http_request_duration_seconds",
            "ReleasePilot API request duration.",
            labelnames=("method",),
            registry=self.registry,
        )

    def observe(self, method: str, status: int, elapsed_seconds: float) -> None:
        bounded_method = method if method in {"GET", "POST"} else "OTHER"
        self.requests.labels(bounded_method, str(status)).inc()
        self.duration.labels(bounded_method).observe(elapsed_seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)
